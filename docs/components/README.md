# 구성요소 카드 (protocol v0.1)

각 repo가 v0.1 통합에서 할 일입니다. 공통 방법은 [../integration-guide.md](../integration-guide.md).

| 계층 | 카드 | 핵심 |
|---|---|---|
| L1 | [rm_abstract_layer](rm_abstract_layer.md) | `AcceleratorProvider` + 노드 데몬(AcceleratorProfile 게시) |
| L2 | [hetero-npu-p2p](hetero-npu-p2p.md) | `KVTransport` `p2p` |
| L2 | [npu-offload](npu-offload.md) | workload runner(serve) + 지표 + chart |
| L2 | [duet](duet.md) | (보류) 노드 네트워크 복구 후 |
| L3 | [rngd-pd](rngd-pd.md) | KV 경로를 이름으로 선택, 기존 /dev/shm 경로를 `KVTransport` `shm`으로, chart |
| L3 | [npu-lora](npu-lora.md) | workload runner(train) + Job chart |
| L4 | [llm-d-setup](llm-d-setup.md) | CRD 설치, airm 지표 수집, 배치 결정 전달 지점 |
| L5 | [lmd-top](lmd-top.md) | AcceleratorProfile과 airm 지표 표시 |
| L5 | [rm-bench](rm-bench.md) | 결과를 Measurement 형식으로, end-to-end 시나리오 실행기 |
