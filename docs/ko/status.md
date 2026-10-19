# 현재 통합 상태와 접근 권한

[문서 홈](README.md) · [English](../status.md)

구성요소 목록이나 clone 성공은 adapter·chart·전체 시나리오 완료 증빙이 아닙니다. 고정된 커밋의 매니페스트, 작업 카드, 실제 검증 결과를 함께 확인하세요.

## Optimus Prime 전환 상태

목표 엔진은 `aicomp`의 **Optimus Prime**이며 `opt_prime` 런타임과 `fasop` 계획·탐색을 같은 제품으로 둡니다. 확인한 소스는 `main`이고 `optimus-prime`은 **미생성 제안 브랜치**입니다. 대상 커밋은 null, engine submodule은 비활성, 제안한 adapter도 미등록입니다. 기존 서브모듈이 현재 실행 소스입니다. [통합 설계](engine-integration.md)와 [계획 registry](../../config/engine-integration.yaml)를 참고하세요.

현재 FASOP은 이종 GPU 학습 비용 탐색입니다. 추론용 비용 보정·NPU 계획·검토된 llm-d 배치 adapter는 후속 구현이며 이번 문서 변경으로 실행·검증하지 않습니다.

## 저장소 접근 상태 · 2026-10-19

| 저장소 | 접근 |
|---|---|
| ai-rm, rm-core, rm_abstract_layer | 공개 |
| aicomp | Optimus Prime·FASOP 공개 소스, 아직 활성 엔진 서브모듈은 아님 |
| hetero-npu-p2p, npu-offload | 공개 |
| rngd-pd, npu-lora | 공개 |
| llm-d-setup | 공개 |
| rm-bench, rm-controller | ai-rm `packages/`에 포함 (rm-bench는 2026-10-19 이전, 기존 저장소는 archive) |
| lmd-top | 내부 주소 이력을 정리한 공개본 |
| duet | **비공개·선택 구성요소**, 별도 권한 필요 |

`git clone --recursive`와 `make setup`은 비공개 `duet`도 받으려 합니다. 공개 경로 선택 방법은 [시작하기](getting-started.md)에 있습니다.

## 최상위 도구의 현재 기능과 한계

| 영역 | 현재 기능 | 한계 |
|---|---|---|
| 구조 | 5계층 서브모듈과 문서 | 실제 동작은 각 저장소에서 구현 |
| in-tree 패키지 | `packages/rm-bench`(측정, 트레이스 재생), `packages/rm-controller`(토폴로지 배치), CI에서 테스트·계약 검사 | controller는 결정을 쓰지만 서빙 파드는 아직 따르지 않음 |
| 탐색 | `list`, `doctor`, 매니페스트 읽기 | 매니페스트가 없어 0 steps여도 검증 완료가 아님 |
| 설치·테스트 | 구성요소가 선언한 명령 실행 | 받은 커밋과 로컬 요구 사항에 의존 |
| 배포 | `deploy.manifests`를 kubectl로 적용, 사이트 Kustomize overlay | `deploy.chart`를 자동 Helm 배포하지 않음 |
| 계약 연결 | rm-core 규범 및 작업 카드 | adapter 구현·적합성은 구성요소별 확인 |
| 공개 검사 | 추적 파일 스캐너·CI | 전체 이력 감사나 하드웨어 검증을 대체하지 않음 |

Umbrella chart, 시뮬레이션 클러스터 명령, 서빙 파드가 따르는 부하 인지 배치, 호환성 registry는 통합 방향이며 아직 제공되지 않습니다. 배치 controller는 1차 구현이 있습니다(클러스터 dry-run 확인). PASS·FAIL·하드웨어 SKIP을 구분하고 구성요소 조합과 실행 조건을 남기세요.

## 프로토콜 v0.1 통합 · 2026-10-19 검증

