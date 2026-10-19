# rm-controller — L4 카드

> 위치: ai-rm [`packages/rm-controller`](../../packages/rm-controller) (in-tree). 정책 `airm.placements:topology`,
> `airm.placements:optimal`.

AcceleratorProfile(L1)과 노드 상태를 읽어 prefill/decode 풀을 배치하고, 결정을 ConfigMap `airm-placement`(hetero-llm-d
`deploy/airm/README.md`의 `decisions.json` 형식)에 씁니다. EPP scorer와 lmd-top이 이 ConfigMap을 읽습니다.

## 현재 (2026-10-19, 1차 구현)
- 정책 `topology`: host-local KV 경로(`shm`, `p2p`, `loopback`)는 prefill·decode를 한 노드에, 카드는 서로 다르게(`loopback` 제외).
  cordon·NotReady 노드 제외, prefill은 최고 peak, decode는 최대 메모리, 동점은 낮은 카드 번호. 역할별 `count`로 P:D 1:N.
  풀은 순서대로 배치하고 카드를 공유하지 않습니다. 들어갈 곳이 없으면 이유와 함께 빈 결정(종료 코드 1).
- `generation`은 결정이 바뀔 때만 증가합니다.
- 검증: 테스트 12개(실제 클러스터 모양의 풀), `rm_core.conformance airm.placements topology` PASS, 실제 클러스터 dry-run에서
  shm 풀 → `etri-001/furiosa:0` + `furiosa:1`(e2e 수동 배치와 동일), p2p 풀 → RNGD 0 + ATOM 0,1.

## 2차 구현 (2026-10-19, 로드맵 W5·W6, rm-controller 0.2.0)
- 문서 형식은 rm-core v0.1.2 `rm_core.placement`(PROTOCOL §5.4)를 그대로 씁니다. 0.1이 쓴 ConfigMap과 바이트가 같아 generation이
  움직이지 않습니다(`rm-core>=0.1.2,<0.2`).
- **`optimal` 정책 (W6)**: 장치 종류별 처리량 프로파일(`rm_controller/profiles.yaml`, 측정·유도·추정 표시), KV 링크 비용, 워크로드
  구성(트레이스 통계), SLO, 카드 budget으로 prefill/decode 종류·개수·노드·링크를 완전 열거로 골라 SLO를 지키는 카드당 goodput을
  최대화. 프로파일 없음·`loopback`·불가능하면 이유를 남기고 `topology`로 대체. 모델과 제약은 패키지 README 참고.
