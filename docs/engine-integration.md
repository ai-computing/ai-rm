# Optimus Prime consolidation plan

[Documentation](README.md) · [한국어](ko/engine-integration.md) · [Declarative plan](../config/engine-integration.yaml)

**Target: consolidate inference-engine technology in Optimus Prime, hosted in [`ai-computing/aicomp`](https://github.com/ai-computing/aicomp).** AI-RM remains the resource/cluster/operations integration hub. FASOP becomes a named planning element of the same engine product, rather than a separate runtime repository.

This change updates **AI-RM documentation and planning configuration only**. Engine code consolidation, the integration branch, adapter implementation and deployment are future work owned by the implementer. No implementation has been copied and no new runtime is activated.

![AI-RM hub, Optimus Prime runtime and FASOP planner, and their migration sources](assets/engine-consolidation.svg)

## Source and branch policy

The inspected source is `aicomp/main` at [`62a7831`](https://github.com/ai-computing/aicomp/tree/62a783114afa3531beeb7955c66da2e6aaf4ba65). Existing code lives under [`opt_prime/`](https://github.com/ai-computing/aicomp/tree/62a783114afa3531beeb7955c66da2e6aaf4ba65/opt_prime) and [`fasop/`](https://github.com/ai-computing/aicomp/tree/62a783114afa3531beeb7955c66da2e6aaf4ba65/fasop). The proposed consolidation branch name is **`optimus-prime`**; it is **not created by this AI-RM update**, and there is no validated target commit to pin yet.

`config/engine-integration.yaml` records this distinction explicitly: inspected source versus planned branch, null target revision and inactive engine submodule. It is an architecture registry, **not input to `tools/airm.py`**. `.gitmodules` keeps the existing source repositories and their commits during migration. Do not point active setup commands at a nonexistent branch.

## Ownership after consolidation

| Owner | Owns | Boundary |
|---|---|---|
| **AI-RM** | Resource integration, pinned combinations, cluster integration, observation and evidence | Coordinates components; does not own a second inference runtime |
| **Optimus Prime / `opt_prime`** | Unified inference runtime, backend adapters, prefill/decode, KV lifecycle/transport integration and expert offload | NPU and source-module integration remain planned; existing GPU features are not proof of NPU support |
| **FASOP / `fasop`** | Planning/search element inside Optimus Prime | Logical L4 policy interface; not a replacement for Kubernetes/llm-d routing |
| **rm-core** | Shared resource, transport, workload, placement and measurement contracts | Normative protocol changes require separate review |
| **hetero-llm-d** | Cluster setup, Gateway, InferencePool/EPP, model storage and monitoring | Executes reviewed configuration through established cluster mechanisms |
| **lmd-top / rm-bench** | Observation/operations and workload measurement | Consume the same engine/resource identity and metric definitions |

## Migration map

| Current source | Planned destination / role | Retained boundary |
|---|---|---|
| `rm-accel` | Engine-facing backend/execution adapters → Optimus Prime | L1 device discovery and capability publication remain a resource responsibility |
| `rngd-pd` | Optimus Prime PD-serving and NPU-backend modules | Preserve exact output behavior, transport selection and llm-d boundary until accepted |
| `hetero-npu-p2p` | Optimus Prime KV-transport module/integration | Same-host support, ABI constraints, completion fences and explicit failures |
| `npu-offload` | Optimus Prime expert-offload module | MoE weight/execution partitioning; not a `KVTransport` implementation |
| `aicomp/fasop` | Planning element of the same Optimus Prime product | Existing training estimates remain distinct from inference measurements |
| `npu-train` | Training workload, with an engine adapter where justified | Do not treat training integration as completed inference migration |
| `duet` | Optional private search/RAG workload | No private code is copied into the public engine |

The source repositories remain useful for development, provenance and comparison during the transition. Removing submodules or archiving source repositories is a later cutover decision after the consolidated engine is validated.

## FASOP: present capability versus planned role

The inspected FASOP code performs cost-based TP/PP/DP strategy search for **Transformer training on heterogeneous GPU clusters**, using profiles, memory constraints and candidate ranking. The inspected Optimus Prime code already exposes PP/TP inference, explicit prefill/decode and KV cache management. These are source observations, not tests executed by this documentation update.

The planned inference path is:

1. Discover supported resources and collect a workload/model profile.
2. Supply calibrated **inference** profiles and constraints to a FASOP adapter.
3. Produce a placement/parallelism proposal with assumptions and provenance.
4. Validate it against engine backend capabilities and the cluster configuration.
5. Apply a reviewed proposal through the llm-d integration boundary.
6. Measure TTFT, TPOT, throughput and SLO attainment; compare estimates with actual results.

Training step time, training throughput and estimated cost must not be relabeled as TTFT/TPOT or inference SLO attainment. Cross-vendor NPU planning, online adaptation and automatic EPP reconfiguration are not current FASOP capabilities established by this plan.

## Contract and configuration boundary

The proposed integration uses existing groups: an engine workload adapter named `optimus-prime` in `airm.workloads`, and a planner adapter named `fasop` in `airm.placements`. **Both are proposals, not registered implementations.** Do not run registry-loading commands for them until implemented. Any new protocol types belong in rm-core rather than ad hoc engine-local contracts.

The current umbrella CLI still dispatches existing component manifests; the planning YAML neither installs Optimus Prime nor deploys FASOP. Actual site addresses and credentials remain in untracked cluster configuration.

## Cutover acceptance

- The integration branch exists and an exact reviewed commit is available.
- Engine modules and adapters are implemented with their manifests and component documentation.
- Correctness, transport, backend and existing behavior checks pass; hardware SKIP is reported separately and cannot establish deployment readiness.
- FASOP's inference cost model is calibrated and its proposal format validated separately from runtime correctness.
- End-to-end cluster scenarios and measurements are reviewed for the actual supported hardware.
- AI-RM pins the accepted engine revision, and setup/deployment instructions are updated to real commands.

Until those conditions hold, the existing pinned submodules remain the executable integration path. See [status](status.md), [interfaces](interfaces.md) and the [component directory](components/README.md).
