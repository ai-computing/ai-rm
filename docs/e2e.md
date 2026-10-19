# End-to-end run on the live cluster

[Documentation](README.md) · [한국어](ko/e2e.md) · [Status](status.md)

The first run of every layer together on the Kubernetes + llm-d cluster, on 2026-10-19: devices
discovered by L1 place the L3 serving pods, requests enter through the llm-d gateway and EPP, KV moves
over the named L2 transport, and L5 measures and displays the result through rm-core names only.

**Scope.** Llama-3.1-8B-Instruct, RNGD prefill + RNGD decode on one node, KV over `shm`, one
replica each (batch 1). This is a connectivity run with a smoke workload, not a performance benchmark;
the Optimus Prime engine is not involved.

## What ran

| Layer | Component (pinned) | On the cluster |
|---|---|---|
| L1 | rm_abstract_layer v0.4.1, chart 0.4.2 | DaemonSet `airm-system/rm-abstract-node`; 7 `AcceleratorProfile`s on etri-001 (3 RNGD + 4 ATOM), 2 on etri-esc8000-e11; node labels `airm.ai-computing.io/<vendor>.<model>` |
| L4 | llm-d-setup | CRD v0.1.1, `ScrapeConfig airm-pods`, `airm-placement` ConfigMap, airm dashboard; existing Gateway → `llama8b-pd-pool` → EPP |
| L3 | rngd-pd | Release `airm-e2e`: gateway (`app: llama8b-pd`, joins the pool), prefill on RNGD 0, decode on RNGD 1, pods placed by the L1 labels (`furiosa.RNGD` and `rebellions.ATOM` both present) |
| L2 | rngd-pd `shm` transport (`airm.kv_transports:shm`) | 67 MB of KV per 8B request through `/dev/shm` |
| L5 | rm-bench, lmd-top | `rm-bench e2e --scenario pd-smoke --api completions` through the llm-d gateway; lmd-top Infra ▸ Devices shows profiles, `airm_*` series and placement |

## Results

`pd-smoke`: 32 requests (Poisson 8 rps, concurrency 8, 16–128 prompt tokens, 16 output tokens).

| View | TTFT p90 | TPOT p90 | Throughput | KV transfer p90 | SLO |
|---|---|---|---|---|---|
| Client (rm-bench, through llm-d) | 2350 ms | 208 ms | 53.9 tok/s | — | PASS, 32/32 |
| Server (PD gateway `airm_*` in Prometheus) | 282 ms | 19.5 ms | — | 112 ms | — |

The client figures include queueing: eight concurrent requests meet a one-request-at-a-time
deployment, so the user-visible latency is dominated by waiting, not by the prefill or decode passes.
A single request answers "The three primary colors are" with " red, blue, and yellow. …" (TTFT 1.7 s
cold, TPOT 15.8 ms).

## Real traces

rm-bench replays public production traces with their real arrival times and lengths
(`rm-bench traces fetch`, data kept out of the repositories; see the rm-bench README). Their full
characterization and what each asks of the NPU stack: [workload traces](workload-traces.md).

| Trace (whole) | Requests | Mean / 60 s peak rps | Prompt p50 / p90 | Output p50 | Prefix-block reuse | Fits S=512 |
|---|---|---|---|---|---|---|
| Azure 2023 conversation | 19,366 / 1 h | 5.5 / 8.5 | 1041 / 2221 | 217 | — | 32 % |
| Azure 2023 code | 8,819 / 1 h | 2.6 / 10.5 | 1425 / 5479 | 13 | — | 22 % |
| BurstGPT (without fails, 1) | 1.4 M / 61 days | 0.27 / 18.3 | 472 / 1360 | 362 | — | 62 % |
| Mooncake conversation | 12,031 / 1 h | 3.4 / 4.1 | 8039 / 30220 | 364 | 28 % | 0 % |
| Mooncake tool-agent | 23,608 / 1 h | 6.7 / 7.8 | 6402 / 18998 | 30 | 49 % | 0 % |

The RNGD PD graph compiled for S=512 serves a quarter to a third of real chat traffic and none of the
long-context Mooncake requests; real-length evaluation needs larger compiled sequence lengths.

**Azure conversation replay on the PD path** (first 120 s of the trace, requests with input+output ≤ 511
kept (33 %), time stretched 5× to match one PD pair: 152 requests over 600 s, mean 0.25 rps, peak 0.33):

