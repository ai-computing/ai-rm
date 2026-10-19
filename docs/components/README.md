# Component directory and integration cards

[Documentation](../README.md) · [한국어 문서](../ko/README.md) · [Optimus Prime plan](../engine-integration.md)

**Target product ownership:** Optimus Prime in `aicomp` owns the consolidated inference runtime and includes FASOP as its planning/search element. Existing repositories remain pinned migration sources until implementation and acceptance. Detailed legacy work cards below are maintained in Korean; they describe transition tasks, not verified completion.

## Target engine elements

| Element | Source / intended branch | Role | Card |
|---|---|---|---|
| **Optimus Prime** | `aicomp/opt_prime`; proposed branch `optimus-prime` | Unified runtime target; branch/adapters are not activated here | [Engine](optimus-prime.md) |
| **FASOP** | `aicomp/fasop`, same repository/product | Planning/search; existing training cost model, inference adapter planned | [Planner](fasop.md) |

## Current source and retained integration boundaries

| Layer | Current component | Transition role | Detailed card |
|---|---|---|---|
| L1 | rm_abstract_layer | Retain device discovery; engine-facing backend adapters target Optimus Prime | [Korean card](rm_abstract_layer.md) |
| L2 | hetero-npu-p2p | Source for the engine's KV-transport module | [Korean card](hetero-npu-p2p.md) |
| L2 | npu-offload | Source for expert-offload; workload/memory-tier contract, not KVTransport | [Korean card](npu-offload.md) |
| L2 / workload | duet | Optional private search workload; no public-code migration | [Korean card](duet.md) |
| L3 | rngd-pd | Source for engine PD/NPU-backend modules | [Korean card](rngd-pd.md) |
| L3 / workload | npu-lora | Training workload and future engine adapter as needed | [Korean card](npu-lora.md) |
| L4 | llm-d-setup | Keep cluster/routing/storage/monitoring; accept reviewed planner proposals | [Korean card](llm-d-setup.md) |
| L5 | lmd-top | Keep observation/operations; display engine and plan provenance | [Korean card](lmd-top.md) |
| L5 | rm-bench | Keep load/measurement; compare actual execution with planner estimates | [Korean card](rm-bench.md) |

Use the [integration guide](../integration-guide.md), [interfaces](../interfaces.md), [status](../status.md) and [declarative ownership plan](../../config/engine-integration.yaml). Do not remove a source submodule or declare its module migrated solely because the plan names a destination.

## 한국어 안내

통합 런타임은 Optimus Prime, 내부 계획·탐색 요소는 FASOP으로 정리합니다. 기존 소스 카드는 전환 중 계약과 검증 기준으로 유지하며 완료 여부는 실제 커밋·구현·검증으로 확인합니다. NPU LoRA는 학습 workload, duet은 비공개 검색 workload로 두고 상위 클러스터·관측·측정 책임은 유지합니다.
