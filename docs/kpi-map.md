# 성과지표 대응표

「AI 반도체 통합 자원관리 기술 개발」 과제의 성과지표가 어느 계층·구성요소로 달성·측정되는지 정리한다.
이 저장소는 공개이므로 **수치와 증빙 파일은 넣지 않는다.** 수치는 각 구성요소의 연구 기록(비공개 Plane, MLflow)과
과제 증빙 폴더에 있고, 여기에는 연결 관계만 둔다.

| 성과지표 | 측정 지표 키 (`interfaces.md`) | 주 계층 | 구성요소 | 근거가 쌓이는 곳 |
|---|---|---|---|---|
| MFU | `mfu_pct` (+ peak 출처 태그) | L3, L2 | rngd-pd, hetero-npu-p2p | PD 실험 run (MLflow), 실험 기록 |
| 전력효율 | `gflops_per_w`, `power_w` | L3, L5 | rngd-pd, rm-bench, llm-d-setup(IPMI/DCGM exporter) | 측정 run, 전력 측정 구간 정의 |
| 이종 자원 수 | 장치 종류 수 (Accelerator.vendor/model) | L1, L4 | rm_abstract_layer, llm-d-setup | 클러스터 구성 기록, 장치 등록·발견·할당 시연 |
| SLO 달성률 | `ttft_p90_ms`, `tpot_p90_ms` | L4, L5 | llm-d-setup(EPP), rm-bench, lmd-top | 부하 시험 run |
| 메모리 통합 | `kv_transfer_ms`, 처리량 비 | L2 | duet, npu-offload, hetero-npu-p2p | 메모리 계층 실험 run |
| 확장성 (최대 노드 수) | 노드·가속기 수 | L4 | llm-d-setup | 클러스터 구성 기록 |
| 응용 서비스 수 | 서비스 수 | L3, L4 | rngd-pd, npu-offload, llm-d-setup(ModelService) | 서빙 구성 기록 |

## 증빙 원칙

- 수치마다 그 수치를 낸 실행(커밋 해시, 실행 조건, 원시 결과)을 연결한다.
  구성요소 repo에서 `report.py --metric ... --param ... --artifact ...`로 보고하면 연결이 자동으로 남는다.
- 가정이 들어간 수치(예: 공식 peak가 없어 다른 정밀도의 peak를 준용한 MFU)는 가정을 태그로 함께 남긴다.
- 보고서 기준일의 ai-rm 커밋(서브모듈 조합)을 기록해 둔다.
