<p align="center"><img src="docs/assets/hero.svg" alt="AI-RM — unified resource management for GPU, NPU, CPU and unified-memory systems" width="100%"></p>

<p align="center">
  <strong>English</strong> · <a href="README.ko.md">한국어</a><br>
  <a href="docs/README.md">Documentation</a> · <a href="docs/engine-integration.md">Optimus Prime</a> · <a href="docs/architecture.md">Architecture</a> · <a href="docs/getting-started.md">Getting started</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-55d6be" alt="License: BSD-3-Clause"></a>
  <a href="docs/architecture.md"><img src="https://img.shields.io/badge/platform-Kubernetes%20%2B%20llm--d-65b9ff" alt="Target: Kubernetes plus llm-d"></a>
  <a href="docs/status.md"><img src="https://img.shields.io/badge/status-research%20%26%20integration-f4c46b" alt="Status: research and integration"></a>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/check-sensitive.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/check-sensitive.yml/badge.svg" alt="Sensitive-data check"></a>
</p>

# AI-RM · Unified Resource Management for AI Accelerators

**One resource integration hub. One unified inference-engine direction: Optimus Prime.**

AI-RM is the integration hub for the **AI Semiconductor Integrated Resource Management Technology Development** project (AI 반도체 통합 자원관리 기술 개발). It connects research on **GPUs, FuriosaAI RNGD, Rebellions ATOM, CPUs and GB10 unified-memory systems**, targeting **Kubernetes + llm-d** clusters. Inference-engine technology is planned to consolidate into **[Optimus Prime in `aicomp`](https://github.com/ai-computing/aicomp)**, including **FASOP** as its planning/search element.

This repository owns resource/cluster integration, shared interface guides, pinned source revisions and operations/evidence tooling. **The consolidation is a documented plan, not an implemented migration.** Existing component repositories remain pinned sources until the unified engine is implemented and accepted. The proposed `aicomp` branch is `optimus-prime`; it is not created or activated by this update. See the [engine plan](docs/engine-integration.md) and [status](docs/status.md).

![Conceptual AI research laboratory with accelerator servers and a compact compute system](docs/assets/lab-environment.png)
*AI-generated environment illustration; not a photograph of the project's installation or deployment evidence.*

## What does AI-RM connect?

| | Research area | Purpose |
|---|---|---|
| <img src="docs/assets/icon-chip.svg" width="40" alt="Device icon"> | **Discover heterogeneous devices** | Express device discovery and capabilities through a common abstraction. |
| <img src="docs/assets/icon-memory.svg" width="40" alt="Memory icon"> | **Use memory across tiers** | Study NPU KV transfer, MoE expert offload and CPU–GPU cooperation on unified memory. |
| <img src="docs/assets/icon-serve.svg" width="40" alt="Serving icon"> | **Execute inference and training** | Connect prefill/decode disaggregation and NPU training workloads. |
| <img src="docs/assets/icon-cluster.svg" width="40" alt="Cluster icon"> | **Integrate the cluster** | Connect Kubernetes + llm-d routing, device profiles, model storage and monitoring. |
| <img src="docs/assets/icon-observe.svg" width="40" alt="Observation icon"> | **Measure reproducibly** | Align latency, throughput, power and SLO metrics with experiment context and KPI evidence. |

## Five layers, one integration architecture

![L1 accelerator abstraction, L2 memory and transport, L3 execution and serving, L4 cluster orchestration, L5 observability and operations, with shared rm-core contracts](docs/assets/architecture.svg)

[`rm-core`](https://github.com/ai-computing/rm-core) defines shared contracts. Components connect through adapters, named entry points and common measurement formats. The submodule commits in AI-RM pin an integration revision.

## Optimus Prime: the engine consolidation target

![AI-RM coordinates resource and cluster integration; Optimus Prime in aicomp contains the opt_prime runtime and fasop planner, with existing repositories as migration sources](docs/assets/engine-consolidation.svg)

| Part | Intended owner | Current boundary |
|---|---|---|
| **Inference runtime** | Optimus Prime · `aicomp/opt_prime` | Existing PP/TP inference and KV APIs; NPU/PD/transport/offload consolidation is planned. |
| **Planning and search** | FASOP · `aicomp/fasop`, within Optimus Prime | Current heterogeneous-GPU **training** cost search; inference-specific calibration and adapters are planned. |
| **Resources, cluster and operations** | AI-RM + rm-core + llm-d-setup + lmd-top/rm-bench | Keep resource contracts, Gateway/EPP, observation and reproducible evidence at the hub boundary. |
| **External workloads** | npu-lora; private optional duet | Training and search workloads connect through explicit adapters; private code stays private. |

The [declarative plan](config/engine-integration.yaml) records ownership, source roles, the proposed branch and cutover criteria. It is **not runtime configuration** and is not consumed by the current CLI. [Read the consolidation design](docs/engine-integration.md).

## Current source components

The following repositories remain the executable sources during transition. Engine-facing parts of `rm_abstract_layer`, PD serving, KV transport and expert offload are planned Optimus Prime modules; the L1 resource-discovery responsibility remains separate.

| Layer | Component | Role | Details |
|---|---|---|---|
| **L1 · Accelerator** | [rm_abstract_layer](https://github.com/ai-computing/rm_abstract_layer) | Device discovery, capability models and plugins | [Card](docs/components/rm_abstract_layer.md) |
| **L2 · Memory** | [hetero-npu-p2p](https://github.com/ai-computing/hetero-npu-p2p) | Completion-fenced KV transfer between compatible same-host NPUs | [Card](docs/components/hetero-npu-p2p.md) |
| **L2 · Memory** | [npu-offload](https://github.com/ai-computing/npu-offload) | Hot experts on NPU HBM; cold expert execution on the host CPU | [Card](docs/components/npu-offload.md) |
| **L2 · Memory** | **duet** · private / optional | GB10 vector search: CPU graph traversal + GPU distance computation | [Card](docs/components/duet.md) |
| **L3 · Execution** | [rngd-pd](https://github.com/ai-computing/rngd-pd) | RNGD prefill + ATOM decode disaggregated serving | [Card](docs/components/rngd-pd.md) |
| **L3 · Execution** | [npu-lora](https://github.com/ai-computing/npu-lora) | LoRA and full fine-tuning research on inference-oriented NPUs | [Card](docs/components/npu-lora.md) |
| **L4 · Cluster** | [llm-d-setup](https://github.com/ai-computing/llm-d-setup) | Kubernetes + llm-d, routing, model storage and monitoring | [Card](docs/components/llm-d-setup.md) |
| **L5 · Operations** | [lmd-top](https://github.com/ai-computing/lmd-top) | Terminal console for cluster observation and operations | [Card](docs/components/lmd-top.md) |
| **L5 · Operations** | [rm-bench](https://github.com/ai-computing/rm-bench) | Trace replay, synthetic load and latency measurements | [Card](docs/components/rm-bench.md) |

`duet` stays private. It is optional for documentation and public-component exploration. See [access and readiness](docs/status.md) before initializing submodules.

## Follow the workload and the data

**Disaggregated LLM serving.** The target routes requests to Optimus Prime prefill/decode workers. Existing RNGD/ATOM PD technology is a migration source. KV state uses an explicitly selected transport; P2P requires compatible same-host hardware and ABI, and host staging is a separate path. The new engine/backend and llm-d adapters are planned.

![Target flow from client and Gateway/EPP to Optimus Prime prefill/decode workers and an explicit KV transport, with metrics](docs/assets/request-flow.svg)

**Memory research beyond KV.** Expert offload and unified-memory vector search move different data and execute different parts of the workload.

![Three distinct memory paths: NPU KV transfer, MoE expert offload and private optional GB10 unified-memory search](docs/assets/memory-paths.svg)

Read the [architecture](docs/architecture.md), [interfaces](docs/interfaces.md) and [research scenarios](docs/research-scenarios.md) for each path's responsibilities and limits.

## Start here

### Explore without accelerator hardware

```bash
git clone https://github.com/ai-computing/ai-rm.git
cd ai-rm
python3 tools/airm.py list
python3 tools/check_sensitive.py .
```

The top-level clone includes documentation and integration tools. A cluster and `duet` access are not required to read them. Uninitialized components appear as **not fetched** in `list`.

### Fetch public components

Avoid `--recursive` unless you also have access to private `duet`. Initialize the public components explicitly:

```bash
git submodule update --init -- \
  components/l1-accel/rm_abstract_layer \
  components/l2-memory/hetero-npu-p2p \
  components/l2-memory/npu-offload \
  components/l3-serving/rngd-pd \
  components/l3-serving/npu-lora \
  components/l4-cluster/llm-d-setup \
  components/l5-ops/rm-bench \
  components/l5-ops/lmd-top
```

All listed paths are public, including the sanitized `lmd-top` export. See [getting started](docs/getting-started.md) for prerequisites and selected-component installation. `make setup` invokes `make init` and attempts to fetch **all** submodules, including `duet`; use the Python CLI for a public-only checkout. This installs current sources, not the planned consolidated engine.

### Prepare an authorized cluster

In a configured Linux environment with Python 3.8+, Git and component-specific prerequisites:

```bash
python3 -m pip install PyYAML
python3 tools/airm.py doctor
python3 tools/airm.py setup --layer l3-serving
python3 tools/airm.py test --layer l3-serving
mkdir -p deploy/clusters/local
cp deploy/clusters/example/cluster.example.env deploy/clusters/local/cluster.local.env
# Edit the untracked cluster.local.env with your site settings.
python3 tools/airm.py deploy --cluster local --dry-run --layer l3-serving
```

Deployment currently applies each component's `deploy.manifests` with `kubectl`; components without manifests are skipped. Client dry run requires appropriate local Kubernetes configuration and is not proof of a successful deployment. See [deployment](deploy/README.md).

## Documentation

The **[documentation hub](docs/README.md)** provides wiki-style navigation in English, with **[한국어 문서](docs/ko/README.md)** alongside it.

| I want to… | Read |
|---|---|
| Understand the project and its boundaries | [Overview](docs/project-overview.md) · [Status](docs/status.md) |
| Understand the unified engine direction | [Optimus Prime + FASOP plan](docs/engine-integration.md) · [Planning configuration](config/engine-integration.yaml) |
| Understand the layers and workloads | [Architecture](docs/architecture.md) · [Scenarios](docs/research-scenarios.md) |
| Set up a checkout or prepare a cluster | [Getting started](docs/getting-started.md) · [Deployment](deploy/README.md) |
| Integrate an implementation | [Interfaces](docs/interfaces.md) · [Integration](docs/integration-guide.md) · [Contract](docs/component-contract.md) |
| Find a component's integration tasks | [Component directory and work cards](docs/components/README.md) |
| Understand measurements and terms | [KPI map](docs/kpi-map.md) · [Glossary](docs/glossary.md) |
| Contribute or maintain the visuals | [Contributing](CONTRIBUTING.md) · [Asset provenance and prompts](docs/assets/README.md) |

## Research and evidence

![Discover devices, connect adapters, execute workloads and record reproducible measurements](docs/assets/research-workflow.svg)

Research maps to **MFU, power efficiency, heterogeneous resource coverage, SLO attainment, memory integration, scalability and application services**. Public documents describe methods and component mapping. Unreleased numerical results and project evidence remain in designated private research records; this page does not claim benchmark gains. See the [KPI map](docs/kpi-map.md).

## Contributing and license

Read [CONTRIBUTING.md](CONTRIBUTING.md), the relevant component card and [rm-core's normative protocol](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md). Keep site settings and credentials in untracked configuration; run `make check` before publishing changes.

This integration repository uses [BSD-3-Clause](LICENSE). Each component retains its own license; check its repository before reuse.
