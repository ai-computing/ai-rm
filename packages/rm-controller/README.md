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
python -m rm_controller.sim --episode            # the W5 rebalancer episode replayed, linear vs predictive rule
python -m rm_controller.baselines --compare      # DistServe- and HexGen-2-style baselines
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
type(s), the decode device type(s), how many instances of each, the nodes and the KV link so that **SLO-feasible goodput per
card** is highest, from:

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
| Mixed roles | `mixed_roles: true` (default): a role may hold instances of several types. Prefill: one M/G/c per type, arrivals split by routing weight = the rate that type's group takes with its own TTFT p90 within the SLO (so every group meets it); decode: split by capacity. One type per role is the case above, with the same numbers |
| Constraints | an instance's cards on one node; every prefill→decode type pair served by the plan's KV link; host-scope links (`shm`, `p2p`) keep the pool on one node; ≥ 1 instance per role; cards ≤ budget; `mixed_roles: false` → one device type per role |
| Objective | no rate: max goodput/card, then goodput; rate given: fewest cards that cover it; `objective: goodput`: max goodput |
| Search | exact enumeration over links × nodes × types² × instance counts (thousands of candidates at 32 cards); mixed roles add every pair of per-type count vectors within the cards and budget, visited by an upper bound (min(prefill, decode capacity) / peak) and cut when the bound cannot win; above 200,000 pairs a scope keeps one type per role and the reason says so |
| Fallback | no profile for any free type, `loopback`, an unknown transport, or nothing SLO-feasible → `topology` with the spec's counts, and the reason says so; a pool that leaves one choice gets topology's choice |

