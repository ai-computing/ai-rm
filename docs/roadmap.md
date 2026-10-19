# Roadmap: closing the gaps

[한국어](ko/roadmap.md)

A comparison against current systems (llm-d, NVIDIA Dynamo, vLLM + NIXL/LMCache, Mooncake, DistServe/Splitwise,
HexGen-2/Helix/ThunderServe) found one thing nobody else ships: prefill/decode serving across NPUs from
**different vendors**, with an explicit KV contract (layout, precision, ownership). It also found seven gaps.
This page tracks the plan for each.

Engine work belongs to Optimus Prime ([aicomp](https://github.com/ai-computing/aicomp)) and is tracked there as feature
requests. Everything else is done in the ai-rm repositories.

| | Gap | Where the field is | ai-rm side | Engine side (aicomp) |
|:-:|---|---|---|---|
| W1 | **Serving surface**: no streaming, completions only, greedy, fixed length | vLLM/SGLang: OpenAI-compatible streaming, sampling, cancel | rm-bench `--api chat`, GuideLLM and MLPerf result import | [#41](https://github.com/ai-computing/aicomp/issues/41) streaming + chat · [#42](https://github.com/ai-computing/aicomp/issues/42) sampling · [#43](https://github.com/ai-computing/aicomp/issues/43) cancel on disconnect |
| W2 | **Scale and maturity**: one node, B≤8, S=512, one model, cards pinned by site values | Production stacks run multi-node, continuous batching, long context | node-daemon image, umbrella chart, kind-based sim cluster in CI, multi-node and multi-pool placement, pods use their assigned card | [#44](https://github.com/ai-computing/aicomp/issues/44) multi-lane batched decode · [#51](https://github.com/ai-computing/aicomp/issues/51) S=2048+ |
| W3 | **KV transport standards**: own transport, not reachable from NIXL / vLLM | NIXL is the common KV transfer layer (Dynamo, llm-d, vLLM) | NIXL backend plugin for RNGD↔ATOM in hetero-npu-p2p, vLLM KV connector in rngd-pd, 0.1–4 GB transfer curves | [#47](https://github.com/ai-computing/aicomp/issues/47) layer-wise transfer · [#48](https://github.com/ai-computing/aicomp/issues/48) NIXL transport hook |
| W4 | **Cache reuse**: every request prefills from scratch | llm-d / Dynamo route by KV-cache hits; LMCache and Mooncake Store tier KV | EPP prefix-cache scorer config, LMCache / Mooncake Store evaluation, host-DRAM KV tier (rm-core `MemoryTier`) | [#46](https://github.com/ai-computing/aicomp/issues/46) KV block events + prefix reuse · [#52](https://github.com/ai-computing/aicomp/issues/52) host-DRAM KV tier |
| W5 | **Control loop**: static deployments, placement recorded but not enforced, no failure handling | Dynamo Planner rebalances P:D on SLOs; KEDA/HPA on queue metrics | rm-controller applies placements, P:D rebalancer, re-placement on node or card failure, KEDA autoscaling | [#45](https://github.com/ai-computing/aicomp/issues/45) `/metrics` · [#49](https://github.com/ai-computing/aicomp/issues/49) recovery from quarantine |
| W6 | **Formal scheduling**: rule-based placement | HexGen-2 (graph partition + max-flow), Helix (MILP), ThunderServe — all GPU-only | `optimal` placement policy over card types and KV link cost, placement format in the rm-core protocol | [#50](https://github.com/ai-computing/aicomp/issues/50) FASOP inference cost model + NPU profiles |
| W7 | **Evidence**: no baselines yet | Papers report goodput per card and SLO attainment against DistServe/vLLM | Same-budget baselines (same-vendor PD, vendor PD, replication), tok/J in every run, two paper drafts | — |

## Done means

| | Acceptance |
|:-:|---|
| W1 | `rm-bench run pd-smoke --api chat` passes and GuideLLM reports TTFT on the PD path |
| W2 | B≥8 decode and S≥2048 cover ≥85 % of the Azure conversation trace; pools span two nodes; `helm install` reproduces the stack; sim e2e runs on every PR |
| W3 | RNGD→ATOM transfer through a NIXL client, token-exact; transfer-time curve to 4 GB |
| W4 | Mooncake tool-agent replay: prefix hit rate > 0 and lower TTFT than no cache |
| W5 | Pods land where `airm-placement` says; P:D ratio follows the trace mix; a killed decode pod recovers within an error-rate bound |
| W6 | `optimal` beats `topology` on goodput per card under the same budget, compared with a GPU-only baseline |
| W7 | Result tables per trace against the three baselines, with tok/J |

## Progress (2026-10-19)

| | Done on the ai-rm side | Waiting for |
|:-:|---|---|
| W1 | rm-bench streaming client (TTFT/TPOT/ITL from SSE), GuideLLM and MLPerf import, `compare` | engine #41–#43 |
| W2 | node-daemon image `ghcr.io/ai-computing/rm-accel`, umbrella chart `charts/ai-rm`, kind sim e2e on every PR, rngd-pd uses its allocated card | engine #44, #51; a cross-node KV link |
| W3 | in progress: NIXL backend and transfer-time curve in hetero-npu-p2p | engine #47, #48 |
| W4 | EPP profiles `queue-kv`, `approx-prefix`, `precise-prefix` (load in the real EPP) | engine #46, #52 |
| W5 | rm-controller 0.2: `--apply`, `--rebalance`, health-aware re-placement; KEDA ScaledObjects | engine #45, #49 |
| W6 | `optimal` placement + simulator; placement document normative (rm-core v0.1.2, §5.4) | engine #50 (measured profiles) |
| W7 | power sampling (`--power prom`, live on RNGD/ATOM/GPU exporters), tok/J in every run | baseline runs in progress |

Progress is tracked in the hub's Plane project (modules W1–W7) and summarized in [status](status.md).
