# Optimus Prime 통합 설계

[문서 홈](README.md) · [English](../engine-integration.md) · [선언형 설정](../../config/engine-integration.yaml)

**추론 엔진 관련 기술은 [`ai-computing/aicomp`](https://github.com/ai-computing/aicomp)의 Optimus Prime으로 통합하는 방향입니다.** AI-RM은 자원·클러스터·운영·검증을 연결하는 상위 허브로 유지하고, FASOP은 같은 엔진 제품 안의 계획·탐색 요소로 포함합니다.

이번 변경은 **AI-RM의 문서와 계획 설정만** 수정합니다. 엔진 코드 통합, 통합 브랜치 생성, adapter 구현과 배포는 구현 담당자가 진행할 후속 작업입니다. 코드를 복사하거나 새 엔진을 활성화하지 않습니다.

![AI-RM 상위 허브, Optimus Prime 런타임·FASOP 계획 요소와 이전 소스의 관계](../assets/engine-consolidation.svg)

## 소스와 브랜치

확인한 소스는 `aicomp/main`의 [`62a7831`](https://github.com/ai-computing/aicomp/tree/62a783114afa3531beeb7955c66da2e6aaf4ba65)입니다. 현재 구현은 `opt_prime/`와 `fasop/`에 있습니다. 통합용 브랜치 이름은 **`optimus-prime`을 제안**하며, 이번 AI-RM 작업에서 실제 생성하지 않습니다. 아직 검증해 고정할 통합 대상 커밋은 없습니다.

`config/engine-integration.yaml`은 확인한 현재 소스와 향후 브랜치를 분리하고, 대상 커밋을 null·engine submodule을 비활성으로 기록합니다. 이 파일은 **설계 registry이며 `tools/airm.py`가 읽는 실행 설정이 아닙니다.** `.gitmodules`의 기존 소스와 고정 커밋은 유지해 존재하지 않는 브랜치 때문에 설치가 깨지지 않도록 합니다.

## 통합 후 책임

| 주체 | 책임 | 경계 |
|---|---|---|
| **AI-RM** | 자원 통합·버전 조합·클러스터 연결·관측·증빙 | 별도 추론 런타임을 중복 개발하지 않음 |
| **Optimus Prime / opt_prime** | 통합 추론 런타임·백엔드·PD·KV·전문가 오프로딩 | NPU와 기존 기술의 이전은 계획 상태 |
| **FASOP / fasop** | Optimus Prime 내부 계획·탐색 요소 | 논리적으로 L4 정책에 연결하되 k8s·llm-d 라우팅을 대체하지 않음 |
| **rm-core** | 자원·전송·작업·배치·측정 공통 계약 | 새로운 규범 타입은 별도 검토 |
| **llm-d-setup** | 클러스터·Gateway·InferencePool/EPP·스토어·모니터링 | 검토된 배치를 기존 클러스터 체계로 적용 |
| **lmd-top / rm-bench** | 관측·운영 / 부하·측정 | 같은 엔진·자원 식별자와 측정 정의 사용 |

## 기존 구성요소의 이동 방향

| 소스 | 통합 대상·역할 | 유지할 경계 |
|---|---|---|
| rm_abstract_layer | 엔진 실행·백엔드 adapter 부분 → Optimus Prime | 장치 탐지·능력 게시는 L1 자원 책임 |
| rngd-pd | Optimus Prime의 PD·NPU 백엔드 모듈 | 출력 동작·명시적 전송 선택·llm-d 연결 검증 |
| hetero-npu-p2p | Optimus Prime KV 전송 모듈·연동 | 동일 호스트·ABI·완료 fence·명시적 실패 |
| npu-offload | Optimus Prime 전문가 오프로딩 모듈 | KVTransport가 아닌 MoE 가중치·실행 분담 |
| aicomp/fasop | 같은 제품의 계획·탐색 요소 | 학습 비용 추정과 추론 실측 구분 |
| npu-lora | 학습 workload, 필요 시 엔진 adapter | 학습 통합을 추론 이전 완료로 간주하지 않기 |
| duet | 선택적인 비공개 검색·RAG workload | 공개 엔진으로 비공개 코드 복사 금지 |

기존 저장소는 이전 중 개발·출처·비교 기준으로 유지합니다. 서브모듈 제거·소스 저장소 archive는 통합 엔진 검증 이후의 전환 단계입니다.

## FASOP의 현재 기능과 추론 확장

확인한 FASOP은 **이종 GPU에서 Transformer 학습의 TP/PP/DP 전략을 비용 기반으로 탐색**합니다. 프로파일·메모리 제약·후보 순위를 사용합니다. Optimus Prime에는 PP/TP 추론, 명시적 prefill/decode, KV 캐시 관리 코드가 있습니다. 이번 작업에서 이 기능들을 실제 하드웨어로 검증한 것은 아닙니다.

향후 추론 연결은 **자원·워크로드 프로파일 → 추론용 비용 모델 보정 → FASOP 배치·병렬화 후보 → 엔진 지원 조건 검증 → llm-d 경계에서 검토된 적용 → 실측 피드백**으로 설계합니다. 학습 step time·training throughput·예상 비용을 TTFT·TPOT·추론 SLO로 이름만 바꾸면 안 됩니다. NPU 전체를 지원하는 계획, 온라인 적응, EPP 자동 재설정은 구현된 기능이 아닙니다.

## 계약과 설정

기존 entry point 그룹을 사용해 `airm.workloads`의 `optimus-prime`, `airm.placements`의 `fasop` adapter를 제안합니다. **둘 다 미구현 제안**이므로 아직 registry load 명령을 실행할 수 없습니다. 새 타입이 필요하면 rm-core에서 검토합니다.

현재 CLI는 기존 구성요소 매니페스트를 실행하며 계획 YAML은 엔진 설치·배포를 수행하지 않습니다. 사이트 주소·자격 증명은 계속 추적되지 않는 클러스터 설정에 둡니다.

## 전환 완료 기준

통합 브랜치와 정확한 검토 커밋, 구현된 모듈·adapter·매니페스트, 기존 동작·정확성·전송·백엔드 검증, 보정된 FASOP 추론 비용 모델, 실제 지원 하드웨어의 전체 시나리오와 실측을 확인해야 합니다. 하드웨어 SKIP은 별도로 기록하며 배포 준비 완료의 증거로 사용할 수 없습니다. 그 후 AI-RM의 엔진 커밋과 실행 절차를 실제 구현에 맞게 전환합니다.

그전에는 기존 서브모듈 조합이 실행 가능한 통합 경로입니다. [현재 상태](status.md), [인터페이스](interfaces.md), [구성요소](../components/README.md)를 함께 참고하세요.
