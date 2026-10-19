# 아키텍처

[문서 홈](README.md) · [English](../architecture.md)

AI-RM은 자원 표현, 데이터 이동, 워크로드 실행, 클러스터 연결, 관측을 분리합니다. 기본 환경은 Kubernetes + llm-d입니다. **그림은 논리적 책임을 설명하며 구성요소별 구현·배포·검증 완료를 뜻하지 않습니다.**

추론 엔진 책임은 `aicomp`의 **[Optimus Prime](engine-integration.md)**으로 모으는 방향입니다. `opt_prime`은 런타임, `fasop`은 같은 제품의 계획·탐색 요소입니다. FASOP은 논리적으로 L4, 런타임은 L3, 메모리 모듈은 L2에 연결됩니다. 계층별 상자가 반드시 서로 다른 소스 저장소를 뜻하지는 않습니다.

![Optimus Prime 중심의 5계층 목표 구조](../assets/architecture.svg)

## 계층별 책임

| 계층 | 책임 | 구성요소·연결 지점 |
|---|---|---|
| L1 가속기 추상화 | 장치 탐지·메모리·정밀도·peak 출처·전력·인터커넥트 | rm_abstract_layer, AcceleratorProfile과 노드 레이블 |
| L2 메모리·전송 | 메모리 계층과 워크로드 데이터 이동 | Optimus Prime KV/offload 모듈 계획, 기존 hetero-npu-p2p/npu-offload 소스, 별도 비공개 duet |
| L3 통합 엔진·워크로드 | 단일 런타임 책임으로 추론 실행, 학습 연결 | Optimus Prime 목표, rngd-pd 이전 소스, npu-lora workload |
| L4 클러스터·계획 | 라우팅·검토된 배치 제안·스토어·모니터링 | llm-d-setup의 Gateway/InferencePool/EPP, 엔진 내부 FASOP adapter 계획 |
| L4 배치 | 서빙 풀마다 가속기를 고르고 결정을 게시 | rm-controller (`airm-placement`) |
| L5 관측·운영 | 운영 관측·부하·측정 증빙 | lmd-top, rm-bench, 공통 지표 |

## 요청 흐름

![목표 Optimus Prime prefill/decode와 명시적인 KV 경로](../assets/request-flow.svg)

1. 요청은 Gateway와 llm-d 라우팅·배치 연결 지점에 도착합니다.
2. 목표 구조는 Optimus Prime prefill/decode worker를 연결합니다. 기존 RNGD prefill + ATOM decode는 이전 소스이며 NPU 백엔드와 통합 서빙 adapter는 구현·검증이 필요합니다.
3. KV는 이름으로 선택한 경로를 사용합니다. `p2p`는 동일 호스트의 호환 장치·ABI 조건이 필요하고 `shm`은 host staging입니다. 실패 시 다른 경로로 조용히 대체하지 않습니다.
4. 지표를 모니터링·벤치마크에 연결합니다. FASOP adapter는 검토할 제안을 만드는 방향이며 현재 학습 비용 추정을 추론 SLO 실측으로 보고하지 않습니다. 완성된 자동 배치 controller를 뜻하지 않습니다.

L1은 능력 모델을 제공하며 모든 요청이 거치는 네트워크 hop이 아닙니다. L5는 추론 트래픽을 전달하기보다 전체 동작을 관측합니다.

## 서로 다른 메모리 경로

![KV 전송, MoE offload, 통합메모리 검색](../assets/memory-paths.svg)

- **hetero-npu-p2p:** 동일 호스트의 호환 NPU 사이 KV 전송과 완료 fence.
- **npu-offload:** NPU HBM과 호스트 CPU/DRAM에 전문가 실행 분담. v0.1은 KVTransport가 아닌 workload·memory-tier 계약으로 연결합니다.
- **duet:** GB10에서 CPU 그래프 순회와 GPU 거리 계산을 공유 메모리로 연결하는 비공개 선택 검색 workload입니다.

## 저장소와 계약 경계

기존 소스는 이전 중 고정합니다. 엔진 기술은 `aicomp/opt_prime`, 계획 요소는 `aicomp/fasop`으로 통합하는 방향이며 공개 자원·클러스터·워크로드 경계는 유지합니다. [책임 대응표](engine-integration.md)를 참고하세요.

어떤 구성요소도 맡지 않는 통합 코드는 ai-rm의 `packages/`에 둡니다. `rm-bench`(측정, 트레이스 재생)와 `rm-controller`(L4 배치)는
ai-rm의 profile·시나리오와 함께 바뀌므로 같은 커밋으로 관리합니다. `rm-core`는 모든 구성요소가 고정하는 계약이라 별도 저장소로 둡니다
(umbrella 안에 두면 구성요소가 ai-rm에 의존하게 됩니다). NPU 벤더 backend(RNGD/ATOM 그래프·커널·컴파일 캐시)는 별도 저장소가 아니라
`aicomp`의 Optimus Prime으로 통합합니다.

규범 계약은 [rm-core](https://github.com/ai-computing/rm-core)에 있습니다. 서브모듈 포인터가 조합을 고정하지만 그 자체로 전체 검증 증빙은 아닙니다. 실제 구성요소의 `ai-rm.yaml`이 설치·테스트·배포를 선언하고 계획 registry는 실행되지 않습니다. 사이트 값은 추적되지 않는 `cluster.local.env`에 둡니다.

[현재 상태](status.md), [인터페이스](interfaces.md), [구성요소 작업 카드](../components/README.md)를 함께 확인하세요.
