<div align="center">

<h1>rm-controller</h1>

<h3>Topology-aware and optimal placement for heterogeneous llm-d pools</h3>

<p>
  <strong>English</strong> · <a href="README.ko.md">한국어</a>
</p>

<p>
  <a href="https://github.com/ai-computing/ai-rm"><img src="https://img.shields.io/badge/ai--rm-L4%20cluster%20%26%20placement-fbbf24" alt="ai-rm layer L4"></a>
  <a href="https://github.com/ai-computing/rm-core/blob/v0.1.1/PROTOCOL.md"><img src="https://img.shields.io/badge/protocol-v0.1-7c5cff" alt="Protocol v0.1"></a>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml/badge.svg" alt="packages CI"></a>
  <img src="https://img.shields.io/badge/stage-first%20version-107e72" alt="Stage: first version">
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-64748b" alt="License: BSD-3-Clause"></a>
</p>

<p>
  <a href="#-quick-start"><b>Quick start</b></a> ·
  <a href="#-placement-policy"><b>Policy</b></a> ·
  <a href="#-spec"><b>Spec</b></a> ·
  <a href="#-control-loop"><b>Control loop</b></a> ·
  <a href="#-simulation-topology-vs-optimal"><b>Simulation</b></a> ·
  <a href="#-verified"><b>Verified</b></a> ·
  <a href="#-roadmap"><b>Roadmap</b></a>
</p>

</div>

---

