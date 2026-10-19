# Same-budget baselines on the RNGD+ATOM node

[Documentation](README.md) · [한국어](ko/baselines.md) · [End-to-end run](e2e.md) · [Roadmap](roadmap.md)

Live evidence for roadmap items W5 (the controller places and moves the serving pods, and the P:D rebalancer), W6
(measured profiles for the `optimal` policy) and W7 (same-budget baselines with energy, including the vendor's own
engine), run on 2026-10-19 on the node that carries both RNGD and ATOM cards (3 RNGD and 4 ATOM free at the start; a
second RNGD node was cordoned).

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
| W5 rebalancer | `rm-controller --rebalance --apply` on the gateway's `airm_*` gauges moved P:D three times in an hour, each time toward the role under pressure (generations 5–7). Moving a card to decode for conversation ×2 raised attainment from ~10 % to 85 %. Moving one to prefill for code ×3 lowered it from 63–68 % to 45 %, because the rule does not model what the donor role loses. |
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
  comparing linear needs, keeps 2:1. The rebalancer needs a donor model (the profiles' per-instance capacity, or the
  admission cost) and should check a move against the attainment it measures afterwards; recorded for W5.
- **Found: the gateway's TPOT gauge did not see decode queueing.** `airm_tpot_p90_ms` was the decode worker's
  median graph step (~30 ms), flat while requests queued for a lane: in the first conversation phase the client
  TPOT p90 was 1,089 ms and the gauge 30 ms, so the decode pressure read 0.3 and nothing moved. Fixed in
  [rngd-pd#7](https://github.com/ai-computing/rngd-pd/pull/7) (the gauge is now (wall − TTFT) / (tokens − 1) per request,
  what a client sees); the conversation and later phases above ran with it. Also fixed here: an unreadable metrics
  source (the gateway not up yet) no longer fails the controller's round, and each round logs its signals.

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
| `airm-exp-nixl-check` (Pod) | 2 RNGD + 1 ATOM for the `nixl` transport check (rngd-pd#8) | deleted |

No other Deployment or EPP was touched. Raw results (`results/` is not tracked in this repository) stay with the
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

# W6: sim against the runs, and the README tables
python -m rm_controller.sim --compare --requests 4000
```