| View | TTFT p90 | TPOT p90 | Throughput | KV transfer p90 | Result |
|---|---|---|---|---|---|
| Client (rm-bench, through llm-d) | 188 ms | 78.9 ms | 34.0 tok/s | — | SLO PASS, 0 errors, 97.4 % of requests within SLO |
| Server (PD gateway `airm_*`) | 179 ms (window max 1535 ms) | 17.3 ms | — | 111 ms | — |

At this rate TTFT seen by the client matches the server's, but client TPOT is 4–5× the server's: when
real arrivals overlap, a request waits for the single decode instance, which the server-side per-token
figure does not show. Bursts push the server's TTFT p90 up to 1.5 s within the run.

## Found and fixed during the run

| Layer | Finding | Fix |
|---|---|---|
| L1 | `rbln-stat` numbers NPUs per device group, so a 4-ATOM node was reported as 2 | rm_abstract_layer 0.4.1: index from `rbln<N>` |
| L1 | `rbln-stat` cannot unpack under the read-only root; no ATOM was published | chart 0.4.2: writable `/tmp` |
| L1 | An ATOM re-created by the driver after a pod released it dropped out of the daemon's `/dev` | chart 0.4.2: `hostDev` mounts the host's `/dev` live (verified with an allocate/release cycle) |
| L3↔L5 | The PD gateway serves only non-streaming `/v1/completions`; rm-bench sent streaming chat | rm-bench `--api completions`, TTFT from the server's reported timing |
| L4↔L5 | llm-d-setup documents `airm-placement` as one `decisions.json` list; lmd-top read one key per workload and looked in namespace `llm-d` | lmd-top reads both layouts; `LMD_AIRM_NS` follows `LMD_NS` |

## Open items

- **Placement is manual.** No controller writes `airm-placement`; this run records the deployed placement
  with `placement: "manual"`. The reference `greedy` policy, run on the real profiles, put prefill and decode
  on the same card of a cordoned node with `loopback`. A real controller must keep P and D on one node for
  `shm`, use distinct cards, skip cordoned/NotReady nodes and pick a real transport.
- **The placement ConfigMap format is not in rm-core.** PROTOCOL.md §5.2 defines the `Placement` API only;
  llm-d-setup's `decisions.json` layout is the de-facto format. It should be made normative.
- **Card selection in rngd-pd.** `--chip -1` takes the first visible card; a privileged pod with `/dev/rngd`
  mounted sees every card, so prefill and decode collided until the cards were pinned. It should use the
  card the device plugin allocated.
- **Chart defaults.** rngd-pd's decode defaults to ATOM; overriding it to RNGD with a map merge kept the ATOM
  request (`rebellions.ai/ATOM: null` removes it).
- **Not exercised:** RNGD→ATOM decode, the `p2p` transport with live buffers, GPU nodes (no `nvidia-smi` in the
  daemon image), batching. Several nodes were NotReady, cordoned or under disk pressure during the run.

## Reproduce

Site values go in `deploy/clusters/<name>/` (untracked). Start from the examples in
[`deploy/clusters/example/`](../deploy/clusters/example/) and replace the `/path/to/...` host paths.

```bash
# L4: CRD, scrape config, placement ConfigMap, dashboard
components/l4-cluster/llm-d-setup/scripts/airm-install.sh apply all
# L1: node daemon
helm upgrade --install rm-abstract-node components/l1-accel/rm_abstract_layer/deploy/helm/rm-abstract-node \
  -n airm-system --create-namespace -f deploy/clusters/<name>/rm-abstract-node.values.yaml
kubectl get accp
# L3: PD serving behind the existing pool
helm upgrade --install airm-e2e components/l3-serving/rngd-pd/deploy/helm/rngd-pd \
  -n llm-serving -f deploy/clusters/<name>/rngd-pd.values.yaml
# L5: measure through the llm-d gateway route, then open lmd-top → 3 (Infra) → ] (Devices)
rm-bench e2e --scenario pd-smoke --api completions --kv-transport shm \
  --gateway http://<gateway>/rngd/llama8b-pd/completions --model meta-llama/Llama-3.1-8B-Instruct
```

Free the cards afterwards:
`kubectl -n llm-serving scale deploy airm-e2e-gateway airm-e2e-prefill airm-e2e-decode --replicas=0`
or `helm uninstall airm-e2e -n llm-serving`.