**rm-controller** is the L4 placement controller of [ai-rm](https://github.com/ai-computing/ai-rm). It reads the
accelerators L1 publishes (`AcceleratorProfile`) with their health and the nodes' state, places the prefill/decode pools a
spec asks for, and writes the decisions to the `airm-placement` ConfigMap that the EPP scorer and lmd-top read (rm-core
PROTOCOL §5.4, `rm_core.placement`; key `decisions.json`). Optionally it rebalances P:D from load and patches the serving
Deployments to follow the decisions.

<table>
<tr>
<td width="33%" valign="top">
<b>🧭 Topology first</b><br>
Host-local KV paths keep prefill and decode on one node and on different cards; cordoned and NotReady nodes are never chosen.
</td>
<td width="33%" valign="top">
<b>🧮 Pools, not pods</b><br>
P:D 1:N per pool, pools placed in order without sharing a card, and an empty decision with its reason when nothing fits.
</td>
<td width="33%" valign="top">
<b>📝 Quiet when nothing changes</b><br>
The document's <code>generation</code> moves only when the decisions do; a valid placement is kept, and only a role that lost a card is re-placed.
</td>
</tr>
</table>

## 🚀 Quick start

```bash
pip install "rm-core @ git+https://github.com/ai-computing/rm-core@v0.1.2"   # rm-core>=0.1.2,<0.2 (not on PyPI)
pip install -e packages/rm-controller            # PyYAML; [k8s] adds the in-cluster client
rm-controller --spec packages/rm-controller/examples/spec.yaml --dry-run   # print what it would write
rm-controller --spec spec.yaml --once            # write when the decisions changed (generation +1)
rm-controller --spec spec.yaml --interval 60     # keep placing
rm-controller --spec spec.yaml --apply --dry-run # also print the Deployment patches (--apply alone patches)
rm-controller --spec spec.yaml --rebalance       # also move cards between prefill and decode (W5)
rm-controller --spec packages/rm-controller/examples/optimal.yaml --dry-run   # the optimal policy (W6)
python -m rm_core.conformance airm.placements topology optimal
python -m rm_controller.sim --compare            # topology vs optimal, simulated on trace statistics
```

Outside a pod it uses `kubectl` with the current kubeconfig; in a pod (`KUBERNETES_SERVICE_HOST` set) it uses the Python
client (`pip install -e "packages/rm-controller[k8s]"`). Exit status: 0 written or unchanged, 1 a pool could not be placed
(the document still records why), 2 usage or cluster errors.

## 🧭 Placement policy

Policy `topology`, entry point `airm.placements:topology`, built from what the first end-to-end run showed (ai-rm
[e2e](../../docs/e2e.md): rm-core's reference `greedy` put prefill and decode on one card of a cordoned node):

| Rule | Why |
|---|---|
| `shm`, `p2p`, `loopback` keep prefill and decode on **one node**; cards differ unless `loopback` | the KV path is host-local |
| cordoned and not-Ready nodes are skipped | a placement there cannot run |
| prefill takes the **highest peak** (for the workload's precision), decode the **most memory**; ties go to the lowest card index | compute-bound prefill, memory-bound decode, stable choices |
| `count` per role | P:D 1:N |
| pools are placed in order and never share a card | no double booking |
| nothing that fits → empty decisions with the reason | never a crash, always explainable |

Cards whose `AcceleratorProfile` reports them unhealthy (`spec.extra.health`, or `status.health` / a `Healthy` or `Ready`
condition that is not True) and nodes under disk, memory or PID pressure are skipped like cordoned ones.
`place()` keeps the rm-core per-workload contract (conformance PASS); `place_pd()` places a prefill/decode pair together.

### `optimal` (W6)

Policy `optimal`, entry point `airm.placements:optimal` (`placement: optimal` in the spec). It chooses the prefill device
type, the decode device type, how many instances of each, the nodes and the KV link so that **SLO-feasible goodput per card**
is highest, from:

- the free, healthy cards (types `vendor.model`, nodes) and optional per-role type filters;
- a throughput profile per device type (prefill tok/s, decode TPOT at batch 1 and at the max batch, KV capacity, cards per
  instance) and a cost per KV link (bandwidth, latency, scope host/cluster, verified type pairs):
  [`rm_controller/profiles.yaml`](rm_controller/profiles.yaml), or `--profiles` / `profiles:` for your own table;
- the workload mix: mean and p90 lengths, mean rate and 60 s peak/mean, from a trace's statistics (`workload: {trace:
  azure-conv}`) or given directly;
- the SLO (`ttft_p90_ms`, `tpot_p90_ms`) and a card `budget`.

| | |
|---|---|
| Decode | batch = largest with TPOT ≤ SLO and batch × (in + out) ≤ KV capacity; a type is ruled out if < 90 % of prompts fit its KV |
| TTFT p90 | prefill(p90 prompt) + KV(link, p90 prompt) + TPOT + p90 wait for a prefill server + p90 wait for a decode slot (M/G/c, Erlang C with Allen–Cunneen) |
| Goodput | highest rate with TTFT p90 ≤ SLO, ÷ peak/mean (sized for the 60 s peak) |
| Constraints | one device type per role (one Deployment each); an instance's cards on one node; host-scope links (`shm`, `p2p`) keep the pool on one node; ≥ 1 instance per role; cards ≤ budget |
| Objective | no rate: max goodput/card, then goodput; rate given: fewest cards that cover it; `objective: goodput`: max goodput |
| Search | exact enumeration over links × nodes × types² × instance counts (thousands of candidates at 32 cards) |
| Fallback | no profile for any free type, `loopback`, an unknown transport, or nothing SLO-feasible → `topology` with the spec's counts, and the reason says so; a pool that leaves one choice gets topology's choice |

`kv_transport: auto` lets it pick among implemented links; `p2p` is offered only for RNGD → ATOM, where it was verified.
Each profile number is marked measured, derived or estimate in the file. RNGD and ATOM decode are measured on the live
S=512 graphs ([baselines](../../docs/baselines.md)); ATOM prefill and the `p2p` and `tcp` links stay estimates until
FASOP's NPU cost model ([aicomp #50](https://github.com/ai-computing/aicomp/issues/50)) or a sweep replaces them.

## 📝 Spec

```yaml
namespace: llm-serving                 # where airm-placement lives (llm-d's namespace)
pools:
  - pool: llama8b-pd-pool              # InferencePool name
    model: meta-llama/Llama-3.1-8B-Instruct
    kv_transport: shm                  # airm.kv_transports name
    slo: {tpot_p90_ms: 100}
    prefill: {accelerator: furiosa.RNGD, count: 1}
    decode:  {accelerator: furiosa.RNGD, count: 1}
```

`accelerator` is `vendor.model`, as in the node labels `airm.ai-computing.io/<vendor>.<model>`. Optional keys:

```yaml
placement: optimal                     # topology (default) | optimal
objective: per_card                    # optimal: per_card (default) | goodput
profiles: my-profiles.yaml             # optimal / rebalance / apply: throughput table (default: packaged)
pools:
  - pool: ...
    kv_transport: auto                 # optimal only: choose among implemented links
    workload: {trace: azure-conv}      # or {mean_input_tokens, mean_output_tokens, rate_rps, peak_ratio}
    budget: 6                          # most cards for this pool (optimal, rebalance)
    rebalance: {metrics: http://<pod>:8000/metrics, band: 0.2, hold: 3, cooldown_s: 300}
```

Examples: [`examples/spec.yaml`](examples/spec.yaml) (RNGD+RNGD over shm, with a rebalance section),
[`examples/hetero-p2p.yaml`](examples/hetero-p2p.yaml) (RNGD prefill, ATOM ×2 decode over same-host P2P),
[`examples/optimal.yaml`](examples/optimal.yaml) (optimal, `kv_transport: auto`, budget 6).

## 🔁 Control loop

**Re-placement (W5).** A decision that is still valid is kept, so a recovered node does not move running pools. When a
placed card disappears, becomes unhealthy, or its node becomes unschedulable, only the role that lost it is re-placed (on the
same node when the KV path is host-local or an instance spans cards); if both roles lost cards, the pool is placed afresh.
The changed decision bumps `generation`, and its `reason` names the lost card and why (`gone`, `unhealthy`,
`node … unschedulable`).

**P:D rebalancer (W5, `--rebalance`).** For pools with a `rebalance:` section it computes a target split of the pool's card
`budget` between prefill and decode instances:

- from metrics: Prometheus text from a URL or file, one source or `{prefill: …, decode: …}`, with
  `vllm:num_requests_waiting` per role (role from a `role` / `llm-d.ai/role` label), the
  `vllm:time_to_first_token_seconds` and `vllm:time_per_output_token_seconds` histograms (windowed between reads), or the
  gateway's `airm_ttft_p90_ms` / `airm_tpot_p90_ms`, the names Optimus Prime exposes with
  [aicomp #45](https://github.com/ai-computing/aicomp/issues/45). Each role's pressure is max(latency / SLO, waiting per
  instance / 2); needed instances = current × pressure;
- or, without metrics, from the workload's trace statistics and the profiles (peak rate over one instance's capacity).

Hysteresis: nothing moves while both pressures are ≤ 1; a target must change the P:D ratio by more than `band`, be proposed
`hold` rounds in a row and come `cooldown_s` after the last change (`--once` uses hold 1, no cooldown). A new generation is
written only when the split, and so the decisions, change. With `topology` the split sets the role counts; with `optimal`
it fixes the instance counts and the policy still picks types, nodes and link.

**Apply mode (HUB-11, `--apply`).** Deployments annotated `airm.ai-computing.io/pool: <pool>` and
`airm.ai-computing.io/role: prefill|decode|serve` get a merge patch: `spec.replicas` (cards ÷ cards per instance), a
required node affinity on the label `airm.ai-computing.io/<vendor>.<model>` and `kubernetes.io/hostname` in the decision's
nodes, and the card ids in the pod-template annotation `airm.ai-computing.io/accelerator-ids` for charts that pin devices.
A Deployment that already matches gets no patch; an empty decision leaves its Deployment alone. `--apply --dry-run` prints
`{"document", "patches"}`. Without `--apply` only the ConfigMap is written, as before.

## 📊 Simulation: topology vs optimal

`python -m rm_controller.sim --compare` replays trace statistics (length quantiles, mean rate and 60 s peak/mean from
[workload traces](../../docs/workload-traces.md)) through a discrete-event model of the placement (FCFS prefill per
instance, KV handoff over the link, continuous-batching decode with KV-capacity admission) and finds the highest mean
rate at which ≥ 90 % of requests meet TTFT and TPOT: the goodput. SLOs: 2 s / 100 ms for Azure conversation and BurstGPT,
4 s / 100 ms for Azure code, 15 s / 100 ms for Mooncake (long prompts). 4,000 requests per run, seed 1:

**1 node: 2 RNGD + 4 ATOM** — goodput req/s (req/s per card); optimal's layout below the number

| Trace | topology RNGD/RNGD shm | topology RNGD/ATOM×2 p2p | optimal (per card) | optimal (max goodput) |
|---|--:|--:|--:|--:|
| azure-conv | 0.750 (0.375) | 0.000 (0.000) | 0.750 (0.375)<br>P 1x RNGD / D 1x RNGD, shm | 0.750 (0.375)<br>P 1x RNGD / D 1x RNGD, shm |
| azure-code | 0.999 (0.500) | 0.000 (0.000) | 0.999 (0.500)<br>P 1x RNGD / D 1x RNGD, shm | 0.999 (0.500)<br>P 1x RNGD / D 1x RNGD, shm |
| burstgpt | 0.024 (0.012) | 0.000 (0.000) | 0.024 (0.012)<br>P 1x RNGD / D 1x RNGD, shm | 0.024 (0.012)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-conv | 0.557 (0.279) | 0.000 (0.000) | 0.557 (0.279)<br>P 1x RNGD / D 1x RNGD, shm | 0.557 (0.279)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-tool | 0.948 (0.474) | 0.000 (0.000) | 0.948 (0.474)<br>P 1x RNGD / D 1x RNGD, shm | 0.948 (0.474)<br>P 1x RNGD / D 1x RNGD, shm |

**2 nodes: 2 x (2 RNGD + 4 ATOM)** — goodput req/s (req/s per card); optimal's layout below the number

| Trace | topology RNGD/RNGD shm | topology RNGD/ATOM×2 p2p | optimal (per card) | optimal (max goodput) | optimal (max goodput, planned tcp) |
|---|--:|--:|--:|--:|--:|
| azure-conv | 0.750 (0.375) | 0.000 (0.000) | 0.750 (0.375)<br>P 1x RNGD / D 1x RNGD, shm | 0.750 (0.375)<br>P 1x RNGD / D 1x RNGD, shm | 2.661 (0.665)<br>P 1x RNGD / D 3x RNGD, tcp, 2 nodes |
| azure-code | 0.999 (0.500) | 0.000 (0.000) | 0.999 (0.500)<br>P 1x RNGD / D 1x RNGD, shm | 0.999 (0.500)<br>P 1x RNGD / D 1x RNGD, shm | 2.195 (0.549)<br>P 3x RNGD / D 1x RNGD, tcp, 2 nodes |
| burstgpt | 0.024 (0.012) | 0.000 (0.000) | 0.024 (0.012)<br>P 1x RNGD / D 1x RNGD, shm | 0.024 (0.012)<br>P 1x RNGD / D 1x RNGD, shm | 0.082 (0.021)<br>P 1x RNGD / D 3x RNGD, tcp, 2 nodes |
| mooncake-conv | 0.557 (0.279) | 0.000 (0.000) | 0.557 (0.279)<br>P 1x RNGD / D 1x RNGD, shm | 0.557 (0.279)<br>P 1x RNGD / D 1x RNGD, shm | 1.129 (0.282)<br>P 2x RNGD / D 2x RNGD, tcp, 2 nodes |
| mooncake-tool | 0.948 (0.474) | 0.000 (0.000) | 0.948 (0.474)<br>P 1x RNGD / D 1x RNGD, shm | 0.948 (0.474)<br>P 1x RNGD / D 1x RNGD, shm | 1.977 (0.494)<br>P 2x RNGD / D 2x RNGD, tcp, 2 nodes |

What it shows, with these profiles:

- **The profiles are now mostly measured**, on the S=512 graphs of the live baselines
  ([baselines](../../docs/baselines.md)): RNGD prefill 66 ms + 12 K tok/s, RNGD decode 30 ms per token at any batch up to 8
  (the continuous B=8 graph is fixed-width), ATOM decode 108 ms per token up to batch 4 on one card, `shm` 1.6 GB/s.
  ATOM prefill and the `p2p` and `tcp` links are still estimates.
- **On one node optimal is the RNGD/RNGD pool.** ATOM decode misses the 100 ms TPOT SLO at every batch, so any pool that
  decodes on ATOM has no goodput; the live RNGD → ATOM baseline met the SLO for 0 % of requests.
- **Across two nodes it gains only with a cross-node KV transport**, which does not exist yet (`tcp` in the table is a
  planned link at an estimated 0.5 GB/s): 2.0–3.5× the goodput and up to 1.8× per card. Decode is now the bottleneck for
  chat (optimal adds decode instances for Azure conversation and BurstGPT) and prefill for Azure code.
- The Mooncake rows are extrapolations: the S=512 graphs cannot serve those prompts at all, and the prefill rate is
  extended linearly past 512 tokens (attention's quadratic term ignored), so they are optimistic.
- Capacity is sized for each trace's 60 s peak (BurstGPT: 69×), which keeps the absolute rates low.
- The analytical model in `optimal` gives 0.71–0.88× the simulated goodput (column "Model est." in
  [the component card](../../docs/components/rm-controller.md)). Both read the same profiles; the live runs check the
  profiles themselves ([baselines](../../docs/baselines.md#calibration-w6)).

## ✅ Verified

- 51 tests (topology, optimal, rebalancer, health and re-placement, apply, simulator, document bytes identical to 0.1's);
  `rm_core.conformance airm.placements topology optimal` PASS with rm-core v0.1.2; CI runs both.
- Read-only dry run on the live cluster (2026-10-19, topology): the shm pool went to `etri-001/furiosa:0` + `furiosa:1`, the
  placement the end-to-end run had pinned by hand, with the cordoned node skipped; the p2p pool went to RNGD 0 + ATOM 0, 1.
- Live on the RNGD+ATOM node (2026-10-19, [baselines](../../docs/baselines.md)): `optimal` (`examples/optimal.yaml`,
  budget 6) wrote generation 2 (prefill 2× RNGD, decode 1× RNGD, `shm`) and `--apply` patched the annotated rngd-pd
  Deployments (replicas 2 and 1, node affinity, `accelerator-ids`); the pods landed on the decided node with the decided
  number of cards, and the PD path passed `pd-smoke` through the llm-d gateway. Which cards a pod gets is still the
  device plugin's choice. With the calibrated profiles it chose prefill 1× / decode 2× RNGD (generation 3), and `--apply`
  moved the Deployments to it.
- Not yet run on the cluster: `--rebalance` (needs the vLLM metrics of aicomp #45 or the gateway's `airm_*`).

## 🗺 Roadmap

- [x] Use live load (queueing, TTFT/TPOT) and workload shape ([traces](../../docs/workload-traces.md)) in the choice (`--rebalance`, `optimal`)
- [x] Serving Deployments that follow the decisions (`--apply`); charts still have to pin cards from `accelerator-ids`
- [x] The `airm-placement` format made normative in rm-core's protocol (§5.4, v0.1.2)
- [x] An image (`ghcr.io/ai-computing/rm-controller`, [`Dockerfile`](Dockerfile)) and a Deployment in the umbrella chart [`charts/ai-rm`](../../charts/ai-rm)
- [x] Measured RNGD and ATOM-decode profiles from the live baselines
- [ ] ATOM prefill and `p2p` measured, FASOP NPU cost model (aicomp #50); a GPU type for the GPU-only baseline
- [ ] A cross-node KV transport, so that `optimal` can span nodes
- [x] Run `optimal` and `--apply` on the live cluster
- [ ] Run `--rebalance` on the live cluster

## 📄 License

BSD-3-Clause, as [ai-rm](../../LICENSE).
