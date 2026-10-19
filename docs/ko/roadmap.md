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
| W2 | 노드 데몬 이미지 `ghcr.io/ai-computing/rm-accel`, 통합 차트 `charts/ai-rm`, PR마다 kind 시뮬레이션 e2e, rngd-pd가 할당받은 카드 사용 | 엔진 #44, #51, 노드 간 KV 경로 |
| W3 | 진행 중: hetero-npu-p2p의 NIXL 백엔드와 전송 시간 곡선 | 엔진 #47, #48 |
| W4 | EPP 프로파일 `queue-kv`, `approx-prefix`, `precise-prefix` (실제 EPP에서 로드 확인) | 엔진 #46, #52 |
| W5 | rm-controller 0.2: `--apply`, `--rebalance`, 상태 인지 재배치, KEDA ScaledObject | 엔진 #45, #49 |
| W6 | `optimal` 배치와 시뮬레이터, 배치 문서 규범화 (rm-core v0.1.2, §5.4) | 엔진 #50 (실측 프로파일) |
| W7 | 전력 샘플링(`--power prom`, RNGD/ATOM/GPU exporter에서 실측), 모든 실행에 tok/J | 기준선 실험 진행 중 |

진행 상황은 허브의 Plane 프로젝트(모듈 W1–W7)에서 관리하고 [현재 상태](status.md)에 요약합니다.
