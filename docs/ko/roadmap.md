# 로드맵: 격차 메우기

[English](../roadmap.md)

최신 시스템(llm-d, NVIDIA Dynamo, vLLM + NIXL/LMCache, Mooncake, DistServe/Splitwise, HexGen-2/Helix/ThunderServe)과
비교한 결과, ai-rm만 제공하는 것이 하나 있었습니다. **서로 다른 벤더**의 NPU에 걸친 prefill/decode 분리 서빙과,
KV의 레이아웃·정밀도·소유권을 명시한 계약입니다. 동시에 일곱 가지 격차도 확인했습니다. 이 페이지는 각 격차의 계획을 정리합니다.

엔진 작업은 Optimus Prime([aicomp](https://github.com/ai-computing/aicomp)) 담당이며 그곳에 기능 요청으로 올려 두었습니다.
나머지는 ai-rm 저장소들에서 진행합니다.

| | 격차 | 최신 동향 | ai-rm 쪽 | 엔진 쪽 (aicomp) |
|:-:|---|---|---|---|
| W1 | **서빙 기능**: 스트리밍 없음, completions만, greedy·고정 길이 | vLLM/SGLang: OpenAI 호환 스트리밍, sampling, 취소 | rm-bench `--api chat`, GuideLLM·MLPerf 결과 가져오기 | [#41](https://github.com/ai-computing/aicomp/issues/41) 스트리밍+chat · [#42](https://github.com/ai-computing/aicomp/issues/42) sampling · [#43](https://github.com/ai-computing/aicomp/issues/43) 연결 종료 시 취소 |
| W2 | **규모와 성숙도**: 노드 1대, B≤8, S=512, 모델 1개, 사이트 값으로 카드 고정 | 운영 스택은 다중 노드, 연속 배치, 긴 문맥 | 노드 데몬 이미지, 통합 차트, CI의 kind 기반 시뮬레이션 클러스터, 다중 노드·다중 풀 배치, 파드가 할당받은 카드 사용 | [#44](https://github.com/ai-computing/aicomp/issues/44) 다중 lane 배치 decode · [#51](https://github.com/ai-computing/aicomp/issues/51) S=2048 이상 |
| W3 | **KV 전송 표준**: 독자 전송, NIXL·vLLM에서 접근 불가 | NIXL이 공통 KV 전송 계층 (Dynamo, llm-d, vLLM) | hetero-npu-p2p에 RNGD↔ATOM NIXL 백엔드 플러그인, rngd-pd에 vLLM KV connector, 0.1–4 GB 전송 곡선 | [#47](https://github.com/ai-computing/aicomp/issues/47) layer 단위 전송 · [#48](https://github.com/ai-computing/aicomp/issues/48) NIXL 전송 연결점 |
| W4 | **캐시 재사용**: 요청마다 처음부터 prefill | llm-d·Dynamo는 KV 캐시 적중 기준 라우팅, LMCache·Mooncake Store는 KV 계층화 | EPP prefix-cache scorer 설정, [LMCache·Mooncake Store 평가](kv-tier-evaluation.md), 호스트 DRAM KV 계층 (rm-core `MemoryTier`) | [#46](https://github.com/ai-computing/aicomp/issues/46) KV 블록 이벤트와 prefix 재사용 · [#52](https://github.com/ai-computing/aicomp/issues/52) 호스트 DRAM KV 계층 |
| W5 | **제어 루프**: 고정 배포, 배치 결정은 기록만, 장애 대응 없음 | Dynamo Planner가 SLO 기준 P:D 재조정, KEDA/HPA가 대기열 지표로 스케일 | rm-controller가 배치 적용, P:D 재조정기, 노드·카드 장애 시 재배치, KEDA 오토스케일 | [#45](https://github.com/ai-computing/aicomp/issues/45) `/metrics` · [#49](https://github.com/ai-computing/aicomp/issues/49) quarantine 복구 |
| W6 | **형식적 스케줄링**: 규칙 기반 배치 | HexGen-2(그래프 분할 + max-flow), Helix(MILP), ThunderServe — 모두 GPU 전용 | 카드 종류와 KV 링크 비용을 고려하는 `optimal` 배치 정책, 배치 형식을 rm-core 프로토콜에 규범화 | [#50](https://github.com/ai-computing/aicomp/issues/50) FASOP 추론 비용 모델과 NPU 프로파일 |
| W7 | **근거**: 기준선 비교 없음 | 논문들은 DistServe/vLLM 대비 카드당 goodput과 SLO 달성률을 보고 | 같은 카드 예산의 기준선(동종 PD, 벤더 PD, 복제), 모든 실행에 tok/J, 논문 초안 2편 | — |

## 완료 기준

| | 기준 |
|:-:|---|
| W1 | `rm-bench run pd-smoke --api chat` 통과, GuideLLM이 PD 경로의 TTFT를 측정 |
| W2 | B≥8 decode와 S≥2048로 Azure 대화 트레이스의 85 % 이상 수용, 풀이 노드 2대에 걸침, `helm install`로 스택 재현, PR마다 시뮬레이션 e2e |
| W3 | NIXL 클라이언트로 RNGD→ATOM 전송, 토큰 일치, 4 GB까지 전송 시간 곡선 |
| W4 | Mooncake tool-agent 재생에서 prefix 적중률 > 0, 캐시 없음 대비 TTFT 감소 |
| W5 | 파드가 `airm-placement` 결정대로 배치, P:D 비율이 트레이스 구성을 따라감, decode 파드 강제 종료 시 오류율 상한 내 복구 |
| W6 | 같은 예산에서 `optimal`이 `topology`보다 카드당 goodput 높음, GPU 전용 기준선과 비교 |
| W7 | 트레이스별로 세 기준선 대비 결과표와 tok/J |

## 진행 상황 (2026-10-19)

| | ai-rm 쪽 완료 | 대기 중 |
|:-:|---|---|
| W1 | rm-bench 스트리밍 클라이언트(SSE로 TTFT/TPOT/ITL), GuideLLM·MLPerf 가져오기, `compare` | 엔진 #41–#43 |
| W2 | 노드 데몬 이미지 `ghcr.io/ai-computing/rm-accel`, 통합 차트 `charts/ai-rm`, PR마다 kind 시뮬레이션 e2e, rngd-pd가 할당받은 카드 사용, 다중 모델 풀을 실제로 배치·이동(PD + aggregated `serve`, [기준선](baselines.md#w2-한-노드의-두-모델-풀-hub-35)), 노드 간 KV `tcp`(rngd-pd #9)가 CPU relay 노드를 거쳐 바이트·토큰 단위로 일치, 1 GbE에서 0.08 GB/s 측정([기준선](baselines.md#w2-tcp를-통한-노드-간-kv-hub-34)), 두 NPU 노드에 걸친 NPU 간 PD(한 노드의 RNGD prefill, 다른 노드의 RNGD decode, `tcp` 서버는 decode 옆): 바이트·토큰 단위 일치, admission 때 KV load가 relay 경유 816 ms 대신 242 ms, Azure 대화 ×0.5에서 SLO 달성률 96.7 %([기준선](baselines.md#두-번째-npu-노드-2026-10-20)) | 엔진 #44, #51, 2노드 풀이 이득을 내려면 2.5 GbE 이상 링크, 런타임이 설치된 노드 간 실행용 노드(이번에는 실행용으로 복사), `rm-controller`에서 풀의 역할을 지정한 노드에 배치 |
| W3 | `HETERO_NPU` NIXL 백엔드(hetero-npu-p2p #3): RNGD→ATOM DMA-BUF 0.1–4 GiB에서 약 41.5 GB/s 일정, 바이트 검증, 32 layer 분할 추가 비용 없음 | 엔진 #47, #48 (ATOM decode graph가 장치 상주 캐시를 받기 전까지 서빙은 `shm` 유지), rngd-pd `nixl` KV 전송 완료 (rngd-pd #8: RNGD→ATOM 요청당 1.6 ms, 토큰 일치) |
| W4 | A100 2장 실측(hetero-llm-d #5): `approx-prefix-gpu`로 공유 prefix TTFT p50 0.225 → 0.127 s, 수정한 이벤트 계약으로 precise prefix 동작, [KV 계층 평가](kv-tier-evaluation.md) | 엔진 #46, #52 |
| W5 | rm-controller가 실제 PD 파드를 배치·이동(`--apply`), A100 KEDA 1→2 21초, 콜드 스타트 110–121초, rngd-pd decode가 적체를 견딤(rngd-pd #6: 1,153요청 0 실패) | 엔진 #45, #49, 예측형 `--rebalance` 실환경 완료 ([기준선](baselines.md) W5: 대화가 많으면 decode로 이동, 코드에서는 유지해 77–81 %, 이전 45 %) |
| W6 | 역할 내 타입 혼합 `optimal`, 실측 보정 프로파일, 시뮬레이터의 DistServe·HexGen-2식 기준선, 배치 문서 규범화 (rm-core v0.1.2, §5.4) | 엔진 #50 |
| W7 | [같은 예산 기준선](baselines.md): 2장에서는 복제가 카드당 goodput 최고, PD가 tok/J 최고(1.17), 3장에서는 보정된 `optimal` 1P+2D가 SLO 100 %, RNGD→ATOM은 ATOM decode graph(토큰당 108 ms)가 한계 | furiosa-llm 벤더 기준선 완료 (카드당 goodput·tok/J는 `solo`와 같고 지연은 더 낮음, furiosa-llm은 PD 미지원). 대화 ×1을 배치마다 3–5번 반복([반복 실행](baselines.md#반복-실행-2026-10-2021-43): 순서는 유지, PD 1P+1D tok/J는 모든 실행 1.06이지만 달성률은 25.5–98.0 %). 같은 예산의 A100 행은 아직(A100 사용 중) |

## 하드웨어 대기

| 항목 | 막힌 이유 | 소프트웨어 쪽 준비 | 풀리는 조건 |
|---|---|---|---|
| RDMA를 통한 노드 간 KV ([#46](https://github.com/ai-computing/ai-rm/issues/46)) | NPU 노드에 RDMA 장치가 없다. NIC는 RDMA가 없는 Intel X550/X710 10GBASE-T이고, 10G 포트에 링크가 없어 모든 트래픽이 1 GbE 포트 하나로 간다. 방향마다 0.117 GB/s, 67 MB 요청 하나에 약 0.8초. | rngd-pd `nixl-ucx` 전송([rngd-pd#13](https://github.com/ai-computing/rngd-pd/pull/13)): 등록한 host 버퍼 사이를 UCX 위 NIXL READ로 옮긴다. RDMA는 `UCX_TLS`만 바꾸면 된다. UCX-TCP로 노드 간 실행: 바이트 일치, `tcp`처럼 링크가 한계(요청 하나 0.085 GB/s). | (a) 두 NPU 노드에 RoCE v2 / InfiniBand NIC와 스위치 설정(25 GbE 약 2.9 GB/s). (b) 기존 10G 포트 연결: 약 1.1 GB/s, RDMA 없음, 시뮬레이터의 손익분기 0.15–0.25 GB/s를 넘기는 가장 싼 단계. (c) 관리자가 soft-RoCE `rdma link add` 실행, verbs 경로 기능 확인용. |

진행 상황은 허브의 Plane 프로젝트(모듈 W1–W7)에서 관리하고 [현재 상태](status.md)에 요약합니다.
