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
- 검증: 테스트 51개, `rm_core.conformance airm.placements topology optimal` PASS(rm-core v0.1.2).

## Simulation: topology vs optimal (EN)

`python -m rm_controller.sim --compare --requests 4000` (seed 1). Requests are drawn from the trace atlas statistics in
[workload traces](../workload-traces.md) (length p50/p90/p99, mean rate, 60 s peak/mean as an on/off burst model) and run
through a discrete-event model of each placement: FCFS prefill per instance, KV handoff over the link, continuous-batching
decode limited by the TPOT-SLO batch and KV capacity. Goodput = highest mean rate at which ≥ 90 % of requests meet both TTFT
and TPOT. "Model est." is the `optimal` policy's analytical estimate for the same layout (0.68–0.93× the simulated value).
Card sets: one node with 2 RNGD + 4 ATOM, and two such nodes. `tcp` is a planned cross-node link (estimate, no transport
plugin yet), offered only in the row that says so. `optimal` rows use mixed roles (the default since the mixed-roles PR);
a row "…, one type per role" follows wherever `mixed_roles: false` (the policy before) chooses another layout, so those
pairs are the before/after.

**1 node: 2 RNGD + 4 ATOM**

| Trace (SLO TTFT/TPOT p90) | Policy | Layout | Cards | Goodput req/s | req/s per card | Model est. |
|---|---|---|--:|--:|--:|--:|
| azure-conv (2 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.653 |
| azure-conv (2 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| azure-conv (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.653 |
| azure-conv (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.653 |
| azure-code (4 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.874 |
| azure-code (4 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| azure-code (4 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.874 |
| azure-code (4 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.874 |
| burstgpt (2 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.017 |
| burstgpt (2 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| burstgpt (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.017 |
| burstgpt (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.017 |
| mooncake-conv (15 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.449 |
| mooncake-conv (15 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| mooncake-conv (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.449 |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.449 |
| mooncake-tool (15 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.812 |
| mooncake-tool (15 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| mooncake-tool (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.812 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.812 |

**2 nodes: 2 x (2 RNGD + 4 ATOM)**

| Trace (SLO TTFT/TPOT p90) | Policy | Layout | Cards | Goodput req/s | req/s per card | Model est. |
|---|---|---|--:|--:|--:|--:|
| azure-conv (2 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.653 |
| azure-conv (2 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| azure-conv (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.653 |
| azure-conv (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.653 |
| azure-conv (2 s / 100 ms) | optimal, max goodput + planned tcp | P 1x RNGD / D 3x RNGD, tcp, 2 nodes | 4 | 2.724 | 0.681 | 2.295 |
| azure-code (4 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.874 |
| azure-code (4 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| azure-code (4 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.874 |
| azure-code (4 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.874 |
| azure-code (4 s / 100 ms) | optimal, max goodput + planned tcp | P 3x RNGD / D 1x RNGD, tcp, 2 nodes | 4 | 2.270 | 0.567 | 1.853 |
| burstgpt (2 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.017 |
| burstgpt (2 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| burstgpt (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.017 |
| burstgpt (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.017 |
| burstgpt (2 s / 100 ms) | optimal, max goodput + planned tcp | P 1x RNGD / D 3x RNGD, tcp, 2 nodes | 4 | 0.087 | 0.022 | 0.065 |
| mooncake-conv (15 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.449 |
| mooncake-conv (15 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| mooncake-conv (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.449 |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.449 |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput + planned tcp | P 2x RNGD / D 2x RNGD, tcp, 2 nodes | 4 | 1.132 | 0.283 | 0.972 |
| mooncake-tool (15 s / 100 ms) | topology, RNGD/RNGD shm (examples/spec.yaml) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.812 |
| mooncake-tool (15 s / 100 ms) | topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml) | P 1x RNGD / D 2x ATOM, p2p | 3 | 0.000 | 0.000 | 0.000 |
| mooncake-tool (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.812 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.812 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput + planned tcp | P 2x RNGD / D 2x RNGD, tcp, 2 nodes | 4 | 1.948 | 0.487 | 1.734 |

**Honesty notes.** The simulator and `optimal` read the same profile table, so this comparison tests the placement logic
(queueing, bursts, KV fit, routing, link choice), not the hardware numbers. Since the live baselines
([baselines](../baselines.md)) the table is measured for RNGD (prefill, decode at batch 1–8 on the continuous B=8 graph),
ATOM decode (batch 1–4 on one card) and `shm`; ATOM prefill, the `p2p` bandwidth and the whole `tcp` link are estimates.
Lengths beyond the compiled S=512 graphs are extrapolated linearly, so the Mooncake rows describe graphs that do not exist
yet. Under these numbers: optimal equals the RNGD/RNGD pool on one node; ATOM decode (108 ms per token) misses the 100 ms
TPOT SLO, so the hetero pool has no goodput, as on the cluster; across nodes optimal gains 2.0–3.5× only with a cross-node
KV transport. W6's "optimal beats topology per card" holds against the hetero spec and ties the RNGD/RNGD spec; the
GPU-only comparison is in the next section.

Burst windows (2026-10-19, W6 baselines PR): the first simulator drew peak windows at random, so a fast layout whose 4,000
requests spanned one or two 60 s windows often saw no peak at all (an A100 pool scored 45 req/s on BurstGPT against a model
estimate of 0.3). Peak windows are now deterministic (one in round(2 × peak), starting with the first); the tables above
were re-run and moved by at most 0.025 req/s (no layout changed).

## 3차 (2026-10-19, 로드맵 W6, GPU 기준선)
- 프로파일에 `nvidia.A100` 추가(80 GB, vLLM v0.11): batch 64 TPOT 20 ms와 최대 batch 64는 hetero-llm-d 혼합 풀 실험(A100 단독 128요청,
  동시성 64)에서 유도·측정, prefill 10K tok/s와 batch 1 TPOT 11 ms는 데이터시트 기반 추정. GPU 간 링크 `cuda-ipc`(20 GB/s 추정,
  `implemented: false` — vLLM NixlConnector에는 있으나 ai-rm 플러그인은 없음).
- `rm_controller/baselines.py`: 발표된 배치 알고리즘을 단순화한 기준선 둘. **distserve**(DistServe 방식: 동종, 단계별 크기 결정,
  카드당 goodput 최대)와 **hexgen2**(HexGen-2 방식: 인스턴스 그래프 max-flow + 역할 반복 개선, 역할 안에 종류 혼합 허용). Helix는
  레이어 단위 배치라 모델링하지 않음. `python -m rm_controller.baselines --compare`. 아래 표(영문).
- 시뮬레이터 burst 창을 결정적으로 바꿈(위 EN 설명). 테스트 60개.

## GPU-only, NPU-only and mixed baselines (EN)

`python -m rm_controller.baselines --compare --requests 4000` (seed 1). Same simulator and SLOs as above. Policies:
`topology` with no type filter (prefill = highest peak, decode = most memory) over the hardware's own KV path (`cuda-ipc`
between GPUs, the measured `shm` otherwise); `optimal` (both objectives); `distserve` and `hexgen2` from
`rm_controller/baselines.py`. For this comparison every policy may use `cuda-ipc`. "Own est." is each policy's own model:
`optimal`'s estimate (for topology: `optimal`'s model applied to topology's layout), DistServe's M/D/1 + batch model, and
HexGen-2's max-flow divided by the 60 s peak ratio. As above, "…, one type per role" rows are `optimal` before mixed roles,
shown where the layout differs.

**GPU only: 1 node, 4 A100**

| Trace (SLO TTFT/TPOT p90) | Policy | Layout | Cards | Goodput req/s | req/s per card | Own est. |
|---|---|---|--:|--:|--:|--:|
| azure-conv (2 s / 100 ms) | topology (cuda-ipc) | P 1x A100 / D 1x A100, cuda-ipc | 2 | 4.218 | 2.109 | 3.910 |
| azure-conv (2 s / 100 ms) | optimal, per card | P 2x A100 / D 1x A100, cuda-ipc | 3 | 8.644 | 2.881 | 8.459 |
| azure-conv (2 s / 100 ms) | optimal, max goodput | P 3x A100 / D 1x A100, cuda-ipc | 4 | 12.113 | 3.028 | 11.184 |
| azure-conv (2 s / 100 ms) | distserve | P 2x A100 / D 1x A100, cuda-ipc | 3 | 8.644 | 2.881 | 8.744 |
| azure-conv (2 s / 100 ms) | hexgen2 | P 3x A100 / D 1x A100, cuda-ipc | 4 | 12.113 | 3.028 | 10.744 |
| azure-code (4 s / 100 ms) | topology (cuda-ipc) | P 1x A100 / D 1x A100, cuda-ipc | 2 | 1.040 | 0.520 | 0.913 |
| azure-code (4 s / 100 ms) | optimal, per card | P 3x A100 / D 1x A100, cuda-ipc | 4 | 3.160 | 0.790 | 3.000 |
| azure-code (4 s / 100 ms) | optimal, max goodput | P 3x A100 / D 1x A100, cuda-ipc | 4 | 3.160 | 0.790 | 3.000 |
| azure-code (4 s / 100 ms) | distserve | P 3x A100 / D 1x A100, cuda-ipc | 4 | 3.160 | 0.790 | 3.033 |
| azure-code (4 s / 100 ms) | hexgen2 | P 3x A100 / D 1x A100, cuda-ipc | 4 | 3.160 | 0.790 | 3.136 |
| burstgpt (2 s / 100 ms) | topology (cuda-ipc) | P 1x A100 / D 1x A100, cuda-ipc | 2 | 0.163 | 0.082 | 0.155 |
| burstgpt (2 s / 100 ms) | optimal, per card | P 2x A100 / D 1x A100, cuda-ipc | 3 | 0.341 | 0.114 | 0.303 |
| burstgpt (2 s / 100 ms) | optimal, max goodput | P 2x A100 / D 2x A100, cuda-ipc | 4 | 0.348 | 0.087 | 0.326 |
| burstgpt (2 s / 100 ms) | distserve | P 2x A100 / D 1x A100, cuda-ipc | 3 | 0.341 | 0.114 | 0.305 |
| burstgpt (2 s / 100 ms) | hexgen2 | P 2x A100 / D 2x A100, cuda-ipc | 4 | 0.348 | 0.087 | 0.344 |
| mooncake-conv (15 s / 100 ms) | topology (cuda-ipc) | P 1x A100 / D 1x A100, cuda-ipc | 2 | 0.536 | 0.268 | 0.452 |
| mooncake-conv (15 s / 100 ms) | optimal, per card | P 3x A100 / D 1x A100, cuda-ipc | 4 | 1.953 | 0.488 | 1.707 |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput | P 3x A100 / D 1x A100, cuda-ipc | 4 | 1.953 | 0.488 | 1.707 |
| mooncake-conv (15 s / 100 ms) | distserve | P 3x A100 / D 1x A100, cuda-ipc | 4 | 1.953 | 0.488 | 1.804 |
| mooncake-conv (15 s / 100 ms) | hexgen2 | P 3x A100 / D 1x A100, cuda-ipc | 4 | 1.953 | 0.488 | 1.902 |
| mooncake-tool (15 s / 100 ms) | topology (cuda-ipc) | P 1x A100 / D 1x A100, cuda-ipc | 2 | 0.814 | 0.407 | 0.703 |
| mooncake-tool (15 s / 100 ms) | optimal, per card | P 3x A100 / D 1x A100, cuda-ipc | 4 | 2.904 | 0.726 | 2.427 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput | P 3x A100 / D 1x A100, cuda-ipc | 4 | 2.904 | 0.726 | 2.427 |
| mooncake-tool (15 s / 100 ms) | distserve | P 3x A100 / D 1x A100, cuda-ipc | 4 | 2.904 | 0.726 | 2.505 |
| mooncake-tool (15 s / 100 ms) | hexgen2 | P 3x A100 / D 1x A100, cuda-ipc | 4 | 2.904 | 0.726 | 2.597 |

**NPU only: 1 node, 2 RNGD + 4 ATOM**

| Trace (SLO TTFT/TPOT p90) | Policy | Layout | Cards | Goodput req/s | req/s per card | Own est. |
|---|---|---|--:|--:|--:|--:|
| azure-conv (2 s / 100 ms) | topology (shm) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.653 |
| azure-conv (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.653 |
| azure-conv (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.653 |
| azure-conv (2 s / 100 ms) | distserve | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.886 |
| azure-conv (2 s / 100 ms) | hexgen2 | P 1x RNGD / D 1x RNGD, shm | 2 | 0.813 | 0.406 | 0.886 |
| azure-code (4 s / 100 ms) | topology (shm) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.874 |
| azure-code (4 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.874 |
| azure-code (4 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.874 |
| azure-code (4 s / 100 ms) | distserve | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 0.962 |
| azure-code (4 s / 100 ms) | hexgen2 | P 1x RNGD / D 1x RNGD, shm | 2 | 0.943 | 0.472 | 1.000 |
| burstgpt (2 s / 100 ms) | topology (shm) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.017 |
| burstgpt (2 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.017 |
| burstgpt (2 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.017 |
| burstgpt (2 s / 100 ms) | distserve | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.025 |
| burstgpt (2 s / 100 ms) | hexgen2 | P 1x RNGD / D 1x RNGD, shm | 2 | 0.025 | 0.013 | 0.025 |
| mooncake-conv (15 s / 100 ms) | topology (shm) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.449 |
| mooncake-conv (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.449 |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.449 |
| mooncake-conv (15 s / 100 ms) | distserve | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.572 |
| mooncake-conv (15 s / 100 ms) | hexgen2 | P 1x RNGD / D 1x RNGD, shm | 2 | 0.563 | 0.281 | 0.572 |
| mooncake-tool (15 s / 100 ms) | topology (shm) | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.812 |
| mooncake-tool (15 s / 100 ms) | optimal, per card | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.812 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.812 |
| mooncake-tool (15 s / 100 ms) | distserve | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.945 |
| mooncake-tool (15 s / 100 ms) | hexgen2 | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.979 |

**Mixed: 1 node, 2 A100 + 2 RNGD + 4 ATOM**

| Trace (SLO TTFT/TPOT p90) | Policy | Layout | Cards | Goodput req/s | req/s per card | Own est. |
|---|---|---|--:|--:|--:|--:|
| azure-conv (2 s / 100 ms) | topology (shm) | P 1x A100 / D 1x A100, shm | 2 | 4.202 | 2.101 | 3.826 |
| azure-conv (2 s / 100 ms) | optimal, per card | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 11.780 | 2.945 | 10.549 |
| azure-conv (2 s / 100 ms) | optimal, per card, one type per role | P 2x RNGD / D 1x A100, shm | 3 | 7.525 | 2.508 | 7.165 |
| azure-conv (2 s / 100 ms) | optimal, max goodput | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 11.780 | 2.945 | 10.549 |
| azure-conv (2 s / 100 ms) | optimal, max goodput, one type per role | P 2x RNGD / D 1x A100, shm | 3 | 7.525 | 2.508 | 7.165 |
| azure-conv (2 s / 100 ms) | distserve | P 1x A100 / D 1x A100, cuda-ipc | 2 | 4.218 | 2.109 | 4.372 |
| azure-conv (2 s / 100 ms) | hexgen2 | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 11.935 | 2.984 | 10.744 |
| azure-code (4 s / 100 ms) | topology (shm) | P 1x A100 / D 1x A100, shm | 2 | 1.038 | 0.519 | 0.897 |
| azure-code (4 s / 100 ms) | optimal, per card | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 3.019 | 0.755 | 2.770 |
| azure-code (4 s / 100 ms) | optimal, per card, one type per role | P 2x RNGD / D 1x A100, shm | 3 | 2.087 | 0.696 | 1.873 |
| azure-code (4 s / 100 ms) | optimal, max goodput | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 3.019 | 0.755 | 2.770 |
| azure-code (4 s / 100 ms) | optimal, max goodput, one type per role | P 2x A100 / D 2x RNGD, shm | 4 | 2.160 | 0.540 | 1.939 |
| azure-code (4 s / 100 ms) | distserve | P 1x A100 / D 1x A100, cuda-ipc | 2 | 1.040 | 0.520 | 1.011 |
| azure-code (4 s / 100 ms) | hexgen2 | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 3.070 | 0.767 | 3.046 |
| burstgpt (2 s / 100 ms) | topology (shm) | P 1x A100 / D 1x A100, shm | 2 | 0.163 | 0.081 | 0.153 |
| burstgpt (2 s / 100 ms) | optimal, per card | P 1x RNGD+1x A100 / D 1x A100, shm | 3 | 0.289 | 0.097 | 0.261 |
| burstgpt (2 s / 100 ms) | optimal, per card, one type per role | P 1x A100 / D 1x A100, cuda-ipc | 2 | 0.163 | 0.082 | 0.155 |
| burstgpt (2 s / 100 ms) | optimal, max goodput | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 0.362 | 0.091 | 0.305 |
| burstgpt (2 s / 100 ms) | optimal, max goodput, one type per role | P 2x RNGD / D 1x A100, shm | 3 | 0.243 | 0.081 | 0.229 |
| burstgpt (2 s / 100 ms) | distserve | P 1x A100 / D 1x A100, cuda-ipc | 2 | 0.163 | 0.082 | 0.168 |
| burstgpt (2 s / 100 ms) | hexgen2 | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 0.363 | 0.091 | 0.305 |
| mooncake-conv (15 s / 100 ms) | topology (shm) | P 1x A100 / D 1x A100, shm | 2 | 0.505 | 0.253 | 0.422 |
| mooncake-conv (15 s / 100 ms) | optimal, per card | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 1.930 | 0.482 | 1.668 |
| mooncake-conv (15 s / 100 ms) | optimal, per card, one type per role | P 2x RNGD / D 1x A100, shm | 3 | 1.488 | 0.496 | 1.246 |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 1.930 | 0.482 | 1.668 |
| mooncake-conv (15 s / 100 ms) | optimal, max goodput, one type per role | P 2x RNGD / D 1x A100, shm | 3 | 1.488 | 0.496 | 1.246 |
| mooncake-conv (15 s / 100 ms) | distserve | P 1x A100 / D 1x A100, cuda-ipc | 2 | 0.536 | 0.268 | 0.601 |
| mooncake-conv (15 s / 100 ms) | hexgen2 | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 2.196 | 0.549 | 2.090 |
| mooncake-tool (15 s / 100 ms) | topology (shm) | P 1x A100 / D 1x A100, shm | 2 | 0.802 | 0.401 | 0.687 |
| mooncake-tool (15 s / 100 ms) | optimal, per card | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 2.921 | 0.730 | 2.474 |
| mooncake-tool (15 s / 100 ms) | optimal, per card, one type per role | P 2x RNGD / D 1x A100, shm | 3 | 2.102 | 0.701 | 1.786 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 2.921 | 0.730 | 2.474 |
| mooncake-tool (15 s / 100 ms) | optimal, max goodput, one type per role | P 2x RNGD / D 1x A100, shm | 3 | 2.102 | 0.701 | 1.786 |
| mooncake-tool (15 s / 100 ms) | distserve | P 1x RNGD / D 1x RNGD, shm | 2 | 0.950 | 0.475 | 0.945 |
| mooncake-tool (15 s / 100 ms) | hexgen2 | P 2x RNGD+1x A100 / D 1x A100, shm | 4 | 3.151 | 0.788 | 2.823 |

**Honesty notes.** A100 prefill rate and batch-1 TPOT are estimates from the datasheet (312 TFLOPS bf16, ~2 TB/s); the
batch-64 TPOT (20 ms) is an upper bound derived from end-to-end latency in the hetero-llm-d run, which includes prefill and
queueing; `kv_tokens` is arithmetic on `--gpu-memory-utilization 0.90`; `cuda-ipc` bandwidth is an estimate and ai-rm has
no transport plugin for it. The baselines are simplified: no tensor/pipeline-parallel search (a profile has one `group`),
closed-form queues instead of DistServe's simulator, one KV link per layout and least-loaded routing instead of HexGen-2's
per-edge links and flow-proportional routing. Outcome under the calibrated numbers (RNGD, ATOM decode and `shm` measured on the live node): on 4 A100 nothing
changed (`optimal` per card equals `distserve` and beats topology by 1.4–1.8× per card); on the NPU node every policy,
`hexgen2` included, picks RNGD/RNGD (measured ATOM decode cannot meet the TPOT SLO); on the mixed node the measured RNGD
prefill makes 2 RNGD + 1 A100 prefill with A100 decode the choice of `optimal` (per card and max goodput) and of `hexgen2`
(11.78 and 11.94 req/s on Azure conversation, 2.8× `distserve`). The mixed rows assume RNGD → A100 KV over `shm`, which
no ai-rm transport provides. Before calibration (rm-controller #24/#25 tables) `hexgen2` added ATOM decode and `optimal`
reached 87–89 % of it on half the cards.

**Mixed roles: before/after (EN).** `optimal` may now give a role instances of several device types (`mixed_roles`,
default true). Model: prefill groups per type, each an M/G/c, with arrivals split by routing weight; a group's weight is
the rate it takes with its own TTFT p90 (prefill(p90) + KV + TPOT + decode-slot wait + its queue wait) within the SLO, so
every group meets the SLO on its own; decode groups split by capacity. Every prefill→decode type pair must be served by
the plan's KV link (so `cuda-ipc` and `p2p` plans stay single-type; `shm` and `tcp` serve any pair); host-scope links keep
the whole plan on one node. Search: per link and node scope, every pair of type-count vectors within the cards and the
budget, visited in order of an upper bound (min(prefill, decode capacity) / peak) and cut when the bound cannot beat the
best plan; it equals brute force on the mixed node (test) and runs in < 0.05 s per pool there. The simulator routes
`optimal`'s layouts by the plan's weights (smooth weighted round-robin per type group, FCFS inside a group).

| Card set, trace | objective | one type per role | mixed roles | `hexgen2` |
|---|---|--:|--:|--:|
| Mixed node, azure-conv | max goodput | 7.525 (3 cards) | **11.780** (4 cards) | 11.935 (4 cards) |
| Mixed node, burstgpt | max goodput | 0.243 (3) | **0.362** (4) | 0.363 (4) |
| Mixed node, azure-code | max goodput | 2.160 (4) | **3.019** (4) | 3.070 (4) |
| Mixed node, azure-conv | per card | 2.508 per card (3) | **2.945** per card (4) | — |
| 2 nodes, planned tcp, any trace | max goodput | same layout | same layout | — |

Calibrated profiles (live baselines, [baselines](../baselines.md)); the numbers in the bullets below and in 4차 are from
before the calibration, when RNGD prefill was taken as 2.5 K tok/s and ATOM decode as batch 8 at 52 ms.

- **Per card now moves on the mixed node**: with the measured RNGD prefill, 2 RNGD + 1 A100 prefill feeding one A100 decode
  beats every single-type split per card (2.95 vs 2.51 req/s per card on Azure conversation); on every other card set the
  per-card layouts are unchanged. `mixed_roles` stays on by default.
- **The gap to `hexgen2` is small**: ≤ 1.3 % on Azure conversation and BurstGPT, 1.7 % on Azure code, 8–14 % on the
  Mooncake traces, on the same 4 cards; what is left is the shared prefill queue against `optimal`'s fixed weighted split.
- **No ATOM decode anywhere**: neither `optimal` nor `hexgen2` adds it once its measured TPOT (108 ms) is in the table.

## 4차 (2026-10-19, 로드맵 W6 후속, 역할 내 종류 혼합)
- `optimal`에 `mixed_roles`(기본 true): 한 역할(prefill/decode)에 여러 장치 종류의 인스턴스를 둘 수 있음. prefill은 종류별
  M/G/c 그룹으로 나누고, 각 그룹의 라우팅 가중치는 그 그룹이 자신의 TTFT p90을 SLO 안에 지키며 받을 수 있는 요청률에 비례.
  decode는 용량 비례. 모든 prefill→decode 종류 쌍이 계획의 KV 링크로 이어져야 함(host 범위 링크는 한 노드).
- 탐색: 링크·노드 범위별로 종류별 인스턴스 수 벡터 쌍을 상한(min(prefill, decode 용량)/peak) 순으로 보고, 상한이 최선을 못 넘으면
  중단. 조합이 `MAX_MIXED_PAIRS`(20만)를 넘으면 그 범위는 종류 하나씩만 보고 reason에 기록. 혼합 노드에서 brute force와 같은 답.
- 단일 종류 계획은 기존 추정 함수를 그대로 호출 → 기존 테스트·예제 출력 동일. 카드당 목표의 비교표 결과는 하나도 바뀌지 않아
  기본값을 true로 둠. 시뮬레이터는 계획의 가중치로 라우팅(종류 그룹별 smooth weighted round-robin).
- 예제의 랩 풀 결정은 이전과 바이트까지 같음. 도착률이 주어졌는데 어떤 계획도 감당 못 하면(예: 혼합 노드의 `examples/optimal.yaml`,
  Azure 대화 5.5 req/s) 목표가 "최대 goodput"이라 이제 혼합 계획을 고름(추정 3.60 → 4.46 req/s).
- 결과(위 EN 표): 혼합 노드 max goodput Azure conversation 4.22 → 5.41, BurstGPT 0.163 → 0.230 req/s(`hexgen2`의 87 %·89 %, 카드 절반).
  남은 차이는 라우팅: 같은 4카드 배치를 공유 큐로 돌리면 6.34·0.257로 `hexgen2` 이상. 2노드 planned tcp BurstGPT는 0.061 → 0.059로 소폭 하락.
- `--apply`: 혼합 역할은 종류별 Deployment에 `airm.ai-computing.io/accelerator: <vendor>.<model>` annotation을 달면 그 종류의
  카드만 따르고, 결정에 그 종류가 없으면 replicas 0. 재배치(`_reuse`)는 잃은 카드와 같은 종류로 교체. 테스트 73개.
- 남은 일: 공유 큐(작업 보존) 라우팅 모델, 링크를 쌍마다 고르기(지금은 계획당 하나), `--rebalance`는 혼합 역할을 첫 종류로 근사.

## 5차 (2026-10-19, 로드맵 W5·W6·W7, 실측 보정)
- **실제 클러스터**([기준선](../baselines.md)): `optimal`이 RNGD+ATOM 노드에 `airm-placement` generation 2(prefill RNGD 2, decode RNGD 1,
  `shm`)를 쓰고 `--apply`가 rngd-pd Deployment를 맞춤. 파드는 결정한 노드·카드 수로 떴고(카드 선택은 device plugin), `pd-smoke`가
  llm-d 게이트웨이를 거쳐 PASS. 보정 후 `optimal`은 prefill 1 / decode 2(generation 3)를 골랐고 두 트레이스 모두 SLO 100 % 달성.
- **프로파일 보정**: RNGD prefill 66 ms + 12K tok/s, RNGD decode 30 ms/토큰(B=8 continuous), ATOM decode 108 ms/토큰(카드 1장, B≤4),
  `shm` 1.6 GB/s를 측정값으로. 위 표 전부 다시 계산. NPU 노드에서는 모든 정책이 RNGD/RNGD, 혼합 노드에서는 `optimal`과 `hexgen2`
  모두 RNGD 2 + A100 1 prefill / A100 decode, 혼합 노드에서는 역할 내 혼합이 카드당 선택도 바꿈.
- 테스트 조정(보정 때문에 바뀐 기대값만): ATOM 인스턴스는 카드 1장(`test_instances_follow_groups`), RNGD prefill이 빨라져 Mooncake
  대화가 15초 SLO 안에 들어오므로 불가능 사례는 1초 SLO로(`test_hexgen2_drops…`), 혼합 가중치는 인스턴스당 비교(`test_mixed_estimate…`),
  카드당 선택은 혼합 노드에서 달라질 수 있되 나빠지지 않음(`test_per_card_objective_with_mixed_roles_is_never_worse`), RNGD→ATOM p2p
  계획은 TPOT 200 ms·S=512 크기 요청으로(`test_every_prefill_decode_type_pair_needs_the_link`), ATOM TP-2 그룹 동작은 명시한 TP-2
  프로파일로(`test_optimal`, `test_sim`, `test_apply`).

## 다음 할 일
1. 남은 추정치 교체: ATOM prefill·p2p 대역폭 측정, FASOP NPU 비용 모델(aicomp #50), A100 prefill·batch 1 TPOT 측정(현재 추정).
   시뮬레이터에 decode 진입 시 KV 적재 지연과 단일 카드(solo) 서빙 추가([기준선](../baselines.md#calibration-w6)).
2. `--rebalance`를 aicomp #45 지표(또는 게이트웨이 `airm_*`)로 실제 클러스터에서 실행.
3. 노드 간 KV 전송(`airm.kv_transports`) — 있어야 `optimal`이 두 노드를 함께 씁니다.
4. 클러스터 상주: 이미지와 chart(umbrella chart에 포함), in-cluster 클라이언트(`[k8s]`).
