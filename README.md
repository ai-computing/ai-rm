<div align="center">

<a href="docs/project-overview.md"><img src="docs/assets/hero.svg" width="100%" alt="AI-RM: unified resource management across GPU, NPU, CPU and GB10 unified memory on Kubernetes and llm-d, with Optimus Prime engine integration"></a>

<h3>Unified resource management for heterogeneous AI infrastructure</h3>

<p>
  <strong>English</strong> · <a href="README.ko.md">한국어</a>
</p>

<p>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/check-docs.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/check-docs.yml/badge.svg" alt="Documentation checks"></a>
  <a href="https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md"><img src="https://img.shields.io/badge/protocol-v0.1-7c5cff" alt="Protocol v0.1"></a>
  <a href="https://github.com/ai-computing/rm-core"><img src="https://img.shields.io/badge/rm--core-0.1.1-22d3ee" alt="rm-core 0.1.1"></a>
  <a href="deploy/README.md"><img src="https://img.shields.io/badge/target-Kubernetes%20%2B%20llm--d-326ce5?logo=kubernetes&amp;logoColor=white" alt="Target: Kubernetes and llm-d"></a>
  <a href="docs/status.md"><img src="https://img.shields.io/badge/stage-research%20%26%20integration-107e72" alt="Stage: research and integration"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-64748b" alt="License: BSD-3-Clause"></a>
</p>

<p>
  <a href="docs/getting-started.md"><b>Getting started</b></a> ·
  <a href="docs/architecture.md"><b>Architecture</b></a> ·
  <a href="docs/engine-integration.md"><b>Optimus Prime</b></a> ·
  <a href="docs/components/README.md"><b>Components</b></a> ·
  <a href="docs/status.md"><b>Status</b></a> ·
  <a href="docs/README.md"><b>Docs</b></a>
</p>

</div>

---

**AI-RM** is the integration hub for the **AI Semiconductor Integrated Resource Management** research project
(AI 반도체 통합 자원관리 기술 개발). It connects **GPU, NPU (FuriosaAI RNGD, Rebellions ATOM), CPU and GB10
unified-memory research** to **Kubernetes + llm-d** through shared contracts, pinned component versions and
reproducible measurements. Inference-engine technology is being consolidated into **Optimus Prime**, with
**FASOP** as its planning element.

## ✨ What it brings together

<table>
<tr>
<td width="33%" valign="top">
<img src="docs/assets/icon-chip.svg" width="44" alt="Chip icon"><br>
<b>Describe every device</b><br>
Discover GPUs, NPUs, CPUs and unified-memory systems and publish their capabilities through one <code>AcceleratorProfile</code> model.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-memory.svg" width="44" alt="Memory icon"><br>
<b>Move KV and experts by name</b><br>
NPU↔NPU KV transfer, NPU↔host expert offload and CPU↔GPU unified memory behind shared <code>KVTransport</code> and memory-tier contracts.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-serve.svg" width="44" alt="Serving icon"><br>
<b>One engine target</b><br>
Prefill/decode, KV and offload paths converge in Optimus Prime; FASOP plans parallelization and placement.
</td>
</tr>
<tr>
<td width="33%" valign="top">
<img src="docs/assets/icon-cluster.svg" width="44" alt="Cluster icon"><br>
<b>Kubernetes + llm-d native</b><br>
Gateway, InferencePool/EPP, model storage and monitoring through the extension points llm-d already has.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-observe.svg" width="44" alt="Observation icon"><br>
<b>One metric language</b><br>
TTFT, TPOT, tok/s, power and MFU under the same <code>airm_*</code> names in every layer, from the console to the KPI table.
</td>
<td width="33%" valign="top">
<img src="docs/assets/icon-contract.svg" width="44" alt="Contract icon"><br>
<b>Connected by contracts</b><br>
Components never import each other. Each registers an <a href="https://github.com/ai-computing/rm-core">rm-core</a> adapter, checked by conformance tests.
</td>
</tr>
</table>

## 🏗 Architecture

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="docs/assets/overview-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="docs/assets/overview-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/overview-dark.svg">
  <img src="docs/assets/overview-light.svg" width="100%" alt="Target architecture: AI-RM coordinates resource, cluster and operations integration; Optimus Prime contains the inference runtime and FASOP planning element; device research spans GPU, NPU, CPU and unified memory.">
</picture>

<details>
<summary><b>Five technical layers</b></summary>
<br>

<img src="docs/assets/architecture.svg" width="100%" alt="L1 to L5 responsibilities: accelerator abstraction, memory and transport modules, unified engine, cluster and planning boundary, observability and operations, all bound by rm-core contracts">