`kv_transport: auto` lets it pick among implemented links; `p2p` is offered only for RNGD → ATOM, where it was verified.
Each profile number is marked measured, derived or estimate in the file. RNGD and ATOM decode are measured on the live
S=512 graphs ([baselines](../../docs/baselines.md)), and so is the cross-node `tcp` link (rngd-pd's TCP transport through a
relay on another node, 1 GbE); ATOM prefill, A100 and the `p2p` and `cuda-ipc` links stay estimates until FASOP's NPU cost model ([aicomp #50](https://github.com/ai-computing/aicomp/issues/50)) or a sweep
replaces them.

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
mixed_roles: true                      # optimal: a role may mix device types (default true)
profiles: my-profiles.yaml             # optimal / rebalance / apply: throughput table (default: packaged)
pools:
  - pool: ...
    kv_transport: auto                 # optimal only: choose among implemented links
    workload: {trace: azure-conv}      # or {mean_input_tokens, mean_output_tokens, rate_rps, peak_ratio}
    budget: 6                          # most cards for this pool (optimal, rebalance)
    rebalance: {metrics: http://<pod>:8000/metrics, band: 0.2, hold: 3, cooldown_s: 300, margin: 0.2}
```

**Several pools, several models (HUB-35).** A spec lists any number of pools, each its own model; they are placed in
order and no card is given to two pools. A pool is either prefill/decode (as above) or aggregated, single-card replicas
of an engine that runs both phases (furiosa-llm, vLLM):

```yaml
  - pool: qwen3-4b-pool
    model: furiosa-ai/Qwen3-4B-FP8
    serve: {accelerator: furiosa.RNGD, count: 1}   # one `serve` decision; no kv_transport, no rebalance
```

An aggregated pool takes `count` free cards of the type (the node with the most of them first) under either policy: the
profiles describe the prefill/decode path, not another model's single-card serving. Its Deployment is annotated
`role: serve`. When the spec of one pool changes, that pool is placed on cards no other pool held in the previous
generation if it fits there, and every other pool keeps its decision, so a re-run moves only the changed pool
(live: [baselines](../../docs/baselines.md#w2-two-model-pools-on-one-node-hub-35)).

Examples: [`examples/spec.yaml`](examples/spec.yaml) (RNGD+RNGD over shm, with a rebalance section),
[`examples/hetero-p2p.yaml`](examples/hetero-p2p.yaml) (RNGD prefill, ATOM ×2 decode over same-host P2P),
[`examples/optimal.yaml`](examples/optimal.yaml) (optimal, `kv_transport: auto`, budget 6),
[`examples/multi-pool.yaml`](examples/multi-pool.yaml) (two models: Llama-3.1-8B PD and Qwen3-4B aggregated).

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
  instance / 2). The arrival rate and mean lengths come from `vllm:request_success_total` and the
  `vllm:request_prompt_tokens` / `vllm:request_generation_tokens` histograms, or the gateway's `airm_req_s` / `airm_tok_s`,
  else from the pool's `workload` trace statistics;
- or, without metrics, from the workload's trace statistics and the profiles (peak rate over one instance's capacity).

With metrics and a profile for both device types, the target comes from a prediction
([`predict.py`](rm_controller/predict.py)): both roles' pressure at every split of the budget, from `optimal`'s queueing
model (prefill M/G/c for the TTFT p90; decode lanes at the TPOT-SLO batch, the lane wait counted in TPOT, and each
admission stalling the decode loop for the KV load on a link marked `admit_blocking`, which `shm` is). The model is first
fitted to the current split: the rate at which it reproduces what an over-SLO role shows is the pool's effective arrival
rate (bursts the mean rate misses show up here), a calm role's own reading caps the rate it is predicted at, and decode is
fed what prefill passes, so a split with more prefill lets more of a burst through to decode. The best split becomes the
target only if its predicted worst-role pressure is below the current split's by `margin` (default 20 %); otherwise the
split holds, and the round's log line says why, e.g. `hold: no split predicted better than now 1:2 P 2.44 D 0.66; best
other 2:1 P 0.12 D inf at 6.37 req/s (prefill fit)`. A device type without a profile keeps the linear rule (needed
instances = current × pressure).

Hysteresis: nothing moves while both pressures are ≤ 1; a target must change the P:D ratio by more than `band`, be proposed
`hold` rounds in a row and come `cooldown_s` after the last change (`--once` uses hold 1, no cooldown). A new generation is
written only when the split, and so the decisions, change. With `topology` the split sets the role counts; with `optimal`
it fixes the instance counts and the policy still picks types, nodes and link.

**Apply mode (HUB-11, `--apply`).** Deployments annotated `airm.ai-computing.io/pool: <pool>` and
`airm.ai-computing.io/role: prefill|decode|serve` get a merge patch: `spec.replicas` (cards ÷ cards per instance), a
required node affinity on the label `airm.ai-computing.io/<vendor>.<model>` and `kubernetes.io/hostname` in the decision's
nodes, and the card ids in the pod-template annotation `airm.ai-computing.io/accelerator-ids` for charts that pin devices.
A role that mixes device types needs one Deployment per type, annotated `airm.ai-computing.io/accelerator: <vendor>.<model>`:
it follows only that type's cards and goes to 0 replicas when the decision has none. The decision's `reason` gives the
routing weights; the gateway must split traffic by them (the simulator does).
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
| azure-conv | 0.813 (0.406) | 0.000 (0.000) | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm |
| azure-code | 0.943 (0.472) | 0.000 (0.000) | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm |
| burstgpt | 0.025 (0.013) | 0.000 (0.000) | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-conv | 0.563 (0.281) | 0.000 (0.000) | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-tool | 0.950 (0.475) | 0.000 (0.000) | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm |

**2 nodes: 2 x (2 RNGD + 4 ATOM)** — goodput req/s (req/s per card); optimal's layout below the number

| Trace | topology RNGD/RNGD shm | topology RNGD/ATOM×2 p2p | optimal (per card) | optimal (max goodput) | optimal (max goodput, `tcp` only) |
|---|--:|--:|--:|--:|--:|
| azure-conv | 0.813 (0.406) | 0.000 (0.000) | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |
| azure-code | 0.943 (0.472) | 0.000 (0.000) | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |
| burstgpt | 0.025 (0.013) | 0.000 (0.000) | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |
| mooncake-conv | 0.563 (0.281) | 0.000 (0.000) | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |
| mooncake-tool | 0.950 (0.475) | 0.000 (0.000) | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |

What it shows, with these profiles:

- **The profiles are now mostly measured** on the S=512 graphs of the live baselines
  ([baselines](../../docs/baselines.md)): RNGD prefill 66 ms + 12 K tok/s, RNGD decode 30 ms per token at any batch up to 8
  (the continuous B=8 graph is fixed-width), ATOM decode 108 ms per token up to batch 4 on one card, `shm` 1.6 GB/s.
  `tcp` 0.08 GB/s + 14 ms, measured across nodes on the NPU node's 1 GbE link. ATOM prefill and `p2p` are still estimates.
- **On one node optimal is the RNGD/RNGD pool.** ATOM decode misses the 100 ms TPOT SLO at every batch, so any pool that
  decodes on ATOM has no goodput; the live RNGD → ATOM baseline met the SLO for 0 % of requests.
- **Across two nodes nothing is gained over the measured `tcp` link.** It moves 67 MB per request in ~0.85 s (the full
  S=512 buffer, on 1 GbE) and the trace prompts' KV in seconds, so no two-node plan meets the TTFT SLO: optimal stays on one
  node over `shm`, and the best `tcp` plan (last column; nothing SLO-feasible, so topology's 1P+1D) has no goodput. With the
  old estimate (0.5 GB/s, then a planned link) the same column read 0.087–2.724 req/s, 2.0–3.5× one node. Sweeping the
  bandwidth: the two-node layouts come back between 0.15 and 0.25 GB/s (2.5 GbE and up), and at 0.8 GB/s give 2.73 req/s
  for Azure conversation (P 1 / D 3 RNGD) and 2.39 for Azure code (P 3 / D 1), as the estimate did. NPU-to-NPU across two
  nodes is not measured: the second NPU node was cordoned, so the link was measured RNGD → CPU relay node → RNGD.
- The Mooncake rows are extrapolations: the S=512 graphs cannot serve those prompts at all, and the prefill rate is
  extended linearly past 512 tokens (attention's quadratic term ignored), so they are optimistic.
- Capacity is sized for each trace's 60 s peak (BurstGPT: 69×), which keeps the absolute rates low.
- The analytical model in `optimal` gives 0.68–0.93× the simulated goodput, conservative everywhere (column "Model est."
  in [the component card](../../docs/components/rm-controller.md)). Both read the same profiles; the live runs check the
  profiles themselves ([baselines](../../docs/baselines.md#calibration-w6)).

**Episode replay (`--episode`).** [`episode.py`](rm_controller/episode.py) replays W5's live rebalancer run: 3 RNGD cards
behind the rngd-pd gateway, Azure code ×3 and conversation ×2 replays alternating (real arrival times from the Azure 2023
CSVs under `$RM_BENCH_TRACES`, else the windows' statistics), the rebalancer in the loop every 60 s on the gateway's gauges,
with its hysteresis, a two-minute pod start and in-flight work lost on a moved card. On top of the profiles it models the
client's 64 open requests, the in-loop KV load at decode admission, prefill pods reached at random through a Service, and
prefill under load at 1.5× the idle profile (`--prefill-scale`). Results: [baselines](../../docs/baselines.md#the-predictive-rule).

## ⚖️ Baselines: DistServe- and HexGen-2-style placement

`python -m rm_controller.baselines --compare` runs two published placement algorithms, simplified
([`rm_controller/baselines.py`](rm_controller/baselines.py)), next to `topology` and `optimal` through the same simulator, on
a GPU-only node (4 A100), the NPU node (2 RNGD + 4 ATOM) and a mixed node (2 A100 + 2 RNGD + 4 ATOM):

- **distserve** (DistServe, OSDI'24, "high node-affinity" placement): one device type for both phases on one node; prefill
  sized by an M/D/1 queue against the TTFT SLO, decode by the largest TPOT-SLO batch, phases sized separately, then the
  instance counts and type with the best goodput per card. Its parallelism search is left out.
- **hexgen2** (HexGen-2, ICLR'25): cards → instances; a role per instance; max-flow source → prefill → (KV link) → decode →
  sink; roles refined by flips and swaps while the flow grows; idle instances dropped. Types may mix within a role. Per-edge
  link choice, flow-proportional routing and the parallelism search are left out.
- Helix (MILP over layer placement) is not modelled: our engines run whole-model instances.

A100 numbers are partly estimates (prefill rate and batch-1 TPOT from the datasheet; batch-64 TPOT derived from the
hetero-llm-d A100 run). The GPU link `cuda-ipc` (vLLM's NixlConnector path, 20 GB/s estimate) counts as available to every
policy here, although ai-rm has no transport plugin for it. 4,000 requests per run, seed 1:

**GPU only: 1 node, 4 A100** — goodput req/s (req/s per card); layout below the number

| Trace | topology (cuda-ipc) | optimal, per card | optimal, max goodput | distserve | hexgen2 |
|---|--:|--:|--:|--:|--:|
| azure-conv | 4.218 (2.109)<br>P 1x A100 / D 1x A100, cuda-ipc | 8.644 (2.881)<br>P 2x A100 / D 1x A100, cuda-ipc | 12.113 (3.028)<br>P 3x A100 / D 1x A100, cuda-ipc | 8.644 (2.881)<br>P 2x A100 / D 1x A100, cuda-ipc | 12.113 (3.028)<br>P 3x A100 / D 1x A100, cuda-ipc |
| azure-code | 1.040 (0.520)<br>P 1x A100 / D 1x A100, cuda-ipc | 3.160 (0.790)<br>P 3x A100 / D 1x A100, cuda-ipc | 3.160 (0.790)<br>P 3x A100 / D 1x A100, cuda-ipc | 3.160 (0.790)<br>P 3x A100 / D 1x A100, cuda-ipc | 3.160 (0.790)<br>P 3x A100 / D 1x A100, cuda-ipc |
| burstgpt | 0.163 (0.082)<br>P 1x A100 / D 1x A100, cuda-ipc | 0.341 (0.114)<br>P 2x A100 / D 1x A100, cuda-ipc | 0.348 (0.087)<br>P 2x A100 / D 2x A100, cuda-ipc | 0.341 (0.114)<br>P 2x A100 / D 1x A100, cuda-ipc | 0.348 (0.087)<br>P 2x A100 / D 2x A100, cuda-ipc |
| mooncake-conv | 0.536 (0.268)<br>P 1x A100 / D 1x A100, cuda-ipc | 1.953 (0.488)<br>P 3x A100 / D 1x A100, cuda-ipc | 1.953 (0.488)<br>P 3x A100 / D 1x A100, cuda-ipc | 1.953 (0.488)<br>P 3x A100 / D 1x A100, cuda-ipc | 1.953 (0.488)<br>P 3x A100 / D 1x A100, cuda-ipc |
| mooncake-tool | 0.814 (0.407)<br>P 1x A100 / D 1x A100, cuda-ipc | 2.904 (0.726)<br>P 3x A100 / D 1x A100, cuda-ipc | 2.904 (0.726)<br>P 3x A100 / D 1x A100, cuda-ipc | 2.904 (0.726)<br>P 3x A100 / D 1x A100, cuda-ipc | 2.904 (0.726)<br>P 3x A100 / D 1x A100, cuda-ipc |

**NPU only: 1 node, 2 RNGD + 4 ATOM** — goodput req/s (req/s per card); layout below the number

| Trace | topology (shm) | optimal, per card | optimal, max goodput | distserve | hexgen2 |
|---|--:|--:|--:|--:|--:|
| azure-conv | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm |
| azure-code | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm |
| burstgpt | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-conv | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-tool | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm |

**Mixed: 1 node, 2 A100 + 2 RNGD + 4 ATOM** — goodput req/s (req/s per card); layout below the number

| Trace | topology (shm) | optimal, per card | optimal, max goodput | distserve | hexgen2 |
|---|--:|--:|--:|--:|--:|
| azure-conv | 4.202 (2.101)<br>P 1x A100 / D 1x A100, shm | **11.780 (2.945)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 7.525 (2.508), P 2x RNGD / D 1x A100_ | **11.780 (2.945)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 7.525 (2.508), P 2x RNGD / D 1x A100_ | 4.218 (2.109)<br>P 1x A100 / D 1x A100, cuda-ipc | 11.935 (2.984)<br>P 2x RNGD+1x A100 / D 1x A100, shm |
| azure-code | 1.038 (0.519)<br>P 1x A100 / D 1x A100, shm | **3.019 (0.755)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 2.087 (0.696), P 2x RNGD / D 1x A100_ | **3.019 (0.755)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 2.160 (0.540), P 2x A100 / D 2x RNGD_ | 1.040 (0.520)<br>P 1x A100 / D 1x A100, cuda-ipc | 3.070 (0.767)<br>P 2x RNGD+1x A100 / D 1x A100, shm |
| burstgpt | 0.163 (0.081)<br>P 1x A100 / D 1x A100, shm | **0.289 (0.097)**<br>P 1x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 0.163 (0.082), P 1x A100 / D 1x A100, cuda-ipc_ | **0.362 (0.091)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 0.243 (0.081), P 2x RNGD / D 1x A100_ | 0.163 (0.082)<br>P 1x A100 / D 1x A100, cuda-ipc | 0.363 (0.091)<br>P 2x RNGD+1x A100 / D 1x A100, shm |
| mooncake-conv | 0.505 (0.253)<br>P 1x A100 / D 1x A100, shm | **1.930 (0.482)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 1.488 (0.496), P 2x RNGD / D 1x A100_ | **1.930 (0.482)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 1.488 (0.496), P 2x RNGD / D 1x A100_ | 0.536 (0.268)<br>P 1x A100 / D 1x A100, cuda-ipc | 2.196 (0.549)<br>P 2x RNGD+1x A100 / D 1x A100, shm |
| mooncake-tool | 0.802 (0.401)<br>P 1x A100 / D 1x A100, shm | **2.921 (0.730)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 2.102 (0.701), P 2x RNGD / D 1x A100_ | **2.921 (0.730)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 2.102 (0.701), P 2x RNGD / D 1x A100_ | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 3.151 (0.788)<br>P 2x RNGD+1x A100 / D 1x A100, shm |

What it shows, with these profiles (RNGD, ATOM and `shm` measured, A100 partly estimated):

- **GPU only**: unchanged by the calibration. `optimal` (per card) and `distserve` pick the same layouts on every trace;
  `optimal` (max goodput) and `hexgen2` agree too; topology's fixed 1:1 split loses 1.4–1.8× per card.
- **NPU only**: every policy, `hexgen2` included, picks RNGD/RNGD. With the measured ATOM decode (108 ms per token) no ATOM
  decode instance meets the TPOT SLO, so the max-flow search no longer adds them. Goodput is 2.4–26× the uncalibrated table
  (Azure conversation 0.336 → 0.813 req/s; BurstGPT unchanged at 0.025), from the measured RNGD prefill and `shm` load; the Mooncake rows are
  extrapolations past S=512.
- **Mixed**: the measured RNGD prefill (12 K tok/s, against the A100's estimated 10 K) changes the picks. `optimal` now
  pairs 2 RNGD + 1 A100 prefill with A100 decode on Azure conversation, Azure code and both Mooncake traces, for per card
  as well as max goodput (11.78 req/s on Azure conversation, 2.8× `distserve`'s homogeneous A100 pair); one type per role
  it would take 2 RNGD prefill + 1 A100 decode (7.53). `hexgen2` reaches the same 4-card layout without ATOM decode and is
  within 1–14 % of `optimal` (11.94 vs 11.78 req/s; Mooncake conversation 2.20 vs 1.93): the gap left is the shared
  prefill queue against `optimal`'s fixed weighted split. **Per-card choices now change with mixed roles on the mixed
  node** (before calibration they did not); everywhere else they are unchanged.
- The mixed rows assume RNGD → A100 KV over `shm`, which no ai-rm transport provides yet, and A100 numbers are partly
  estimates; they compare placement logic under one table, not hardware.
- W6's "optimal beats topology per card against a GPU-only baseline" holds in simulation: on 4 A100 it matches or beats
  the DistServe-style search and beats topology on every trace.

## ✅ Verified

- 90 tests (topology, optimal and mixed roles, aggregated `serve` pools beside PD pools, rebalancer and its predictor, health and re-placement, apply, simulator and episode replay, baselines, document bytes identical to 0.1's);
  `rm_core.conformance airm.placements topology optimal` PASS with rm-core v0.1.2; CI runs both.
- Read-only dry run on the live cluster (2026-10-19, topology): the shm pool went to `npu-node-1/furiosa:0` + `furiosa:1`, the
  placement the end-to-end run had pinned by hand, with the cordoned node skipped; the p2p pool went to RNGD 0 + ATOM 0, 1.
- Live on the RNGD+ATOM node (2026-10-19, [baselines](../../docs/baselines.md)): `optimal` (`examples/optimal.yaml`,
  budget 6) wrote generation 2 (prefill 2× RNGD, decode 1× RNGD, `shm`) and `--apply` patched the annotated rngd-pd
  Deployments (replicas 2 and 1, node affinity, `accelerator-ids`); the pods landed on the decided node with the decided
  number of cards, and the PD path passed `pd-smoke` through the llm-d gateway. Which cards a pod gets is still the
  device plugin's choice. With the calibrated profiles it chose prefill 1× / decode 2× RNGD (generation 3), `--apply`
  moved the Deployments to it, and that layout met the SLO for every request on both traces.
- `--rebalance --apply` live on the RNGD+ATOM node (2026-10-19) from the rngd-pd gateway's `airm_*` gauges: three P:D changes in
  an hour, each toward the role under pressure; right for conversation (attainment ~10 % → 85 %), wrong for code ×3 (63–68 %
  → 45 %, the donor role's loss is not modelled). See [baselines](../../docs/baselines.md#w5-the-pd-rebalancer-live).
- The predictive rule (2026-10-20): on the live run's signals it holds where the linear rule made the code ×3 move (2:1
  predicted with decode saturated; measured 3.1–3.8) and still makes the conversation move. Replayed in
  `python -m rm_controller.sim --episode` (W5's alternating load, real Azure arrival times), the linear rule moved 8 times
  and averaged 74–76 % on code and 56 % on conversation; the predictive rule held 1P+2D (78 %, 99 %), and from 2P+1D it made
  the conversation move and nothing else. Live re-check (2026-10-19, same load and cards, 50 min from 2P+1D): one move,
  2:1 → 1:2 four minutes into conversation ×2, then 1P+2D held through both code ×3 phases, 77–81 % attainment on every code
  run (the linear rule's move had given 40–45 %). See [baselines](../../docs/baselines.md#the-predictive-rule).

## 🗺 Roadmap

- [x] Use live load (queueing, TTFT/TPOT) and workload shape ([traces](../../docs/workload-traces.md)) in the choice (`--rebalance`, `optimal`)
- [x] Serving Deployments that follow the decisions (`--apply`); charts still have to pin cards from `accelerator-ids`
- [x] The `airm-placement` format made normative in rm-core's protocol (§5.4, v0.1.2)
- [x] An image (`ghcr.io/ai-computing/rm-controller`, [`Dockerfile`](Dockerfile)) and a Deployment in the umbrella chart [`charts/ai-rm`](../../charts/ai-rm)
- [x] Measured RNGD and ATOM-decode profiles from the live baselines
- [ ] ATOM prefill, `p2p` and A100 measured, FASOP NPU cost model (aicomp #50)
- [x] Device types mixed within a role (`mixed_roles`), routed by per-type weights
- [ ] Pooled (work-conserving) prefill routing across types in the model and the gateway; a KV link per type pair
- [ ] A cross-node KV transport, so that `optimal` can span nodes
- [x] Run `optimal` and `--apply` on the live cluster
- [x] Run `--rebalance` on the live cluster ([baselines](../../docs/baselines.md#w5-the-pd-rebalancer-live))
- [x] Rebalancer: predict both roles' pressure after a move (profiles, admission cost) and hold when no split is predicted better
- [ ] Rebalancer: check a move against the attainment measured after it (undo a move that made things worse)

## 📄 License

BSD-3-Clause, as [ai-rm](../../LICENSE).