- **P:D 재조정 (W5, `--rebalance`)**: vLLM 이름 지표(`vllm:num_requests_waiting`, TTFT/TPOT 히스토그램, aicomp #45)나 게이트웨이
  `airm_*`, 또는 트레이스 통계로 목표 분할을 계산. band·hold·cooldown 히스테리시스, 바뀔 때만 새 generation.
- **상태 인지 재배치 (W5)**: NotReady·cordon·Disk/Memory/PID pressure 노드와 비정상 카드 제외. 유효한 결정은 유지하고, 카드를
  잃은 역할만 다시 배치(이유를 `reason`에 기록), generation 증가.
- **적용 모드 (HUB-11, `--apply`)**: `airm.ai-computing.io/pool`·`role` annotation이 있는 Deployment에 replicas, node affinity
  (`airm.ai-computing.io/<vendor>.<model>`, hostname), `accelerator-ids` annotation을 patch. `--dry-run`은 patch를 출력. 기본 동작은 그대로.
- **시뮬레이터**: `python -m rm_controller.sim --compare`. 아래 표(영문).
- 검증: 테스트 51개, `rm_core.conformance airm.placements topology optimal` PASS(rm-core v0.1.2). `optimal`·`--rebalance`·
  `--apply`는 아직 실제 클러스터에서 실행하지 않았습니다(가짜 IO와 시뮬레이션만).

## Simulation: topology vs optimal (EN)

`python -m rm_controller.sim --compare --requests 4000` (seed 1). Requests are drawn from the trace atlas statistics in
[workload traces](../workload-traces.md) (length p50/p90/p99, mean rate, 60 s peak/mean as an on/off burst model) and run
through a discrete-event model of each placement: FCFS prefill per instance, KV handoff over the link, continuous-batching
decode limited by the TPOT-SLO batch and KV capacity. Goodput = highest mean rate at which ≥ 90 % of requests meet both TTFT
and TPOT. "Model est." is the `optimal` policy's analytical estimate for the same layout (0.43–1.25× the simulated value).
Card sets: one node with 2 RNGD + 4 ATOM, and two such nodes. `tcp` is a planned cross-node link (estimate, no transport
plugin yet), offered only in the row that says so.

**1 node: 2 RNGD + 4 ATOM**

| Trace (SLO TTFT/TPOT p90) | Policy | Layout | Cards | Goodput req/s | req/s per card | Model est. |
|---|---|---|--:|--:|--:|--:|
| azure-conv (2 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.335 | 0.168 | 0.182 |
| azure-conv (2 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.046 | 0.015 | 0.049 |
| azure-conv (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.335 | 0.168 | 0.182 |
| azure-conv (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.335 | 0.168 | 0.182 |
| azure-code (4 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.125 | 0.063 | 0.054 |
| azure-code (4 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| azure-code (4 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.125 | 0.063 | 0.054 |
| azure-code (4 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.125 | 0.063 | 0.054 |
| burstgpt (2 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.027 | 0.013 | 0.019 |
| burstgpt (2 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.004 | 0.001 | 0.005 |
| burstgpt (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.027 | 0.013 | 0.019 |
| burstgpt (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.027 | 0.013 | 0.019 |
| mooncake-conv (15 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.000 | 0.000 | 0.000 |
| mooncake-conv (15 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| mooncake-conv (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.000 | 0.000 |  |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.000 | 0.000 |  |
| mooncake-tool (15 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.038 | 0.019 | 0.046 |
| mooncake-tool (15 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| mooncake-tool (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.038 | 0.019 | 0.046 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.038 | 0.019 | 0.046 |

**2 nodes: 2 x (2 RNGD + 4 ATOM)**

| Trace (SLO TTFT/TPOT p90) | Policy | Layout | Cards | Goodput req/s | req/s per card | Model est. |
|---|---|---|--:|--:|--:|--:|
| azure-conv (2 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.335 | 0.168 | 0.182 |
| azure-conv (2 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.046 | 0.015 | 0.049 |
| azure-conv (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.335 | 0.168 | 0.182 |
| azure-conv (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.335 | 0.168 | 0.182 |
| azure-conv (2 s / 100 ms) | optimal, max goodput + planned tcp | P 3x RNGD / D 1x RNGD, tcp, 2 nodes | 4 | 0.705 | 0.176 | 0.707 |
| azure-code (4 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.125 | 0.063 | 0.054 |
| azure-code (4 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| azure-code (4 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.125 | 0.063 | 0.054 |
| azure-code (4 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.125 | 0.063 | 0.054 |
| azure-code (4 s / 100 ms) | optimal, max goodput + planned tcp | P 3x RNGD / D 1x RNGD, tcp, 2 nodes | 4 | 0.627 | 0.157 | 0.405 |
| burstgpt (2 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.027 | 0.013 | 0.019 |
| burstgpt (2 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.004 | 0.001 | 0.005 |
| burstgpt (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.027 | 0.013 | 0.019 |
| burstgpt (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.027 | 0.013 | 0.019 |
| burstgpt (2 s / 100 ms) | optimal, max goodput + planned tcp | P 2x RNGD / D 2x RNGD, tcp, 2 nodes | 4 | 0.061 | 0.015 | 0.049 |
| mooncake-conv (15 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.000 | 0.000 | 0.000 |
| mooncake-conv (15 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| mooncake-conv (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.000 | 0.000 |  |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.000 | 0.000 |  |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput + planned tcp | P 1x RNGD / D 1x RNGD, shm | 2 | 0.000 | 0.000 |  |
| mooncake-tool (15 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.038 | 0.019 | 0.046 |
| mooncake-tool (15 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 1x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| mooncake-tool (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.038 | 0.019 | 0.046 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.038 | 0.019 | 0.046 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput + planned tcp | P 3x RNGD / D 1x RNGD, tcp, 2 nodes | 4 | 0.380 | 0.095 | 0.359 |


**Honesty notes.** The simulator and `optimal` read the same profile table, so this comparison tests the placement logic
(queueing, bursts, KV fit, routing, link choice), not the hardware numbers. In that table RNGD's batch-1 TPOT, the `shm`
bandwidth and ATOM's batch-8 throughput and memory limit are measured or derived from measurements (docs/e2e.md,
docs/workload-traces.md); RNGD's batch-8 TPOT, ATOM prefill and batch-1 TPOT, the `p2p` bandwidth and the whole `tcp` link
are estimates. Lengths beyond the compiled S=512 graphs are extrapolated linearly. Under these numbers the outcome is:
optimal equals the RNGD/RNGD pool on one node and beats the hetero RNGD/ATOM×2 pool by about 10× per card (ATOM decode is
limited by its ~4 K tokens of KV room); across nodes it gains (2.1–10× goodput) only with a cross-node KV transport.
W6's "optimal beats topology per card" therefore holds against the hetero spec and ties the RNGD/RNGD spec; a GPU-only
baseline needs a GPU profile first.

## 다음 할 일
1. 프로파일 추정치를 측정으로 교체: FASOP NPU 비용 모델(aicomp #50), RNGD batch>1·ATOM prefill·p2p 대역폭 sweep. GPU 종류 추가.
2. `--rebalance`를 aicomp #45 지표(또는 게이트웨이 `airm_*`)로 실제 클러스터에서 실행, `--apply`로 annotation된 Deployment 구동.
3. 노드 간 KV 전송(`airm.kv_transports`) — 있어야 `optimal`이 두 노드를 함께 씁니다.
4. 클러스터 상주: 이미지와 chart(umbrella chart에 포함), in-cluster 클라이언트(`[k8s]`).