| Layer | Responsibility | Components |
|:-:|---|---|
| **L5** | Observability & operations | lmd-top · rm-bench |
| **L4** | Cluster & placement | hetero-llm-d · rm-controller · FASOP adapter *(planned)* |
| **L3** | Unified engine | Optimus Prime · rngd-pd *(migration source)* · npu-train |
| **L2** | Memory & transport | hetero-npu-p2p · npu-offload · onggi · duet |
| **L1** | Accelerator abstraction | rm-accel |

More: [architecture](docs/architecture.md) · [interfaces](docs/interfaces.md) · [engine consolidation plan](docs/engine-integration.md)
</details>

> [!IMPORTANT]
> **Integration in progress.** Optimus Prime is the planned unified engine in [`aicomp`](https://github.com/ai-computing/aicomp); its integration branch and adapters are not active yet, and FASOP's inference planning is future work. Existing repositories remain the pinned, executable sources. See [status](docs/status.md) for what is implemented versus planned.

## 🚀 Quick start

Explore without accelerator hardware or private-component access:

```bash
git clone https://github.com/ai-computing/ai-rm.git && cd ai-rm
python3 tools/airm.py list            # components · layers · versions · deployability
python3 tools/check_sensitive.py .    # scan for internal addresses, tokens and keys
```

<details>
<summary><b>Fetch components, install and test</b></summary>
<br>

[Initialize the public components by path](docs/getting-started.md#3-initialize-selected-components)
(a `--recursive` clone also attempts the private `duet`), then:

```bash
make doctor                     # prerequisites and missing pieces
make setup                      # install components (LAYER=l2-memory to limit)
make test                       # quick tests that need no accelerator
python -m rm_core.conformance   # contract checks: PASS / SKIP (no hardware) / FAIL
```

Full steps: [getting started](docs/getting-started.md).
</details>

<details>
<summary><b>Deploy to a Kubernetes + llm-d cluster</b></summary>
<br>

```bash
mkdir -p deploy/clusters/local
cp deploy/clusters/example/cluster.example.env deploy/clusters/local/cluster.local.env
$EDITOR deploy/clusters/local/cluster.local.env    # site values, never tracked
make deploy CLUSTER=local DRY_RUN=1                 # review before applying
```

See [deployment](deploy/README.md).
</details>

## 🧩 Ecosystem

| | Area | Components |
|:-:|---|---|
| 🚂 | **Engine & planning** | [Optimus Prime · `opt_prime`](https://github.com/ai-computing/aicomp/tree/main/opt_prime) · [FASOP · `fasop`](https://github.com/ai-computing/aicomp/tree/main/fasop) |
| 🟣 | **Resource discovery** | [rm-accel](https://github.com/ai-computing/rm-accel) |
| 🔵 | **Engine migration sources** | [rngd-pd](https://github.com/ai-computing/rngd-pd) · [hetero-npu-p2p](https://github.com/ai-computing/hetero-npu-p2p) · [npu-offload](https://github.com/ai-computing/npu-offload) |
| 🏺 | **Model & artifact store** | [onggi](https://github.com/ai-computing/onggi) *(P0)* |
| 🟡 | **Cluster integration** | [hetero-llm-d](https://github.com/ai-computing/hetero-llm-d) · [rm-controller](packages/rm-controller) · [rm-core contracts](https://github.com/ai-computing/rm-core) |
| 🟠 | **Operations & measurement** | [lmd-top](https://github.com/ai-computing/lmd-top) · [rm-bench](packages/rm-bench) |
| 🟢 | **Training & search workloads** | [npu-train](https://github.com/ai-computing/npu-train) · **duet** *(private, optional)* |

Responsibilities, source roles and integration tasks: [component directory](docs/components/README.md).

## 🔌 How it connects

Components implement an rm-core contract, register it as an entry point and are selected **by name**, so
switching a KV path is a configuration change rather than a code change.

```toml
# hetero-npu-p2p/pyproject.toml
[project.entry-points."airm.kv_transports"]
p2p = "hetero_p2p.airm:P2PTransport"
```

```python
from rm_core import registry
transport = registry.load("airm.kv_transports", "p2p")   # kvTransport: p2p | shm | loopback
```

| Contract | Entry-point group | Layer |
|---|---|:-:|
| `AcceleratorProvider` | `airm.accelerator_providers` | L1 |
| `KVTransport` | `airm.kv_transports` | L2 |
| Workload runner | `airm.workloads` | L3 |
| `Placement` | `airm.placements` | L4 |
| Metrics (`airm_*`) | — | all |

Details: [interfaces](docs/interfaces.md) · [integration guide](docs/integration-guide.md) · [`ai-rm.yaml` schema](docs/component-contract.md)

## 🗺 Roadmap

- [x] Five-layer layout, pinned submodules and setup tooling (`list` · `doctor` · `setup` · `test` · `deploy` · `check`)
- [x] rm-core v0.1 contracts, reference implementations, conformance checks and `AcceleratorProfile` CRD
- [x] Component adapters for protocol v0.1, verified together ([status](docs/status.md#protocol-v01-integration--verified-2026-10-19))
- [ ] Optimus Prime integration branch: PD, KV-transport and expert-offload modules from the migration sources
- [ ] FASOP inference planning and a reviewed llm-d placement adapter
- [x] First end-to-end run on the live cluster: L1 placement → llm-d → PD serving → measurement ([results](docs/e2e.md))
- [x] Real-trace replay and workload characterization ([traces](docs/workload-traces.md)); rm-bench and rm-controller in-tree under `packages/`
- [x] Placement controller, first version: topology-aware placement written to `airm-placement` (dry-run verified on the cluster)
- [ ] Serving pods that follow the placement decisions; load-aware placement; RNGD→ATOM decode and P2P with live buffers end to end
- [ ] Umbrella chart, simulated cluster and power / MFU evidence from every run
- [ ] Protocol v0.2: bind live buffers (`MemoryRegion`) to KV transfers

### Closing the gaps

Compared with llm-d, Dynamo, vLLM + NIXL/LMCache, Mooncake and HexGen-2/Helix, ai-rm is the only stack serving prefill/decode
across NPUs from different vendors. Seven gaps remain; engine-side parts are feature requests on
[aicomp](https://github.com/ai-computing/aicomp/issues), the rest is done here. Full plan: [roadmap](docs/roadmap.md).

| | Gap | Plan |
|:-:|---|---|
| W1 | Serving surface | Streaming, chat API, sampling, cancel ([#41](https://github.com/ai-computing/aicomp/issues/41)–[#43](https://github.com/ai-computing/aicomp/issues/43)); GuideLLM and MLPerf on the PD path |
| W2 | Scale and maturity | Batched decode ([#44](https://github.com/ai-computing/aicomp/issues/44)), S≥2048, node image + umbrella chart, sim cluster in CI, multi-node pools |
| W3 | KV transport standards | NIXL backend for RNGD↔ATOM, vLLM KV connector, layer-wise and GB-scale transfer ([#47](https://github.com/ai-computing/aicomp/issues/47), [#48](https://github.com/ai-computing/aicomp/issues/48)) |
| W4 | Cache reuse | KV block events and prefix reuse ([#46](https://github.com/ai-computing/aicomp/issues/46)), EPP prefix-cache routing, host-DRAM KV tier |
| W5 | Control loop | Placements enforced, P:D rebalancing, re-placement on failure, KEDA on `/metrics` ([#45](https://github.com/ai-computing/aicomp/issues/45), [#49](https://github.com/ai-computing/aicomp/issues/49)) |
| W6 | Formal scheduling | `optimal` placement over card types and KV link cost; FASOP inference cost model ([#50](https://github.com/ai-computing/aicomp/issues/50)) |
| W7 | Evidence | Same-budget baselines, tok/J in every run, paper drafts |

## 📚 Documentation

| Goal | Guides |
|---|---|
| 🧭 **Understand the project** | [Overview](docs/project-overview.md) · [Architecture](docs/architecture.md) · [Research scenarios](docs/research-scenarios.md) · [Glossary](docs/glossary.md) |
| 🔧 **Connect an implementation** | [Engine plan](docs/engine-integration.md) · [Interfaces](docs/interfaces.md) · [Integration guide](docs/integration-guide.md) |
| 📊 **Run and evaluate** | [Getting started](docs/getting-started.md) · [Deployment](deploy/README.md) · [KPI and evidence](docs/kpi-map.md) |
| 📍 **Check progress** | [Status](docs/status.md) · [Roadmap](docs/roadmap.md) · [Planning configuration](config/engine-integration.yaml) |

[All documentation](docs/README.md) · [한국어 문서](docs/ko/README.md)

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for implementation boundaries, documentation and validation, and use
[GitHub Issues](https://github.com/ai-computing/ai-rm/issues) for questions and proposals.

> [!NOTE]
> This repository is public. Keep site configuration, internal addresses and credentials out of tracked files; site values live only in the untracked `cluster.local.env`. See the [security guide](docs/security.md).

## 📄 License

[BSD-3-Clause](LICENSE) for this integration repository. Each component retains its own license.

<div align="center"><sub>Built by the ai-computing team · ETRI</sub></div>
