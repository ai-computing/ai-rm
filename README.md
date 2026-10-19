<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/wordmark-dark.svg">
    <img src="docs/assets/wordmark-light.svg" width="260" alt="AI-RM">
  </picture>
</p>

<p align="center"><strong>Unified resource management for heterogeneous AI infrastructure.</strong></p>

<p align="center">
  <strong>English</strong> · <a href="README.ko.md">한국어</a><br>
  <a href="docs/README.md">Documentation</a> · <a href="docs/getting-started.md">Getting started</a> · <a href="docs/architecture.md">Architecture</a> · <a href="docs/engine-integration.md">Optimus Prime</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-BSD--3--Clause-64748b" alt="License: BSD-3-Clause"></a>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/check-docs.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/check-docs.yml/badge.svg" alt="Documentation checks"></a>
  <a href="docs/status.md"><img src="https://img.shields.io/badge/Stage-Research%20%26%20integration-107e72" alt="Stage: research and integration"></a>
</p>

AI-RM is the integration hub for the **AI Semiconductor Integrated Resource Management** research project (AI 반도체 통합 자원관리 기술 개발). It connects **GPU, NPU, CPU and GB10 unified-memory research** to **Kubernetes + llm-d** through shared contracts, pinned component versions and reproducible measurements.

- **Describe resources** — discover devices and express their capabilities through a common model.
- **Connect engine technology** — consolidate inference, KV transport and expert offload into Optimus Prime, with FASOP as its planning element.
- **Observe and evaluate** — align cluster operations, workload measurements and project evidence.

## Quick start

Explore the repository without accelerator hardware or private-component access:

```bash
git clone https://github.com/ai-computing/ai-rm.git
cd ai-rm
python3 tools/airm.py list
```

To install components or prepare a cluster, follow [getting started](docs/getting-started.md). For a public-only checkout, initialize the [selected public submodules](docs/getting-started.md#3-initialize-selected-components); a recursive clone also attempts private `duet`.

## Architecture

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="docs/assets/overview-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="docs/assets/overview-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/overview-dark.svg">
  <img src="docs/assets/overview-light.svg" width="100%" alt="Target architecture: AI-RM coordinates resource, cluster and operations integration; Optimus Prime contains the inference runtime and FASOP planning element; device research spans GPU, NPU, CPU and unified memory.">
</picture>

**Integration in progress.** Optimus Prime is the planned unified inference engine in [`aicomp`](https://github.com/ai-computing/aicomp). FASOP currently searches training parallelization strategies; inference planning is future work. Existing repositories remain pinned migration sources. See the [five-layer architecture](docs/architecture.md), [engine consolidation plan](docs/engine-integration.md) and [current status](docs/status.md).

## Ecosystem

| Area | Components |
|---|---|
| **Engine & planning** | [Optimus Prime · `opt_prime`](https://github.com/ai-computing/aicomp/tree/main/opt_prime) and [FASOP · `fasop`](https://github.com/ai-computing/aicomp/tree/main/fasop) in `aicomp` |
| **Resource discovery** | [rm_abstract_layer](https://github.com/ai-computing/rm_abstract_layer) |
| **Engine migration sources** | [rngd-pd](https://github.com/ai-computing/rngd-pd) · [hetero-npu-p2p](https://github.com/ai-computing/hetero-npu-p2p) · [npu-offload](https://github.com/ai-computing/npu-offload) |
| **Cluster integration** | [llm-d-setup](https://github.com/ai-computing/llm-d-setup) · [rm-core contracts](https://github.com/ai-computing/rm-core) |
| **Operations & measurement** | [lmd-top](https://github.com/ai-computing/lmd-top) · [rm-bench](https://github.com/ai-computing/rm-bench) |
| **Training & search workloads** | [npu-lora](https://github.com/ai-computing/npu-lora) · **duet** (private, optional) |

Find responsibilities, source roles and integration tasks in the [component directory](docs/components/README.md).

## Documentation

| Explore | Guides |
|---|---|
| **Understand the project** | [Overview](docs/project-overview.md) · [Architecture](docs/architecture.md) · [Research scenarios](docs/research-scenarios.md) |
| **Connect an implementation** | [Engine plan](docs/engine-integration.md) · [Interfaces](docs/interfaces.md) · [Integration guide](docs/integration-guide.md) |
| **Run and evaluate** | [Getting started](docs/getting-started.md) · [Deployment](deploy/README.md) · [KPI and evidence](docs/kpi-map.md) |
| **Check progress** | [Status](docs/status.md) · [Planning configuration](config/engine-integration.yaml) |

[All documentation](docs/README.md) · [한국어 문서](docs/ko/README.md) · [Glossary](docs/glossary.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for implementation boundaries, documentation and validation. Use [GitHub Issues](https://github.com/ai-computing/ai-rm/issues) for questions and proposals. Keep site configuration and credentials out of tracked files; follow the [security guide](docs/security.md).

## License

[BSD-3-Clause](LICENSE) for this integration repository. Each component retains its own license.
