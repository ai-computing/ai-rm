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

## 현재 단계: P2

- Go CLI: `dedup-report`, POSIX/S3 저장소의 `push/pull`, 청크 해시 검증, ref와 GC.
- 노드 캐시·peer 전송, 같은 오프셋의 바이트를 보존하는 파일 델타 적용, 읽기 전용 CSI 볼륨.
- CSI는 같은 manifest의 복원 요청을 합치고, 서로 다른 artifact의 동시 복원 수를 제한합니다(기본 `--pulls 1`).
- `ai-rm.yaml`: `layer: l2-memory`, `kind: tool`, `deploy.target: none`. CSI 예제는 사이트별 이미지·저장소 설정 후 수동 설치하며 rm-core 어댑터는 아직 없습니다.

파일 델타 전달과 NPU 메모리 갱신은 별도입니다. 서빙 런타임이 체크포인트·SDK·장치·가중치 배열·지원 B/S를
검사하고 준비된 그래프를 선택해야 합니다. RNGD 외부 가중치, ATOM 장치 입력 가중치, 가중치 내장 ATOM 그래프의
지원 범위를 서로 동일하게 간주하지 않습니다.

## 다음에 할 일
1. 준비된 변형의 체크포인트·컴파일러·SDK·장치·배열·B/S 메타데이터와 런타임 설정 연결, 실제 서빙 요청으로 검증.
2. P3: `ArtifactSet` CRD·컴파일 팜; P4: 배치·확장 신호에 따른 프리페치와 readiness 비용 연동.
3. rm-core `ArtifactStore` 계약 제안(protocol v0.2), `airm_artifact_*` 지표.
4. lmd-top Deploy 화면의 CRD 연동(현재 `model-inventory` ConfigMap).

## 완료 기준(이번 편입)
- [x] `python tools/airm.py list`에 onggi가 l2-memory로 표시
- [x] Linux에서 onggi gofmt·vet·`test -race`·CLI 빌드 검증
- [ ] 런타임 설정 자동 생성·예열·실제 NPU 서빙 통합 검증

## 하지 않을 것
- 영속 분산 저장소를 직접 구현(ADR-0002)
- 엔진·벤더 형식 수정