모든 구성요소에 v0.1 adapter를 머지했고 서브모듈은 그 머지 커밋을 가리킵니다. 검증은 RNGD + ATOM 노드에서 Python
구성요소 전부를 **한** 환경(rm-core v0.1.1)에 설치해 수행했고, 고유 환경이 필요한 항목은 해당 구성요소 호스트에서 확인했습니다.

| 구성요소 | 고정 커밋 | Adapter / 역할 | 결과 |
|---|---|---|---|
| rm_abstract_layer | `c72f356` (0.4.1, chart 0.4.2) | `airm.accelerator_providers:rm-abstract` | 적합성 PASS, etri-001에서 RNGD 3 + ATOM 4 탐지(device plugin과 일치). *정정:* 처음 기록한 "ATOM 2, 벤더 도구와 일치"는 틀렸습니다. `rbln-stat` 번호 문제였고 0.4.1에서 수정 |
| hetero-npu-p2p | `9556e1a` | `airm.kv_transports:p2p` | 단위 테스트 91개 PASS, 적합성 **SKIP** (`HETERO_P2P_HELPER`와 실제 버퍼 fixture 필요) |
| npu-offload | `486d1e7` | `airm.workloads:npu-offload`, 메모리 계층 | `RNGD_LLMD` 설정 시 6/6 PASS, chart 렌더·lint 통과 |
| rngd-pd | `83ba553` | `airm.kv_transports:shm`, `airm.workloads:rngd-pd` | `shm` 적합성 PASS, 테스트 44개 PASS, chart 렌더·lint 통과 |
| npu-lora | `f9b7bc5` | `airm.workloads:npu-lora`, `airm_tok_s` | 테스트 PASS, chart 렌더·lint 통과 |
| llm-d-setup | `0f4f58e` | CRD, `airm_*` 수집, 대시보드, 배치 ConfigMap | 실제 클러스터에서 server dry-run PASS |
| lmd-top | `73e07d7` | `AcceleratorProfile`·`airm_*`·배치 결정 표시 | cargo 테스트 447 + 11개 PASS, clippy 경고 0 |
| rm-bench | in-tree | `airm.workloads:rm-bench`, 측정, 트레이스 재생 | 테스트 26개 PASS |
| rm-controller | in-tree | `airm.placements:topology` | 적합성 PASS, 테스트 12개 PASS |

L1 → L5 연결 검사(탐지 → 프로파일 → 배치 → 이름으로 고른 전송 → 전송 → 측정 → 워크로드 실행기 확인)는 rm-core만으로
통과하며, 2026-10-19에는 실제 클러스터에서 모든 계층을 함께 실행했습니다(L1 프로파일로 PD 파드 배치, llm-d 게이트웨이·EPP 경유,
`shm` KV 전송, rm-bench·lmd-top 측정·표시). 수치와 수정 사항, 남은 과제(배치 컨트롤러, 실제 버퍼 P2P, RNGD→ATOM decode)는
[end-to-end 실행](e2e.md)을 참고하세요.
모든 구성요소 트리의 민감정보 검사는 clean입니다.

## 기존 구조 변경

이전 `rm_monitor`의 역할은 `llm-d-setup/monitoring/`의 모니터링·Grafana, `rm-bench`의 trace·부하, `lmd-top`의 운영 콘솔로 나뉘었습니다. `rm_monitor`는 archive 상태이며 `rm_abstract_layer`는 `components/l1-accel/`에 있습니다.

## lmd-top 공개 이력

공개본에는 내부 주소를 문서용 주소로 치환한 브랜치·태그를 올렸습니다. 과거 PR·이슈를 포함한 원본은 `lmd-top-private-history`에 비공개로 보관하며 archive(읽기 전용) 상태입니다. 과거 터미널 녹화와 컴파일된 Python cache는 공개 이력에서 제외했고 상위 서브모듈 포인터를 정리된 커밋으로 갱신했습니다. 기존 개발 체크아웃은 새 clone 또는 신중한 rebase가 필요하며 이전 이력을 merge하면 제거한 내용이 재유입될 수 있습니다. 비공개 보관본은 공개 대상 구성요소가 아닙니다.
