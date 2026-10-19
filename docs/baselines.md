# Same-budget baselines on the RNGD+ATOM node

[Documentation](README.md) · [한국어](ko/baselines.md) · [End-to-end run](e2e.md) · [Roadmap](roadmap.md)

Live evidence for roadmap items W5 (the controller places and moves the serving pods, and the P:D rebalancer), W6
(measured profiles for the `optimal` policy) and W7 (same-budget baselines with energy, including the vendor's own
engine), run on 2026-10-19 on the node that carries both RNGD and ATOM cards (3 RNGD and 4 ATOM free at the start; a
second RNGD node was cordoned). The W2 sections (two model pools at once; KV across nodes over `tcp`) ran the same evening
on the same node, the second RNGD node still cordoned.

**Scope.** Llama-3.1-8B-Instruct, the graphs rngd-pd has compiled today (S=512), one node, KV over `shm`. Two real
traces clipped to what S=512 can serve, a few hundred requests per run, one run per cell. These are baselines for this
engine generation, not a performance claim for the hardware.

## Summary

| | Result |
|---|---|
| W5 | `rm-controller` `optimal` wrote `airm-placement` and `--apply` moved the rngd-pd Deployments to it, twice (prefill 2 / decode 1 RNGD with the shipped profiles, prefill 1 / decode 2 with the calibrated ones). Pods landed on the decided node with the decided card counts; `pd-smoke` through the llm-d gateway passed 32/32. Which cards a pod gets is the device plugin's choice, not the decision's. |
| W7 | **2 cards:** replication (two single-card `solo` instances) beats PD 1P+1D on goodput per card: Azure conversation at 1.52 req/s with 100 % SLO attainment (0.75 req/s per card) where 1P+1D reached 87.7 %; 1P+1D gives the most tokens per joule (1.17 tok/J against 0.76). **3 cards:** the calibrated `optimal` layout, PD 1P+2D, met the SLO for every request on both traces, like `solo` ×3, at 1.2× its tokens per joule; the shipped-profile choice 2P+1D reached 93.6 % and 77.5 %. **RNGD prefill → ATOM decode cannot meet a 100 ms TPOT SLO**: the ATOM decode graph takes 108 ms per token. |
| W6 | The profile table was off by 2× and more: RNGD prefill of a 400-token prompt takes 100 ms, not the 220 ms the old derived numbers gave, RNGD decode on the batched graph is 30 ms per token at any batch (not 17–24), ATOM decode is 108 ms on one card (not 40–52 on two). `profiles.yaml` now carries the measured values; `optimal` changes its choice from 2P+1D to 1P+2D, and 1P+2D did better on the cluster (100 % against 93.6 % and 77.5 %). |
| W7 vendor | **furiosa-llm 2026.3.0 aggregated** (one card per replica, FuriosaAI's pre-compiled Llama-3.1-8B) met the SLO for every request on both traces with 2 and 3 cards. It tied `solo` on goodput per card (offered-load bound) and on tokens per joule (0.74 against 0.76), with TPOT p90 17–19 ms against rngd-pd's 30–69 ms. **furiosa-llm has no PD mode** (no disaggregation option, no KV-transfer code, and FuriosaAI's llm-d guide lists it as unsupported), so there is no vendor PD row. |
| W5 rebalancer | `rm-controller --rebalance --apply` on the gateway's `airm_*` gauges moved P:D three times in an hour, each time toward the role under pressure (generations 5–7). Moving a card to decode for conversation ×2 raised attainment from ~10 % to 85 %. Moving one to prefill for code ×3 lowered it from 63–68 % to 45 %, because the rule does not model what the donor role loses. The predictive rule (both roles predicted after a move) made only the conversation move in a 50-minute live re-check and held 1P+2D through code ×3: 77–81 % there. |
| W2 multi-pool | Two models at once on disjoint cards, both placed by `rm-controller` (`--apply`, a PD pool and an aggregated `serve` pool): Llama-3.1-8B rngd-pd 1P+1D met the SLO for 97.6 % of Azure conversation ×1 with Qwen3-4B (furiosa-llm, one card) under the same load next to it, 98.0 % alone; Qwen 100 % in both. A re-run with one pool's spec changed (Llama decode RNGD → ATOM) patched only that pool's Deployments; the Qwen pod kept running untouched. |
| W2 cross-node KV | rngd-pd's new `tcp` transport carried real prefill KV (67 MB per request) from the RNGD prefill pod to a relay pod on a CPU node and back to the RNGD decode pod: 2,112/2,112 blobs byte-identical, 32/32 outputs identical to `shm`. The NPU node's 1 GbE link sets the speed: 0.08–0.09 GB/s per request, 0.117 GB/s per direction with 8 in flight, ~0.8 s per 67 MB leg. `profiles.yaml` `tcp` is now measured (0.08 GB/s, implemented); with it the two-node simulator rows no longer gain over one node (they would from 0.15–0.25 GB/s). NPU to NPU across two NPU nodes is unverified: the second NPU node stayed cordoned. |
| Found | rngd-pd's gateway `airm_tpot_p90_ms` was the engine step and did not see decode queueing ([rngd-pd#7](https://github.com/ai-computing/rngd-pd/pull/7)). rm-bench's trace prompts shared prefixes by accident (72 distinct texts), which a prefix cache exploits (fixed here). rngd-pd addressed an allocated card by its host index (`npu3` → `rngd:3`, out of range): fixed in [rngd-pd#5](https://github.com/ai-computing/rngd-pd/pull/5). The continuous decode worker stops serving for good once more than 8 requests wait with `PD_PREFETCH=1`: [rngd-pd#4](https://github.com/ai-computing/rngd-pd/issues/4). A process outside Kubernetes held one RNGD card, so a pod allocated that card failed with `EBUSY`. |

## Setup

| | |
|---|---|
| Serving | rngd-pd `main` plus [rngd-pd#5](https://github.com/ai-computing/rngd-pd/pull/5), chart `deploy/helm/rngd-pd` (card from the kubelet allocation, no `--chip` pins) |
| RNGD prefill | `--backend rngd-full --C 512 --group 2`, buckets 32–512 |
| RNGD decode | `--backend rngd --B 8 --group 8 --sched continuous` (continuous batching, 8 lanes) |
| ATOM decode | `--backend atom --B 4 --sched continuous`, artifact `decode_S512_B4_lm` (largest S=512 batch compiled), one card |
| `solo` | `--role solo --C 512 --group 2 --decode-group 8 --B 8 --sched continuous`: prefill and continuous decode on one card. The chart has no `solo` role, so a minimal Deployment from the same image and mounts (`airm-exp-solo`) ran N replicas behind one rngd-pd gateway with a targets file (`{model: {solo: <service>}}`); the Service spreads requests over the replicas |
| furiosa-llm | `furiosaai/furiosa-llm:2026.3.0`, `serve furiosa-ai/Llama-3.1-8B-Instruct` (pre-compiled artifact, tag `v2026.3`), one card per replica, N replicas behind one Service (`airm-exp-flm`), serving defaults; client `--api completions-stream` |
| KV | `shm` (`/dev/shm` staging), `PD_PREFETCH=0` for every reported run (see [the prefetch failure](#prefetch-on-collapses-under-load)) |
| Load | rm-bench `e2e --api completions`, Azure 2023 trace replay from its start, requests with input + output ≤ 511 tokens kept (`--max-total-tokens 511`, skip policy, as the `trace-*` scenarios do), 300 s schedule, concurrency 64, timeout 300 s |
| Rates | conversation at the trace rate (×1: 455 requests, 1.52 req/s) and half of it (×0.5: 212 requests, 0.71 req/s); code at the trace rate (×1: 222 requests, 0.74 req/s, bursts of over 10 req/s within a second) |
| SLO | rm-controller's: conversation TTFT p90 ≤ 2 s and TPOT p90 ≤ 100 ms; code TTFT p90 ≤ 4 s, TPOT p90 ≤ 100 ms; per request for attainment |
| Power | `--power prom`, 1 s sampling of Prometheus: `furiosa_npu_hw_power` (`label="rms"`) for the RNGD cards the pods were allocated, plus `RBLN_DEVICE_STATUS:CARD_POWER` for the ATOM card in use. Card power only (no host); idle cards outside the configuration are not counted |
| Procedure | worker pods restarted before every run (the engine has no request cancel, aicomp#43, so an overloaded run leaves a backlog), then a `pd-smoke` warm-up and an idle probe |

Goodput = requests that met both SLOs per second of schedule; per card = goodput ÷ cards in the configuration.
tok/J = output tokens ÷ card energy over the run.

## W5: the controller places and applies

```
rm-controller --spec examples/optimal.yaml --once --apply        # budget 6, kv_transport auto, mix azure-conv
rm-controller: 9 profiles, 2 decisions, generation 2 written; 2 deployment patch(es) applied
# decisions: prefill furiosa:0, furiosa:1; decode furiosa:3; shm; "est. 0.71 req/s (0.24/card) ... profiles partly estimated"
```

The release's prefill and decode Deployments carried `airm.ai-computing.io/pool: llama8b-pd-pool` and `role: prefill|decode`;
the patch set replicas 2 and 1, a required node affinity (RNGD label, the node's hostname) and the `accelerator-ids`
annotation. Pod logs:

```
[decode]  [chip] allocated by k8s: [0] -> using rngd:0
[prefill] [chip] allocated by k8s: [1] -> using rngd:1
[prefill] [chip] allocated by k8s: [3] -> npu3, using rngd:2      # after rngd-pd#5; before it: rngd:3, "device index out of range"
```

The node and the number of cards per role follow the decision; the card identities do not (the decision named
`furiosa:3` for decode, the device plugin gave decode `npu0`). Pinning a decided card needs the device plugin's
preferred-allocation hook or DRA; rngd-pd now always uses what the kubelet allocated, so the two never collide.

`pd-smoke` through the llm-d gateway (Envoy → InferencePool → EPP → rngd-pd gateway) on the controller's 2P+1D layout:

| Run | TTFT p90 | TPOT p90 | tok/s | Result |
|---|--:|--:|--:|---|
| 2P+1D, decode B=8 continuous, prefetch on (this run) | 1815 ms | 59.6 ms | 84.5 | PASS, 32/32 |
| 1P+1D, decode B=1 ([end-to-end run](e2e.md)) | 2350 ms | 208 ms | 53.9 | PASS, 32/32 |

After calibration ([W6](#calibration-w6)) the same spec chose prefill 1 / decode 2 (generation 3, `est. 1.52 req/s`), and
`--apply` scaled prefill to 1 and decode to 2; that layout's runs are in the tables below as `pd-1p2d-rngd`.

## W5: the P:D rebalancer, live

`rm-controller --rebalance --apply` ran as a loop (60 s rounds, hysteresis defaults: band 0.2, hold 3, cooldown
300 s) on the `airm-e2e` rngd-pd Deployments, budget 3 RNGD cards, SLO TTFT p90 ≤ 2 s and TPOT p90 ≤ 100 ms, reading
the rngd-pd gateway's `airm_ttft_p90_ms` / `airm_tpot_p90_ms` (the fallback when no vLLM histograms exist; the gauges
cover the last 512 requests). Spec: [`examples/rebalance-gateway.yaml`](../packages/rm-controller/examples/rebalance-gateway.yaml).
The load alternated between Azure code at ×3 (prefill-heavy: 1.9 req/s, p50 output 14 tokens) and Azure conversation
at ×2 (decode-heavy: 2.3 req/s, ~119 output tokens), 300 s replays back to back, `--api completions`, `PD_PREFETCH=0`.
Both rates are above what three cards serve within the SLO in any split, so each role in turn is under pressure.

| Time (UTC) | Load | Gateway TTFT / TPOT p90 | Pressure P / D | Decision |
|---|---|--:|--:|---|
| 15:43 | code ×3 starts on 1P+2D (generation 4) | 1,590 → 5,372 ms / 47 ms | 2.69 / 0.47 | target 2:1, held 3 rounds |
| 15:51 | | 5,769 ms / 47 ms | 2.88 / 0.47 | **generation 5: P:D 1:2 → 2:1**, both Deployments patched |
| 16:09 | conversation ×2 starts on 2P+1D | 815 ms / 159 → 557 ms | 0.25 / 5.57 | target 1:2, held 3 rounds |
| 16:13 | | 326 ms / 557 ms | 0.25 / 5.57 | **generation 6: P:D 2:1 → 1:2** |
| 16:25 | code ×3 starts on 1P+2D | 2,715 → 4,879 ms / 66 ms | 2.44 / 0.66 | target 2:1, held 3 rounds |
| 16:29 | | 4,879 ms / 66 ms | 2.44 / 0.66 | **generation 7: P:D 1:2 → 2:1** |
| 16:31–16:40 | code ×3 on 2P+1D | 4,055–4,800 ms / 314–378 ms | 2.0–2.4 / 3.1–3.8 | target 2:1 (both roles over; 2:1 has the lower worst need), no change |

Each change landed 3.5–8 minutes after the mix switched (three agreeing rounds, plus the window of 512 requests
turning over), and the new pods were serving about two minutes after the patch. Client view of each 300 s replay
(rm-bench, same SLO; runs during which the split changed lose the requests in flight on the removed pods):

| Load | Split | SLO attainment | TTFT p90 | TPOT p90 | Goodput req/s |
|---|---|--:|--:|--:|--:|
| conversation ×2 | 2P+1D (no move: gauge blind, see below) | 7.7 % | 50.3 s | 1,089 ms | 0.17 |
| conversation ×2 | 2P+1D → 1P+2D during the run | 10.7 % | 42.8 s | 525 ms | 0.25 |
| conversation ×2 | **1P+2D** | **85.1 %, 85.5 %** | 447 ms, 440 ms | 128 ms, 134 ms | **1.95, 1.96** |
| code ×3 | **1P+2D** (before the move) | **62.9 %, 68.4 %** | 5.8 s, 5.0 s | 69 ms, 67 ms | **1.22, 1.32** |
| code ×3 | 1P+2D → 2P+1D during the run | 40.0 %, 41.2 % | 5.4 s, 4.2 s | 337 ms, 366 ms | 0.77, 0.79 |
| code ×3 | 2P+1D (after the move) | 44.8 %, 45.5 % | 4.5 s, 4.6 s | 334 ms, 336 ms | 0.86, 0.87 |

- **The split follows the mix**: three changes in an hour, each in the direction of the role under pressure
  (generations 5, 6, 7), with the default hysteresis; nothing oscillated within a phase.
- **Conversation: the move was right.** Moving a card to decode took attainment from ~10 % to 85 % and goodput
  from 0.2 to 1.95 req/s at the same offered load.
- **Code: the move was wrong.** Taking a decode card for prefill cut TTFT p90 by about 15 % but multiplied TPOT
  p90 by five (67 → 335 ms), and attainment fell from 63–68 % to 45 %. The rule predicts the donor role from its
  current pressure, linearly (decode at 0.66 on two cards → 1.3 on one); on one card it measured 3.1–3.8. With short
  answers every decode admission loads 67 MB of KV inside the device lock (`PD_PREFETCH=0`), so one decode card
  that admits all of code ×3's requests saturates far sooner than linear. Both roles then read over 1, and the rule,
  comparing linear needs, keeps 2:1. Fixed by [the predictive rule](#the-predictive-rule): it predicts the donor role
  too and holds here.
- **Found: the gateway's TPOT gauge did not see decode queueing.** `airm_tpot_p90_ms` was the decode worker's
  median graph step (~30 ms), flat while requests queued for a lane: in the first conversation phase the client
  TPOT p90 was 1,089 ms and the gauge 30 ms, so the decode pressure read 0.3 and nothing moved. Fixed in
  [rngd-pd#7](https://github.com/ai-computing/rngd-pd/pull/7) (the gauge is now (wall − TTFT) / (tokens − 1) per request,
  what a client sees); the conversation and later phases above ran with it. Also fixed here: an unreadable metrics
  source (the gateway not up yet) no longer fails the controller's round, and each round logs its signals.

### The predictive rule

Fix ([`predict.py`](../packages/rm-controller/rm_controller/predict.py), PR `rebalance-predict`): before a move the
rebalancer predicts both roles' pressure at every split of the budget with `optimal`'s queueing model and the calibrated
profiles, and moves only if the predicted worst-role pressure drops by `margin` (20 %); otherwise it holds and logs why.
The model adds what the code ×3 move ran into: with `shm` (`admit_blocking` in the profiles) each decode admission stalls
the decode loop for the 67 MB KV load (42 ms at 1.6 GB/s), the lane wait counts in TPOT, and decode is fed what prefill
passes, so a second prefill card lets more of a burst through to the single decode card. The rate is fitted on the current
split: the rate at which the model reproduces an over-SLO role's reading is the pool's effective arrival rate (code ×3's
mean is 1.9 req/s, but 24 requests arrive in its busiest second), and a calm role's reading caps the rate it is predicted
at. The arrival rate and mean lengths from the metrics, or the workload's trace, are only the fallback. Hysteresis is unchanged.

On the signals of the run above (no `workload` in the spec, as live):

| Round (live run above) | Split | Pressure P / D | Linear rule | Predictive rule |
|---|---|--:|---|---|
| 16:29, code ×3 | 1P+2D | 2.44 / 0.66 | 2:1 (decode on one card estimated at 1.3; measured 3.1–3.8) | **hold**: 2:1 predicted P 0.12, D ∞ (decode saturates) |
| 16:13, conversation ×2 | 2P+1D | 0.16 / 5.57 | 1:2 | **1:2**: predicted P 0.13, D 0.33 |
| conversation ×2 after the move | 1P+2D | 0.22 / 1.31 | 1:2 (hold) | hold: 2:1 predicted D ∞ |
| 16:35, code ×3 | 2P+1D | 2.2 / 3.46 | 2:1 (hold) | hold: 1:2 predicted P ∞ (the prefill fit reads the burst-driven TTFT as near-saturation) |

The same decisions come out with the trace mixes of either load, the replay windows' mixes or the default mix.

**Simulated replay** (`python -m rm_controller.sim --episode`, [`episode.py`](../packages/rm-controller/rm_controller/episode.py)):
3 RNGD, Azure 2023 arrival times of the replayed windows (code ×3: 579 requests in 300 s, busiest second 24; conversation
×2: 698), three 300 s replays per phase, the rebalancer every 60 s on simulated gateway gauges with the live hysteresis,
pods ready two minutes after a move and in-flight work on a moved card lost. On top of the profiles it models rm-bench's 64
open requests, the in-loop KV load, prefill pods reached at random through a Service, and prefill under load at 1.5× the
idle profile (the idle profile replays code ×3 to a TTFT p90 of 1.2 s; live it was 5.0–5.8 s). SLO attainment per phase:

| Run | code ×3 | conversation ×2 | code ×3 | conversation ×2 | Moves |
|---|--:|--:|--:|--:|--:|
| fixed 1P+2D | 77.9 % | 99.1 % | 77.9 % | 99.1 % | – |
| fixed 2P+1D | 68.6 % | 3.0 % | 67.2 % | 3.0 % | – |
| linear rule from 1P+2D (as live) | 74.4 % | 56.3 % | 75.8 % | 56.3 % | 8 |
| **predictive rule from 1P+2D** | **77.9 %** | **99.1 %** | **77.9 %** | **99.1 %** | 0 |

| Run | conversation ×2 | code ×3 | conversation ×2 | code ×3 | Moves |
|---|--:|--:|--:|--:|--:|
| linear rule from 2P+1D | 68.7 % | 75.6 % | 56.3 % | 75.5 % | 7 |
| **predictive rule from 2P+1D** | **68.7 %** | **77.9 %** | **99.1 %** | **77.9 %** | 1 (2:1 → 1:2 at 180 s) |

The linear rule makes the code move (1:2 → 2:1 four minutes into each code phase), sees decode go over and moves back, so it
also enters every conversation phase on the wrong split. The predictive rule makes the conversation move at the same
round as the linear one and no code move. Sensitivity to the prefill factor: at 1.0 code's TTFT stays under the SLO, neither
rule moves on code, both make the conversation move; at 2.0 the replay makes 2P+1D the better split for code (71.9 % against
50.6 %), which the live run contradicts, and the predictive rule still holds 1P+2D there (it misses that move; the linear
rule's oscillation gets 57.5 %). Without the CSVs (60 s on/off bursts only) both rules make only the conversation move.

**Live re-check** (2026-10-19 17:37–18:30 UTC, same node, cards, Deployments, gateway build with rngd-pd#7, `PD_PREFETCH=0`
and load as the run above; controller at `adce9db`; started on 2P+1D, conversation first):

| Run | Load | Split | SLO attainment | TTFT p90 | TPOT p90 | Run above, same load and split |
|--:|---|---|--:|--:|--:|---|
| 1 | conversation ×2 | 2P+1D → 1P+2D (move at 17:43) | 8.2 % | 50.5 s | 544 ms | 10.7 % (move during the run) |
| 2 | conversation ×2 | 1P+2D (pods ready 17:45) | 76.4 % | 456 ms | 150 ms | |
| 3 | conversation ×2 | 1P+2D | 80.4 % | 487 ms | 147 ms | 85.1 %, 85.5 % |
| 4–6 | code ×3 | 1P+2D, held | 79.3 %, 78.4 %, 78.1 % | 5.2–5.3 s | 68–70 ms | 62.9 %, 68.4 % on 1P+2D; 44.8 %, 45.5 % after the move to 2P+1D |
| 7–8 | conversation ×2 | 1P+2D, held | 80.7 %, 84.8 % | 454 ms, 445 ms | 149 ms, 136 ms | 85.1 %, 85.5 % |
| 9–10 | code ×3 | 1P+2D, held | 80.9 %, 77.2 % | 5.0 s, 5.6 s | 70 ms | as runs 4–6 |

- **One move in 50 minutes, the right one**: 2:1 → 1:2 at the fourth round of the first conversation phase (decode
  pressure 5.33, predicted 1:2 P 0.13 D 0.33). Through both code ×3 phases it held 1P+2D at every round (P 2.4–2.7,
  D 0.69: "no split predicted better than now", 2:1 predicted with decode saturated).
- **Code ×3 attainment 77–81 %** on every run, against 63–68 % on the same split and 40–45 % after the linear rule's move
  in the run above. The split is the same as the run above's first code phase, so part of that difference is run to run
  (the earlier run had just come from a conversation phase with pods freshly patched); the 45 % level is what the predictive
  rule avoided.
- **Conversation ×2 on 1P+2D: 76–85 %**, as before (85 %). TTFT on code ×3 stays at 5 s, over the 2 s SLO: with three cards
  no split serves code ×3 within the SLO, and moving a card to prefill makes it worse.
- Not exercised live: a code move the model would predict to help (none exists on three cards for these loads).

## W7: same-budget baselines

### Azure conversation, ×0.5 (212 requests, 0.71 req/s)

| Deployment | Cards | SLO attainment | TTFT p90 | TPOT p90 | Goodput req/s | per card | Power W (peak) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD | 2 | 100.0 % | 246 ms | 33.1 ms | 0.70 | 0.35 | 155.9 (176) | 0.57 |
| replication: `solo` ×2 RNGD | 2 | 100.0 % | 186 ms | 30.0 ms | 0.70 | 0.35 | 212.2 (250) | 0.42 |
| RNGD prefill → ATOM decode | 2 | 0.0 % (70 of 212 timed out) | 39,984 ms | 3,116 ms | 0.00 | 0.00 | 93.6 (104) | 0.38 |
| PD 2P+1D RNGD (optimal, shipped profiles) | 3 | 100.0 % | 158 ms | 34.2 ms | 0.70 | 0.23 | 193.1 (207) | 0.46 |
| PD 1P+2D RNGD (optimal, calibrated) | 3 | 100.0 % | 192 ms | 33.1 ms | 0.70 | 0.23 | 242.4 (288) | 0.37 |
| replication: `solo` ×3 RNGD | 3 | 100.0 % | 191 ms | 30.7 ms | 0.70 | 0.23 | 277.4 (350) | 0.32 |

### Azure conversation, ×1 (455 requests, 1.52 req/s)

| Deployment | Cards | SLO attainment | TTFT p90 | TPOT p90 | Goodput req/s | per card | Power W (peak) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD | 2 | 87.7 % | 289 ms | 110.4 ms | 1.32 | 0.66 | 153.7 (168) | **1.17** |
| replication: `solo` ×2 RNGD | 2 | **100.0 %** | 186 ms | 32.1 ms | **1.51** | **0.75** | 236.1 (259) | 0.76 |
| vendor: furiosa-llm ×2 RNGD (aggregated) | 2 | **100.0 %** | 102 ms¹ | 18.1 ms¹ | **1.51** | **0.76** | 243.0 (297) | 0.74 |
| RNGD prefill → ATOM decode | 2 | 0.0 % (313 of 455 timed out) | 135,915 ms | 3,390 ms | 0.00 | 0.00 | 92.3 (105) | 0.38 |
| PD 2P+1D RNGD (optimal, shipped profiles) | 3 | 93.6 % | 249 ms | 85.4 ms | 1.41 | 0.47 | 200.7 (221) | **0.89** |
| PD 1P+2D RNGD (optimal, calibrated) | 3 | **100.0 %** | 336 ms | 38.7 ms | **1.51** | **0.50** | 257.7 (286) | **0.70** |
| replication: `solo` ×3 RNGD | 3 | 100.0 % | 200 ms | 31.6 ms | 1.51 | 0.50 | 317.0 (372) | 0.57 |
| vendor: furiosa-llm ×3 RNGD (aggregated) | 3 | 100.0 % | 91 ms¹ | 17.2 ms¹ | 1.51 | 0.50 | 319.4 (429) | 0.56 |

### Azure code, ×1 (222 requests, 0.74 req/s, short answers: p50 14 tokens)

| Deployment | Cards | SLO attainment | TTFT p90 | TPOT p90 | Goodput req/s | per card | Power W (peak) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD | 2 | 84.7 % | 281 ms | 143.4 ms | 0.62 | 0.31 | 98.2 (170) | **0.19** |
| replication: `solo` ×2 RNGD | 2 | **99.5 %** | 181 ms | 58.0 ms | **0.73** | **0.37** | 108.4 (208) | 0.17 |
| vendor: furiosa-llm ×2 RNGD (aggregated) | 2 | **100.0 %** | 64 ms¹ | 18.9 ms¹ | **0.74** | **0.37** | 109.6 (201) | 0.17 |
| RNGD prefill → ATOM decode | 2 | 0.0 % | 239 ms | 4,225 ms | 0.00 | 0.00 | 78.4 (108) | 0.21 |
| PD 2P+1D RNGD (optimal, shipped profiles) | 3 | 77.5 % | 793 ms | 195.6 ms | 0.57 | 0.19 | 138.6 (195) | 0.14 |
| PD 1P+2D RNGD (optimal, calibrated) | 3 | **100.0 %** | 1,675 ms | 69.2 ms | **0.74** | **0.25** | 144.0 (233) | **0.13** |
| replication: `solo` ×3 RNGD | 3 | 98.2 % | 185 ms | 47.7 ms | 0.72 | 0.24 | 160.2 (323) | 0.12 |
| vendor: furiosa-llm ×3 RNGD (aggregated) | 3 | 100.0 % | 52 ms¹ | 17.6 ms¹ | 0.74 | 0.25 | 152.8 (242) | 0.12 |

Every configuration served the same requests (the tok/s columns agree within 0.1 % when nothing timed out).

¹ furiosa-llm is measured with `--api completions-stream`: TTFT is the client's first streamed token, queueing
included, and TPOT the gaps after it. The rngd-pd rows use `--api completions` (non-streaming; TTFT from the
server's timing, a decode-lane wait lands in TPOT). The furiosa-llm latencies are therefore the stricter
measurement; the conversation ×0.5 table has no furiosa-llm row (not run).

### What the tables say

- **On two cards replication wins on goodput per card.** A `solo` card prefills on the card it decodes on, so a request
  never waits for a KV copy or for a lane on another card; at ×1 conversation two `solo` cards met the SLO for every
  request while 1P+1D, the same two cards, let 12 % miss TPOT. With S=512 prompts a prefill takes 30–65 ms, short next
  to a 100-token answer at 30 ms per token, so splitting the phases buys little here.
- **PD wins on energy.** 1P+1D drew 154 W for two cards against 236 W for two `solo` cards at the same load: the prefill
  card idles between short prefills and the decode card runs one fixed-width graph. At ×1 conversation it produced 1.17
  output tokens per joule, 1.5× the `solo` pair.
- **Where PD loses time.** With `PD_PREFETCH=0` the decode worker loads each request's 67 MB of KV from `/dev/shm` when it
  admits it, inside the device lock (31–54 ms), and every active stream waits. Azure code has short answers and many
  admissions, so client TPOT p90 rose to 143 ms (1P+1D) and 196 ms (2P+1D, which admits more often); TTFT stays low because
  with `--api completions` the client TTFT is the server's prefill time, and the decode queue shows up in TPOT.
- **2P+1D, the controller's first choice, is decode-bound**: it adds a prefill card that the conversation trace does not
  need (TTFT p90 249 ms against 289 ms) at 47 W more, and helps not at all on code.
- **1P+2D, the choice after calibration, is the best PD layout on three cards**: every request met the SLO on both traces,
  goodput per card equals `solo` ×3 (0.50 and 0.25 against 0.50 and 0.24) at 1.2× its tokens per joule (0.70 against 0.57
  on conversation). A second decode card halves the admissions (and their in-lock KV loads) per decode worker, the
  likely reason 2P+1D fell behind. The single prefill card shows on code's bursts (TTFT p90 1.7 s, within the 4 s SLO).
- **RNGD → ATOM** works end to end (prefill on RNGD, KV over `shm`, decode on one ATOM card) but cannot meet the SLO: the
  S=512 ATOM decode graph runs at 108 ms per token at any batch up to 4, so one ATOM decodes about 37 tokens/s against
  the 90–180 tokens/s these runs ask for. Requests queue for a lane; at ×1 conversation 313 of 455 hit the 300 s client
  timeout. This is an engine limit (graph speed and the B=4 ceiling at S=512), not a placement result.

### Vendor-only baseline: furiosa-llm (W7)

The vendor's own engine on the same cards: image `furiosaai/furiosa-llm:2026.3.0` (the one the cluster's k-exaone
and qwen3-4b deployments run), `furiosa-llm serve furiosa-ai/Llama-3.1-8B-Instruct`, the pre-compiled BF16 artifact
FuriosaAI publishes on Hugging Face (release tag `v2026.3`; tensor parallel over the 8 PEs of one card), served
under the name `meta-llama/Llama-3.1-8B-Instruct`. One card per replica (`furiosa.ai/rngd: 1`), N replicas of a
Deployment (`airm-exp-flm`) behind one Service, as for `solo`; serving defaults otherwise (prefix caching on,
default buckets). Same traces, SLOs, power query and node; client `--api completions-stream`.

| | furiosa-llm ×2 | `solo` ×2 | furiosa-llm ×3 | `solo` ×3 | PD 1P+2D |
|---|--:|--:|--:|--:|--:|
| conversation ×1: SLO / TTFT p90 / TPOT p90 | 100 % / 102 / 18.1 | 100 % / 186 / 32.1 | 100 % / 91 / 17.2 | 100 % / 200 / 31.6 | 100 % / 336 / 38.7 |
| conversation ×1: W / tok/J | 243 / 0.74 | 236 / 0.76 | 319 / 0.56 | 317 / 0.57 | 258 / 0.70 |
| code ×1: SLO / TTFT p90 / TPOT p90 | 100 % / 64 / 18.9 | 99.5 % / 181 / 58.0 | 100 % / 52 / 17.6 | 98.2 % / 185 / 47.7 | 100 % / 1,675 / 69.2 |
| code ×1: W / tok/J | 110 / 0.17 | 108 / 0.17 | 153 / 0.12 | 160 / 0.12 | 144 / 0.13 |

- **At these rates every 2- and 3-card layout that meets the SLO is offered-load bound**: goodput is the trace rate
  (1.51 and 0.74 req/s) for furiosa-llm, `solo` and PD 1P+2D alike, so goodput per card ties. The vendor engine is
  ahead on latency, not on these goodput figures: TPOT p90 17–19 ms against 30–69 ms for rngd-pd's graphs, TTFT
  p90 52–102 ms measured at the client against rngd-pd's server-side 181–336 ms (1,675 ms for PD 1P+2D on code).
- **Energy is a tie with `solo`** (0.74 against 0.76 tok/J on two cards, 0.56 against 0.57 on three): both keep
  every card busy with the whole request. PD 1P+1D's 1.17 tok/J remains the best energy figure on two cards, at
  87.7 % attainment.
- **furiosa-llm PD is not available, so there is no vendor PD row.** The 2026.3.0 `serve` CLI has no
  disaggregation, KV-transfer or role option (`furiosa-llm serve --help`), the installed packages (`furiosa_llm`,
  `furiosa-llm-native`, `furiosa-native-llm-common`) contain no disaggregation, NIXL or KV-connector code, and
  FuriosaAI's llm-d guide ("Deploying Furiosa-LLM with llm-d") states that Furiosa-LLM does not support
  prefill/decode disaggregation: its values deploy decode pods only (`prefill.create: false`) with the
  intelligent-inference-scheduling path. The vendor-only PD baseline (W7) waits on the vendor.
- **Prompt fix found on the way.** The first furiosa-llm runs reported a prefix-cache hit rate of 70 % on the Azure
  replays, which share no prefixes: rm-bench's trace prompts drew words through an affine index into a 72-word
  vocabulary, so there were only 72 distinct prompt texts. Fixed in this change (words from a hash stream; 2,000
  salted prompts now have 2,000 distinct 8-word heads); the furiosa-llm rows above are the reruns (hit rate
  ~10 %, mostly the `pd-smoke` warm-up). With the shared prefixes conversation TTFT p90 was 66 ms instead of
  102 ms. rngd-pd has no prefix cache, so its rows are unaffected.

### Prefetch on collapses under load

The same 2P+1D layout with rngd-pd's default `PD_PREFETCH=1`:

| Run | Sent | Failed | SLO attainment | tok/s |
|---|--:|--:|--:|--:|
| conversation ×0.5 | 212 | 0 | 100.0 % | 89.5 |
| conversation ×1 | 455 | 176 | 60.4 % | 67.7 |
| code ×1 | 222 | 173 | 22.1 % | 2.4 |
| conversation ×2 then code ×4, without a restart in between | 698, 814 | all | 0 % | 0 |

The decode log shows `TimeoutError: pull timeout: <req>/layer.0/k`. The prefetch map keeps 8 entries; an evicted
prefetch still consumes the request's KV from `/dev/shm`, the later load waits `PD_KV_PULL_TIMEOUT` (120 s) inside the
device lock, and the requests already taken from the queue are never answered. Details and fixes:
[rngd-pd#4](https://github.com/ai-computing/rngd-pd/issues/4). Without cancel (aicomp#43) the backlog survives the
client, so the next run fails until the pod restarts. All other runs here use `PD_PREFETCH=0`.

## Calibration (W6)

### Idle probe (server timings from the rngd-pd gateway, median of 3)

| Prompt tokens | 16 | 64 | 128 | 256 | 384 | 480 |
|---|--:|--:|--:|--:|--:|--:|
| RNGD prefill, PD (compute + download + KV save) | 67.5 | 68.4 | 78.0 | 89.4 | 98.2 | 181.2 |
| ↳ of which compute | 36.2 | 36.1 | 39.8 | 51.6 | 64.5 | 73.4 |
| RNGD prefill, `solo` (on the decode card) | 31.1 | 31.2 | 38.8 | 43.1 | 63.5 | 64.5 |
| KV load at decode admission, 67 MB over `shm` | 33.0 | 32.8 | 50.6 | 51.3 | 31.0 | 32.2 |

| Concurrent streams | 1 | 2 | 4 | 8 |
|---|--:|--:|--:|--:|
| RNGD decode, continuous B=8 graph, ms per token | 29.8 | 30.1 | 30.2 | 30.3 |
| RNGD `solo`, ms per token | 29.0 | 27.6 | 28.2 | 26.2 |
| ATOM decode, B=4 graph, ms per token | 108.2 | 108.1 | 108.6 | 108.6 (4 at a time) |

The prefill at 480 tokens varies with the device-to-host download (18–143 ms).

### Profiles before and after

| `profiles.yaml` | Before | After | Source now |
|---|--:|--:|---|
| RNGD `prefill_tok_s` / `prefill_overhead_ms` | 2500 / 60 (derived) | 12000 / 66 | measured, linear fit 16–384 tokens |
| RNGD `tpot_ms_b1` / `tpot_ms_bmax` | 17.0 / 24.0 (measured B=1 graph / estimate) | 30.0 / 30.3 | measured, continuous B=8 graph |
| RNGD `max_batch` | 8 (estimate) | 8 | measured |
| ATOM `group` | 2 | 1 | measured: the fp16 decode artifact runs on one card |
| ATOM `tpot_ms_b1` / `tpot_ms_bmax` | 40.0 / 52.0 (estimate / derived) | 108.2 / 108.6 | measured, S=512 B=4 graph |
| ATOM `max_batch` / `kv_tokens` | 8 / 4096 | 4 / 2048 | measured / derived (4 × 512) |
| ATOM `prefill_tok_s` | 600 (estimate) | 600 | still an estimate (not run) |
| `shm` `gb_s` | 0.6 | 1.6 | measured: load at admission, `PD_PREFETCH=0` (the 111 ms p90 of the end-to-end run was with prefetch) |

### Simulation against the runs

`python -m rm_controller.sim` on the same S=512-clipped mix (length quantiles of the clipped window, 60 s peak/mean
1.8 for conversation and 4.0 for code) at the runs' offered rates. Attainment = share of requests meeting both SLOs:

| Layout, trace, rate | Measured | Sim, old profiles | Sim, calibrated |
|---|--:|--:|--:|
| 1P+1D RNGD, conversation 0.71 req/s | 100.0 % | 100 % | 100 % |
| 1P+1D RNGD, conversation 1.52 req/s | 87.7 % | 98.2 % | 78.8 % |
| 2P+1D RNGD, conversation 1.52 req/s | 93.6 % | 98.4 % | 79.0 % |
| 1P+1D RNGD, code 0.74 req/s | 84.7 % | 100 % | 100 % |
| 2P+1D RNGD, code 0.74 req/s | 77.5 % | 100 % | 100 % |
| 1P+2D RNGD, conversation 1.52 req/s | 100.0 % | 100 % | 100 % |
| 1P+2D RNGD, code 0.74 req/s | 100.0 % | 100 % | 100 % |
| RNGD → ATOM, conversation 0.71 req/s | 0.0 % | 92.2 % | 0 % |
| RNGD → ATOM, code 0.74 req/s | 0.0 % | 100 % | 0 % |

Calibrated, the simulator gets the qualitative answer right where the old table did not (ATOM decode fails, conversation
×1 sits near the 90 % line), and is now pessimistic for chat: it puts the decode wait in TTFT, where the client measures
none with `--api completions`. It still misses what hurts PD on short answers, the KV load inside the decode loop at each
admission, and it has no model of single-card (`solo`) serving, which won here. Both are on the
[component card](components/rm-controller.md)'s list. The sim tables in the [rm-controller README](../packages/rm-controller/README.md)
were rerun with the calibrated profiles.

## W2: two model pools on one node (HUB-35)

Two models served at once on the RNGD+ATOM node, each pool placed by `rm-controller` on its own cards (2026-10-19,
19:10–19:50 UTC): **Llama-3.1-8B-Instruct** as rngd-pd PD 1P+1D on RNGD (`llama8b-pd-pool`, the `airm-e2e` release,
reached through the llm-d gateway) and **Qwen3-4B-FP8** on furiosa-llm 2026.3.0, aggregated, one RNGD card
(`qwen3-4b-pool`, Deployment `airm-exp-qwen`, reached through its Service). The Qwen Deployment copies the cluster's
`serve-furiosa-ai-qwen3-4b-fp8` (read only, left at 0 replicas): same image and arguments, FuriosaAI's pre-compiled
artifact (`max_model_len` 40,960), plus the pool/role annotations and a hostPath model cache.

The spec is [`examples/multi-pool.yaml`](../packages/rm-controller/examples/multi-pool.yaml) (topology; a `serve` pool is
the aggregated kind added in this change):

```
rm-controller --spec multi-pool.yaml --once --apply
rm-controller: 9 profiles, 3 decisions, generation 4 written; 3 deployment patch(es) applied
#  llama8b-pd-pool prefill  <npu-node>/furiosa:0   topology: ... highest peak ... shm keeps prefill and decode on one node
#  llama8b-pd-pool decode   <npu-node>/furiosa:1   topology: ... most memory ...
#  qwen3-4b-pool   serve    <npu-node>/furiosa:3   topology: serve ... (furiosa.RNGD, 1 replica(s), aggregated)
```

**No card shared.** The patches set replicas 1/1/1 and the node affinity; the device plugin gave the Llama prefill and
decode pods `npu1` and `npu0` and the Qwen pod `npu3` (its container sees only `/dev/rngd/npu3*`). Two minutes into the
concurrent run `furiosa-smi` showed `npu0` at 116 W / 57 % utilisation, `npu1` 56 W, `npu3` 82 W with 46.7 of 47.5 GiB
in use (furiosa-llm's KV pool); the decision's card names are not the device plugin's, as in W5.

**Both pools under load at once.** Azure conversation ×1 (455 requests, 1.52 req/s, input + output ≤ 511 tokens, 300 s)
replayed to each pool concurrently, then to each pool alone; SLO TTFT p90 ≤ 2 s, TPOT p90 ≤ 100 ms; power per pool
from its own cards (`--power prom`, `device=~"npu0|npu1"` and `"npu3"`). Llama through the llm-d gateway with
`--api completions`, Qwen through its Service with `--api completions-stream` (as the W7 vendor rows):

| Pool | Run | Cards | SLO attainment | TTFT p90 | TPOT p90 | Goodput req/s | per card | Power W (peak) | tok/J |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| Llama-3.1-8B, rngd-pd PD 1P+1D | **both pools at once** | 2 | 97.6 % | 243 ms | 61.8 ms | 1.47 | 0.74 | 162.8 (182) | 1.10 |
| Llama-3.1-8B, rngd-pd PD 1P+1D | alone (pods restarted) | 2 | 98.0 % | 198 ms | 61.4 ms | 1.48 | 0.74 | 162.1 (178) | 1.11 |
| Qwen3-4B-FP8, furiosa-llm ×1 | **both pools at once** | 1 | 100.0 % | 120 ms¹ | 24.3 ms¹ | 1.51 | 1.51 | 80.8 (95) | 2.23 |
| Qwen3-4B-FP8, furiosa-llm ×1 | alone | 1 | 100.0 % | 64 ms¹ | 20.4 ms¹ | 1.51 | 1.51 | 74.2 (81) | 2.43 |

¹ streaming, measured at the client (see the W7 footnote). All 455 requests of every run completed, none failed.

- **Each pool keeps its SLO next to the other.** Llama's attainment, TPOT and goodput are the same within run-to-run
  noise with and without the Qwen load (97.6 % / 98.0 %); Qwen meets the SLO for every request either way. The W7 cell for
  the same Llama layout and load read 87.7 % (an earlier day's pods); today's 98 % is within the spread of single runs.
- **What is shared is the host.** Qwen's client TTFT p90 doubled (64 → 120 ms) and its TPOT p90 rose by 4 ms while Llama
  ran; the cards are disjoint, so the likely cause is the host they share (CPU, PCIe root, the client machine), not the
  accelerators. Both stay far inside the SLO.
- One card of Qwen3-4B carries the same request stream as two cards of Llama-3.1-8B PD at about half the power per
  pool (81 W against 163 W); the models differ, so this is not a comparison of engines.

**A changed spec moves only that pool.** The spec was changed to decode Llama on ATOM (`decode: {accelerator:
rebellions.ATOM}`) and the controller re-run once; the Llama decode role had one Deployment per device type
(`airm-e2e-decode` annotated `accelerator: furiosa.RNGD`, `airm-exp-decode-atom` with the ATOM decode configuration of
the W7 RNGD → ATOM release, both behind the `airm-e2e-decode` Service):

```
rm-controller: 9 profiles, 3 decisions, generation 5 written; 2 deployment patch(es) applied
#  patch airm-e2e-decode       replicas 1 -> 0   decode of llama8b-pd-pool: no furiosa.RNGD cards in the decision
#  patch airm-exp-decode-atom  replicas 0 -> 1   decode of llama8b-pd-pool: 1 replica(s) on <npu-node>
#  airm-e2e-prefill            up to date
#  airm-exp-qwen               up to date
```

| Deployment | generation 4 | generation 5 |
|---|---|---|
| `airm-e2e-prefill` (Llama prefill) | 1 × `furiosa:0` | unchanged (no patch) |
| `airm-e2e-decode` (Llama decode, RNGD) | 1 × `furiosa:1` | 0 replicas |
| `airm-exp-decode-atom` (Llama decode, ATOM) | 0 replicas | 1 × `rebellions:0`, ready 51 s after the patch |
| `airm-exp-qwen` (Qwen) | 1 × `furiosa:3` | unchanged: same pod, started 19:11:43 UTC, 0 restarts before and after |

During the move a `pd-smoke` to each pool ran at the same time: Qwen 32/32 within the SLO; Llama 32/32 served by the ATOM
decode pod (same text as on RNGD for a fixed prompt), but outside the smoke SLO (TPOT p90 377 ms: the ATOM S=512 graph,
108 ms per token, with 8 requests on 4 lanes, as in W7). Here the changed role moved to a device type the other pool
does not use; the case where the new rule matters (decode moving ATOM → RNGD while the Qwen pool holds an RNGD card,
which a fresh placement would take) is covered by `test_changed_spec_moves_only_that_pool`.

## W2: cross-node KV over tcp (HUB-34)

**Setup.** rngd-pd's `tcp` transport (this change, [rngd-pd#9](https://github.com/ai-computing/rngd-pd/pull/9)):
the prefill worker pushes each layer's K and V (bf16 wire, 64 blobs of 1 MiB, 67.1 MB per request at S=512) to a
`TcpKVServer` over pooled TCP connections, the decode worker takes them from it; every blob carries a CRC-32 checked by
the server and by the receiver. The server ran as a **relay pod on a CPU-only node** (chart option `kvRelay`, image
`python:3.11-slim`, the standard-library `tcpkv.py` from a ConfigMap); the prefill (RNGD) and decode (RNGD) pods ran on
the NPU node, so **every KV byte crossed the network twice**: NPU node → relay node → NPU node. Release
`airm-exp-xnode` (rngd-pd chart, the `airm-e2e` values with `airm.kvTransport: tcp`, decode `--B 8 --sched continuous`,
`PD_PREFETCH=0`), its own gateway Service (not in the llama8b-pd InferencePool). The NPU node reaches the other nodes
over a **1 GbE** interface (node-to-node RTT 0.22 ms); that link, not the transport, bounds every number below.

**Byte-exact.** With `AIRM_KV_TCP_LOG=1` each worker logs size and SHA-256 of every blob it pushes or pulls. 33 requests
(1 + 16 sequential + 16 at concurrency 8): **2,112 of 2,112 blobs identical** (2.215 GB) between the prefill's push and
the decode's pull; the relay counted 0 CRC errors over the whole session (26,112 blobs, 27.4 GB, benchmarks included).

**Token-exact.** 16 fixed prompts (8–479 tokens, 32 output tokens, greedy), sequential and at concurrency 8, through the
same release with `airm.kvTransport` switched between `tcp` and `shm` (pods restarted, same cards): **32 of 32 outputs
identical** (text and token count), twice (with and without the audit log).

**Per request, in serving** (rngd-pd gateway `pd` timings, 16 prompts; save = the push still running after prefill
compute, load = the pull at decode admission):

| | `tcp` sequential | `shm` sequential | `tcp` 8 concurrent | `shm` 8 concurrent |
|---|--:|--:|--:|--:|
| KV save, p50 / p90 | 678 / 724 ms | 1.4 / 4.6 ms | 3,266 / 4,304 ms | 1.7 / 4.0 ms |
| KV load at admission, p50 / p90 | 816 / 896 ms | 31 / 45 ms | 1,305 / 1,378 ms | 30 / 36 ms |
| server TTFT, p50 / p90 | 778 / 839 ms | 104 / 112 ms | 3,330 / 4,766 ms | 318 / 782 ms |

**Link, measured** (`bench/kv_tcp_bench.py` inside the prefill pod, S=512-shaped bf16 KV, push to the relay then pull
back, N requests in flight; one-way time per request and its GB/s):

| In flight | Push p50 (GB/s) | Pull p50 (GB/s) | Both directions, GB/s | Byte-exact |
|--:|--:|--:|--:|---|
| 1 | 758 ms (0.089) | 832 ms (0.081) | 0.084 | yes |
| 2 | 1,182 ms (0.057) | 1,243 ms (0.054) | 0.111 | yes |
| 4 | 2,330 ms (0.029) | 2,290 ms (0.029) | 0.115 | yes |
| 8 | 4,427 ms (0.015) | 4,515 ms (0.015) | 0.117 | yes |
| 1, CRC off | 622 ms (0.108) | 707 ms (0.095) | 0.101 | yes |
| 8, CRC off | 4,592 ms (0.015) | 4,472 ms (0.015) | 0.117 | yes |

One request moves at 0.08–0.09 GB/s each way; with several in flight the 1 GbE interface saturates at 0.117 GB/s
(940 Mbit/s) and the per-request time grows linearly. The CRC costs ~15 % on a single stream and nothing once the
link is full.

**A live trace over it.** Azure conversation ×0.5 (212 requests, 0.71 req/s) through `airm-exp-xnode` with the KV over the
relay, pods restarted first, against the W7 `shm` cell of the same layout:

| Deployment | Cards | SLO attainment | TTFT p90 | TPOT p90 | Goodput req/s | per card | Power W (peak) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD, KV `tcp` via a relay node | 2 | 89.2 % | 1,727 ms | 83.3 ms | 0.62 | 0.31 | 151.7 (165) | 0.59 |
| PD 1P+1D RNGD, KV `shm` (W7) | 2 | 100.0 % | 246 ms | 33.1 ms | 0.70 | 0.35 | 155.9 (176) | 0.57 |

All 212 requests completed. The ~0.8 s pull at each admission stalls the decode loop (`PD_PREFETCH=0`), which shows in
TPOT; the push tail lands in TTFT. A `pd-smoke` (32 requests in 4 s) served all 32 but with TTFT p90 17.9 s: 8 req/s
× 67 MB is 4.6× what the link carries. The simulator, given the measured link, predicts this layout at 100 % (TTFT p90
983 ms, TPOT 30 ms): its replay does not charge the admission load to TPOT (the episode replay does), so it is optimistic
here, as it was for `shm` on short answers.

**Profiles and the two-node rows.** `profiles.yaml` `tcp`: `gb_s` 0.08 (was an estimate of 0.5), `latency_ms` 14 (64
round trips × 0.22 ms), `min_bytes` 67,108,864 (the whole S=512 buffer is sent), `admit_blocking: true`,
`implemented: true`, `source: measured`, scope `cluster`. Re-running `python -m rm_controller.sim --compare --requests
4000`: on two nodes `optimal` (per card and max goodput) now stays on one node over `shm` for every trace (0.813 req/s
Azure conversation, 0.943 code, as one node), and the best plan restricted to `tcp` has no SLO-feasible layout (goodput
0). With the 0.5 GB/s estimate the two-node column read 0.087–2.724 req/s (2.0–3.5× one node). Sweeping the bandwidth,
the two-node layouts come back between 0.15 and 0.25 GB/s and reach 2.73 (conversation, P 1 / D 3 RNGD) and 2.39 req/s
(code, P 3 / D 1) at 0.8 GB/s, so a 2.5 GbE or faster link between NPU nodes is what the two-node gain needs.
`python -m rm_controller.baselines --compare --requests 4000` is unchanged (its card sets are single nodes). Tables:
[rm-controller README](../packages/rm-controller/README.md#-simulation-topology-vs-optimal),
[component card](components/rm-controller.md).

**Not verified: NPU to NPU across two nodes.** The second RNGD node was cordoned and stayed so; both workers ran on the
one NPU node, and the cross-node hops were NPU node ↔ CPU relay node. A prefill on one NPU node with decode on another
(and the server beside the decode, one network leg instead of two) has not run. NIXL: the installed `nixl_cu12` wheel on
the NPU node ships `libplugin_UCX.so` and a UCX agent instantiates there with `UCX_TLS=tcp`, but no NIXL-over-UCX KV
path was built or measured here; rngd-pd's `nixl` transport stays the same-host HETERO_NPU path
([rngd-pd#8](https://github.com/ai-computing/rngd-pd/pull/8)).

## Caveats

- **One node, one engine generation.** Three RNGD and four ATOM cards, S=512 graphs, batch at most 8 (RNGD) and 4 (ATOM).
  The traces are clipped to requests that fit 511 tokens (in the replayed window 698 of 2,872 conversation and 366 of
  1,491 code requests), so these are short-context results.
- **Small runs.** 300 s schedules of 212–455 requests (the first minutes of each trace), one run per cell, no repetitions;
  differences of a few percent are within run-to-run noise.
- **Client view.** `--api completions` is non-streaming: TTFT is derived from the server's timing and does not include a
  wait for a decode lane, which appears in TPOT instead (aicomp#41 brings streaming).
- **Power** is card power from the exporters, sampled once a second from Prometheus's last scrape; host CPU, memory and
  the idle cards outside a configuration are excluded. `solo` ×3 includes three busy cards, PD 1P+1D two.
- **Shared node.** Another agent ran NIXL transfer benchmarks on one RNGD and one ATOM card from the host, outside
  Kubernetes; the first prefill pod allocated that RNGD card failed with `EBUSY` and was retried after the benchmark
  ended. Card identity for the ATOM power query came from `rbln-stat` (memory in use).
- **Routing.** Several prefill or decode pods behind one rngd-pd gateway are reached through a Kubernetes Service
  (connection-level spreading), and `solo` replicas the same way; no load-aware routing was involved.
- **Not run:** ATOM prefill, the `p2p` and `nixl` transports with live serving (`nixl` is verified byte- and
  token-exact outside serving, [rngd-pd#8](https://github.com/ai-computing/rngd-pd/pull/8)), RNGD decode at B > 8, GPUs.
- **Vendor rows** differ in client API (streaming completions) and engine defaults (prefix caching on); see the
  footnote to the tables. They ran after the rngd-pd rows, on the same cards, the same afternoon.
- **W2 runs** are single runs too. The multi-pool load came from one client host for both pools; the cross-node path had a
  relay on a third node (two network legs per request, one where the server sits beside decode), on a 1 GbE link, and both
  NPU workers on one NPU node because the second NPU node is cordoned.
- **Rebalancer run** is one sequence (code ×3, conversation ×2, code ×3), above capacity on purpose; the first
  conversation phase ran with the old TPOT gauge and is reported only for that finding.

## Changes made on the cluster

| Object | Change | Left as |
|---|---|---|
| `llm-serving/airm-e2e` (Helm) | upgraded to rngd-pd `main` chart with these values (no `--chip` pins, decode B=8 continuous, rngd-pd clone with #5 at `/app`); prefill/decode annotated for `--apply`; gateway env `PD_PREFETCH=0`; replicas set by `--apply` and `kubectl scale`; restarts between runs | all Deployments scaled to 0; previous values saved |
| `llm-serving/airm-placement` | `rm-controller` generation 2 (P 2 / D 1) then 3 (P 1 / D 2, calibrated profiles) | generation 3 (previous `manual` document saved) |
| `airm-exp-solo`, `airm-exp-solo-gw` (Deployments, Services) | created for the replication runs | deleted |
| `llm-serving/airm-exp-hetero` (Helm) | RNGD prefill + ATOM decode release | uninstalled |
| `airm-exp-flm` (Deployment, Service) | furiosa-llm replicas for the vendor baseline; model cache on a hostPath under `/var/tmp` | deleted; cache directory removed |
| `airm-exp-flm-probe`, `airm-exp-cleanup` (Pods) | read the furiosa-llm CLI and package; remove the cache | deleted |
| `llm-serving/airm-e2e` (rebalancer run) | gateway scaled to 1 with `PD_PREFETCH=0` and, for the second half, this run's rngd-pd checkout with rngd-pd#7 mounted at `/app`; prefill/decode replicas, affinity, `accelerator-ids` and generation annotation patched by `--apply` (generations 4–7); pods restarted once | all scaled to 0; gateway mount and `PD_PREFETCH=1` restored; annotations back to generation 3's cards |
| `llm-serving/airm-placement` | generations 4–7 written by the rebalancer | generation 3 document restored byte for byte |
| `llm-serving/airm-e2e`, `airm-placement` (predictive rule re-check, 17:37–18:30 UTC) | as the rebalancer run: gateway scaled to 1 with `PD_PREFETCH=0` and the rngd-pd#7 checkout at `/app`; generation 4 (2P+1D) then 5 (1P+2D) by `--apply` | Deployments and ConfigMap replaced with the saved objects (all at 0 replicas, generation 3 document byte for byte) |
| `airm-exp-nixl-check` (Pod) | 2 RNGD + 1 ATOM for the `nixl` transport check (rngd-pd#8) | deleted |
| `llm-serving/airm-e2e` (W2 multi-pool, 19:10–19:50 UTC) | gateway scaled to 1 with `PD_PREFETCH=0`; decode annotated `accelerator: furiosa.RNGD`; prefill/decode replicas, affinity and annotations patched by `--apply` (generations 4, 5); prefill/decode pods restarted once | Deployments and `airm-placement` replaced with the saved objects (all at 0 replicas, generation 3 document byte for byte) |
| `airm-exp-qwen` (Deployment, Service) | furiosa-llm Qwen3-4B-FP8 for the second pool, a copy of `serve-furiosa-ai-qwen3-4b-fp8` (which was only read); model cache on a hostPath under `/var/tmp` (5.4 GB) | deleted; cache removed (`airm-exp-cleanup` Pod, deleted) |
| `airm-exp-decode-atom` (Deployment) | ATOM decode for the Llama pool, the move to generation 5 | deleted |
| `llm-serving/airm-exp-xnode` (Helm) | rngd-pd chart from rngd-pd#9: RNGD prefill + RNGD decode on the NPU node, `kvRelay` pod on a CPU-only node, own gateway Service; switched between `tcp` and `shm`, restarts between runs | uninstalled |

No other Deployment or EPP was touched, and no node was cordoned, uncordoned or targeted by name: the cordoned RNGD
node stayed cordoned and nothing was scheduled on it. Raw results (`results/` is not tracked in this repository) stay with the
experiment logs on the node.

## Reproduce

```bash
# W5: place and apply (Deployments annotated airm.ai-computing.io/pool and /role)
rm-controller --spec packages/rm-controller/examples/optimal.yaml --once --apply
rm-bench e2e --scenario pd-smoke --api completions --gateway http://<llm-d gateway>/rngd/llama8b-pd/completions

# W7: one cell (gateway Service of the configuration, pods restarted first)
rm-bench e2e --scenario <conversation scenario with the 2 s / 100 ms SLO> --api completions --gateway http://<gateway> \
  --speedup 1 --max-total-tokens 511 --duration 300 --deployment pd-1p1d-rngd --cards 2 \
  --power prom --power-url http://<prometheus> \
  --power-query 'sum(furiosa_npu_hw_power{label="rms",device=~"npu0|npu1"})'
rm-bench compare results/*.json

# W7 vendor: furiosa-llm replicas behind one Service (one card each), streaming completions
rm-bench e2e --scenario <conversation scenario> --api completions-stream --gateway http://<furiosa-llm service>:8000   --speedup 1 --max-total-tokens 511 --duration 300 --deployment flm-agg-x2-rngd --cards 2 --power prom ...

# W5 rebalancer: loop with --apply, then alternate the mix through the rngd-pd gateway
rm-controller --spec packages/rm-controller/examples/rebalance-gateway.yaml --rebalance --apply --interval 60
rm-bench e2e --scenario <code scenario> --api completions --speedup 3 ...    # then conversation at --speedup 2

python -m rm_controller.sim --episode     # the same episode replayed, linear vs predictive rule

# W6: sim against the runs, and the README tables
python -m rm_controller.sim --compare --requests 4000

# W2 multi-pool: two pools (PD + aggregated serve), Deployments annotated pool/role; then change one pool and re-run
rm-controller --spec packages/rm-controller/examples/multi-pool.yaml --once --apply
rm-bench e2e ... --gateway http://<llm-d gateway>/rngd/llama8b-pd/completions --api completions &        # both at once
rm-bench e2e ... --gateway http://<qwen service>:8000 --model furiosa-ai/Qwen3-4B-FP8 --api completions-stream &

# W2 cross-node KV: rngd-pd chart (rngd-pd#9) with the relay on a CPU node
helm install <release> deploy/helm/rngd-pd -f <site values> --set airm.kvTransport=tcp --set kvRelay.enabled=true \
  --set kvRelay.nodeSelector.kubernetes\\.io/hostname=<cpu node> --set env.AIRM_KV_TCP_LOG=1    # audit log: size + sha256 per blob
python bench/kv_tcp_bench.py --server <release>-kv-relay:5577 --concurrency 1,2,4,8     # inside the prefill pod
```
