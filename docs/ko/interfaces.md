[English](../interfaces.md) · [한국어 문서 홈](README.md)

# 계층 간 인터페이스

## Optimus Prime 통합 경계

추론 실행·백엔드 PD·KV 연동·전문가 offload는 Optimus Prime 런타임 책임으로 모으는 방향입니다. 자원 탐지·클러스터 라우팅·관측은 상위 계약으로 유지합니다. 같은 제품 안의 FASOP은 배치 계획 경계로 연결하며 EPP를 대체하지 않습니다.

[통합 설계](engine-integration.md)는 `airm.workloads`의 `optimus-prime`, `airm.placements`의 `fasop` adapter를 제안합니다. 둘 다 **미등록·미구현 제안**이며 새 규범 그룹을 추가하지 않습니다. 전환 전에는 기존 소스 adapter 경로를 유지합니다. FASOP의 학습 탐색 결과를 추론 배치로 쓰려면 추론 비용 모델 보정과 별도 검증이 필요합니다.

계약의 **정의는 [rm-core](https://github.com/ai-computing/rm-core)에 있습니다** —
[PROTOCOL.md](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md)(규범), `src/rm_core`(타입),
`python -m rm_core.conformance`(적합성 검사). 이 문서는 요약과 기존 코드와의 대응입니다.

| 계약 | entry-point 그룹 | 무엇 | 현재 대응 코드 |
|---|---|---|---|
| `Accelerator` / `AcceleratorProvider` | `airm.accelerator_providers` | 장치 하나의 능력(메모리, 정밀도별 peak와 출처, 전력, 인터커넥트), 노드의 장치 탐지 | rm_abstract_layer `resources/*`, `hardware_detector.py` |
| `AcceleratorProfile` (k8s) | — | 위 정보를 클러스터에 게시하는 CRD와 노드 레이블 `airm.ai-computing.io/<vendor>.<model>` | rm-core `k8s/`, `rm_core.k8s` |
| `MemoryTier` / `KVLayout` / `KVTransport` | `airm.kv_transports` | KV 이동: completion fence, 조용한 대체 금지, 이름으로 선택 | hetero-npu-p2p `core`·`backend`·`layout`, rngd-pd `connector/transport.py` |
| `Workload` / `Placement` | `airm.placements` | 무엇을(prefill/decode/serve/train/search) 어느 장치에, 어떤 KV 경로로 | llm-d EPP 설정, rngd-pd serving |
| workload runner | `airm.workloads` | 서빙·학습·검색 작업을 기동하는 진입점 | rngd-pd, npu-offload serve 모드, npu-lora trainer, duet |
| Metrics | — | 공통 지표 이름·단위·태그, Prometheus `airm_<name>` | 각 bench·exporter, `report.py --metric` |

## 공통 지표 (rm-core v0.1)

| 키 | 단위 | 의미 |
|---|---|---|
| `ttft_p50_ms`, `ttft_p90_ms`, `ttft_p99_ms` | ms | 첫 토큰 시간 |
| `tpot_p50_ms`, `tpot_p90_ms`, `tpot_p99_ms` | ms | 출력 토큰당 시간 |
| `e2e_p90_ms` | ms | 요청 전체 지연 |
| `tok_s` / `req_s` | tokens/s / requests/s | 처리량 |
| `power_w` (tag `scope=card\|node`), `energy_j` | W / J | 전력·에너지 |
| `gflops_per_w` | GFLOPS/W | 전력효율 |
| `mfu_pct` (tag `peak_source`) | % | MFU (분모 peak의 출처를 반드시 기록) |
| `kv_transfer_ms`, `kv_transfer_gbps` (tag `kv_transport`) | ms / GB/s | KV 이동 |
| `accuracy_pct` (tag `dataset`), `slo_attainment_pct` | % | 정확도, SLO 달성률 |
| `accelerators` (tag `vendor`/`model`) | count | 사용 장치 수 |

새 지표는 rm-core에 먼저 추가(minor 버전)한 뒤에 씁니다. 연결 작업 방법은 [integration-guide.md](integration-guide.md).
