<div align="center">

<img src="assets/banner.svg" alt="ai-rm — unified resource management for AI accelerators" width="100%">

**English** | [한국어](README.ko.md)

<br>

[![check-sensitive](https://github.com/ai-computing/ai-rm/actions/workflows/check-sensitive.yml/badge.svg)](https://github.com/ai-computing/ai-rm/actions/workflows/check-sensitive.yml)
[![protocol](https://img.shields.io/badge/protocol-v0.1-7c5cff)](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md)
[![rm-core](https://img.shields.io/badge/rm--core-0.1.1-22d3ee)](https://github.com/ai-computing/rm-core)
[![target](https://img.shields.io/badge/target-Kubernetes%20%2B%20llm--d-34d399)](deploy/README.md)
[![python](https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&logoColor=white)](https://github.com/ai-computing/rm-core)
[![license](https://img.shields.io/badge/license-BSD--3--Clause-lightgrey)](LICENSE)

**GPUs, NPUs (FuriosaAI RNGD, Rebellions ATOM), CPUs and unified-memory systems (GB10) as one cluster resource**<br>
Five layers — from device discovery to placement, serving, KV movement and observability — connected by contracts

[**Quick start**](#-quick-start) · [**Architecture**](#-architecture) · [**Components**](#-components) · [**How it connects**](#-how-it-connects) · [**Docs**](#-docs) · [**Roadmap**](#-roadmap)

</div>

---

## ✨ Highlights

<table>
<tr>
<td width="33%" valign="top">

### 🧩 Connected by contracts
Components never import each other. Each registers a small adapter that implements a
[rm-core](https://github.com/ai-computing/rm-core) contract, so switching a KV path or a
placement policy is **a name in the config, not a code change**.

</td>
<td width="33%" valign="top">

### ☸️ Kubernetes + llm-d first
Every piece plugs into an extension point llm-d already has — model-server pods, vLLM
`KVConnector`, the EPP — plus an `AcceleratorProfile` CRD that publishes each node's devices.

</td>
<td width="33%" valign="top">

### 📏 One metric language
TTFT, TPOT, tok/s, W and MFU are reported by every layer **under the same names and units**,
so dashboards, benchmarks and KPI tables all point at the same numbers.

</td>
</tr>
</table>

## 🏗 Architecture

Five layers on one loop: observe → decide → act.

```mermaid
flowchart TB
    subgraph L5["L5 · Observe & Operate"]
      direction LR
      lmd["lmd-top<br/><sub>operations console</sub>"] ~~~ bench["rm-bench<br/><sub>load & KPI measurement</sub>"]
    end
    subgraph L4["L4 · Cluster & Placement"]
      llmd["llm-d-setup<br/><sub>Gateway · InferencePool · EPP · model store · monitoring</sub>"]
    end
    subgraph L3["L3 · Execute & Serve"]
      direction LR
      pd["rngd-pd<br/><sub>RNGD prefill + ATOM decode</sub>"] ~~~ lora["npu-lora<br/><sub>training on NPUs</sub>"]
    end
    subgraph L2["L2 · Memory & Transport"]
      direction LR
      p2p["hetero-npu-p2p<br/><sub>NPU↔NPU KV</sub>"] ~~~ off["npu-offload<br/><sub>NPU↔host</sub>"] ~~~ duet["duet<br/><sub>CPU↔GPU unified memory</sub>"]
    end
    subgraph L1["L1 · Accelerator Abstraction"]
      rma["rm_abstract_layer<br/><sub>device discovery · AcceleratorProfile</sub>"]
    end

    L1 -- "Accelerator" --> L4
    L4 -- "Placement (where, over which KV path)" --> L3
    L3 -- "KVTransport (chosen by name)" --> L2
    L3 -. "airm_* metrics" .-> L5
    L2 -. "airm_* metrics" .-> L5
    L5 -. "observations" .-> L4

    classDef l5 fill:#fdf2f8,stroke:#f472b6,color:#831843
    classDef l4 fill:#fffbeb,stroke:#fbbf24,color:#78350f
    classDef l3 fill:#ecfdf5,stroke:#34d399,color:#064e3b
    classDef l2 fill:#ecfeff,stroke:#22d3ee,color:#164e63
    classDef l1 fill:#f5f3ff,stroke:#7c5cff,color:#3b0764
    class lmd,bench l5
    class llmd l4
    class pd,lora l3
    class p2p,off,duet l2
    class rma l1
```

Request flow and design principles: [docs/architecture.md](docs/architecture.md).

## 📦 Components

| | Layer | Component | Kind | Role | Maturity |
|:-:|---|---|---|---|---|
| 🟣 | L1 | [rm_abstract_layer](https://github.com/ai-computing/rm_abstract_layer) | library | Heterogeneous accelerator abstraction, device discovery, `AcceleratorProfile` publishing | ![prototype](https://img.shields.io/badge/-prototype-blue) |
| 🔵 | L2 | hetero-npu-p2p | library | Same-host KV transfer between NPUs of different vendors (completion-fenced) | ![experimental](https://img.shields.io/badge/-experimental-orange) |
| 🔵 | L2 | npu-offload | service | MoE expert offloading (hot experts in NPU HBM, cold experts on the host CPU) | ![prototype](https://img.shields.io/badge/-prototype-blue) |
| 🔵 | L2 | duet | library | Cooperative CPU+GPU vector search on GB10 unified memory | ![prototype](https://img.shields.io/badge/-prototype-blue) |
| 🟢 | L3 | rngd-pd | service | Prefill/decode-disaggregated serving: RNGD prefill + ATOM decode as llm-d pods | ![experimental](https://img.shields.io/badge/-experimental-orange) |
| 🟢 | L3 | npu-lora | workload | LoRA and full fine-tuning on inference-only NPUs | ![prototype](https://img.shields.io/badge/-prototype-blue) |
| 🟡 | L4 | llm-d-setup | cluster | Heterogeneous k8s + llm-d cluster, EPP, monitoring stack | ![prototype](https://img.shields.io/badge/-prototype-blue) |
| 🩷 | L5 | lmd-top | tool | Observability and operations console for llm-d clusters (TUI) | ![prototype](https://img.shields.io/badge/-prototype-blue) |
| 🩷 | L5 | rm-bench | tool | Trace replay and synthetic load; TTFT/TPOT/E2E measurement | ![prototype](https://img.shields.io/badge/-prototype-blue) |

> [!NOTE]
> Component repositories are private and included as submodules under `components/<layer>/<repo>`;
> only members of the ai-computing organization can fetch them. Each repository declares its layer,
> install, test and deployment steps in an [`ai-rm.yaml`](docs/component-contract.md) at its root.

## 🚀 Quick start

```bash
git clone --recursive https://github.com/ai-computing/ai-rm.git && cd ai-rm
make doctor     # check prerequisites
make list       # components · layers · versions · deployability
make setup      # install everything (LAYER=l2-memory for one layer)
make test       # quick tests that need no accelerator
make check      # scan for internal IPs, tokens and keys
```

<details>
<summary><b>Deploy to Kubernetes</b></summary>

```bash
mkdir -p deploy/clusters/local
cp deploy/clusters/example/cluster.example.env deploy/clusters/local/cluster.local.env
$EDITOR deploy/clusters/local/cluster.local.env          # site values (never tracked)
make deploy CLUSTER=local DRY_RUN=1                       # review what will be applied
make deploy CLUSTER=local LAYER=l3-serving                # deploy one layer
```

Applies each component's `deploy.chart` / `deploy.manifests`. See [deploy/README.md](deploy/README.md).
</details>

<details>
<summary><b>All <code>make</code> targets</b></summary>

| Target | What it does |
|---|---|
| `make init` | Fetch submodules |
| `make list [LAYER=…]` | Components, layer, kind, maturity, version, deployment target |
| `make doctor` | git · python · kubectl · helm · cargo · docker, missing submodules, site settings |
| `make setup [LAYER=…] [COMPONENTS=…]` | Run each `ai-rm.yaml` `install` step |
| `make test [LAYER=…]` | Run each `ai-rm.yaml` `test` step |
| `make deploy CLUSTER=… [DRY_RUN=1]` | Apply manifests / charts |
| `make check` | Sensitive-data scan over ai-rm and every fetched component |
| `make bump COMPONENT=…` | Move a component to its latest commit (commit ai-rm to pin it) |
</details>

## 🔌 How it connects

Components implement an rm-core contract, register it as an entry point, and are selected **by name** at runtime.

```toml
# hetero-npu-p2p/pyproject.toml
[project.entry-points."airm.kv_transports"]
p2p = "hetero_p2p.airm:P2PTransport"
```

```python
from rm_core import registry
transport = registry.load("airm.kv_transports", "p2p")   # config: kvTransport: p2p | shm | loopback
```

```bash
python -m rm_core.conformance        # contract checks for every installed implementation (PASS / SKIP / FAIL)
```

| Contract | Entry-point group | Layer |
|---|---|---|
| `AcceleratorProvider` | `airm.accelerator_providers` | L1 |
| `KVTransport` | `airm.kv_transports` | L2 |
| `Placement` | `airm.placements` | L4 |
| workload runner | `airm.workloads` | L3 |
| Metrics (`airm_*`) | — | all |

## 📚 Docs

| Document | Contents |
|---|---|
| [rm-core PROTOCOL.md](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md) | Normative definition of the contracts (v0.1) |
| [architecture.md](docs/architecture.md) | Layers, request flow, repository principles |
| [interfaces.md](docs/interfaces.md) | Contract summary, mapping to existing code, shared metrics |
| [integration-guide.md](docs/integration-guide.md) | How to connect a component (adapter · entry point · metrics · Helm) |
| [components/](docs/components/) | Per-repository integration cards |
| [component-contract.md](docs/component-contract.md) | `ai-rm.yaml` schema |
| [kpi-map.md](docs/kpi-map.md) | Project KPIs ↔ layers and components |
| [security.md](docs/security.md) | Rules and checks for a public repository |

> The design documents under `docs/` are currently written in Korean.

## 🗺 Roadmap

- [x] Layered structure · submodules · setup tooling (`make list/setup/test/deploy/check`)
- [x] rm-core v0.1 contracts · reference implementations · conformance checks · `AcceleratorProfile` CRD
- [ ] Component adapters for protocol v0.1 — in review
- [ ] Umbrella Helm chart + simulated cluster (`make up-sim`) + end-to-end scenario
- [ ] Placement controller and EPP scorer — choose P:D ratio and KV path from live observations
- [ ] MFU · power efficiency · SLO computed automatically from every end-to-end run
- [ ] Protocol v0.2 — bind live buffers (`MemoryRegion`) to KV transfers

## 🔒 Security

This repository is public. It never contains internal addresses, credentials or unpublished
performance numbers, and every push is [scanned automatically](.github/workflows/check-sensitive.yml).
Site values live only in the untracked `cluster.local.env` — see [docs/security.md](docs/security.md).

## 📄 License

BSD-3-Clause. Each component is licensed under the terms of its own repository.

<div align="center"><sub>Built by the ai-computing team · ETRI</sub></div>
