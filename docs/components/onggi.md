# onggi — L2 카드

> **엔진과의 관계:** onggi는 엔진이 아니라 모델 가중치·컴파일 결과물 저장 계층입니다. 엔진은 onggi가 마운트한 파일을 읽을 뿐이며, Optimus Prime 쪽 로더 변경이 필요하면 aicomp에 기능 요청으로 남깁니다. [설계](https://github.com/ai-computing/onggi/blob/main/docs/ko/design.md) · [연계](https://github.com/ai-computing/onggi/blob/main/docs/ko/integration.md)

NPU는 모델 × SDK × 장치 × 길이 구간 × 배치 × 옵션마다 컴파일 결과물을 따로 만듭니다. ATOM은 결과물마다 가중치를 통째로
넣고, RNGD는 HF 원본과 같은 가중치를 여러 벌 보관합니다. onggi는 이것을 내용 주소 청크로 한 번만 저장하고, 필요한 노드에
미리 옮겨, 엔진에 일반 파일로 넘기는 저장 계층입니다(실측: [결과물 형식](https://github.com/ai-computing/onggi/blob/main/docs/ko/artifact-formats.md)).

| 실측(연구실 RNGD + ATOM 노드) | 논리 크기 | 고유 바이트 |
|---|--:|--:|
| ATOM Llama-3.1-8B 빌드 묶음(18개) | 261.8 GB | 44.7 GB (5.9배) |
| Llama-3.1-8B 한 벌(HF 원본, RNGD 변환본·그래프, ATOM 전체) | 330.0 GB | 64.0 GB (5.2배) |
| 노드 모델 저장소 전체 | 1.73 TB | 0.94 TB (1.84배) |

## 현재 단계: P0
- `onggi dedup-report`: 경로를 훑어 결과물 종류별 논리·고유·추가 바이트, 파일 쌍별 공유율, 고정 블록 비교를 출력(Go CLI).
- `ai-rm.yaml`: `layer: l2-memory`, `kind: tool`, `deploy.target: none`, rm-core 어댑터 없음.

## 다음에 할 일
1. P1: 청크 저장소와 `onggi push/pull`, 저장 백엔드는 API 하나로 교체 가능하게(파일 시스템·S3·OCI; 영속성은 하부 시스템에 위임)
2. P2: 노드 agent + CSI 볼륨 — rngd-pd가 첫 소비자
3. rm-core `ArtifactStore` 계약 제안(protocol v0.2), `airm_artifact_*` 지표
4. lmd-top Deploy 화면이 onggi CRD를 읽도록(현재 `model-inventory` ConfigMap)

## 완료 기준(이번 편입)
- [x] `python tools/airm.py list`에 onggi가 l2-memory로 표시
- [x] onggi CI(gofmt, vet, `test -race`, 빌드) 통과
- [ ] 런타임 연동 — P2 이후

## 하지 않을 것
- 영속 분산 저장소를 직접 구현(ADR-0002)
- 엔진·벤더 형식 수정
