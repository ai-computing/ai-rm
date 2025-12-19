# AI Accelerator Resource Management System

A resource management and monitoring system for AI accelerators.

---

## Modules

| Module | Description |
|--------|-------------|
| [rm_monitor](rm_monitor/) | LLM inference monitoring stack (vLLM + Prometheus + Grafana + DCGM Exporter) |
| [rm_abstract_layer](rm_abstract_layer/) | Unified LLM inference abstraction layer for heterogeneous accelerators (GPU/NPU/CPU) |

---

## Key Features

### RM Monitor

- vLLM metrics collection (TTFT, TPOT, E2E, TPS)
- Prometheus + Grafana dashboard
- GPU power/utilization monitoring via DCGM Exporter
- Azure trace-based traffic replay tool

### RM Abstract Layer

- **Minimal Code Change**: Just change `from vllm import LLM` to `from rm_abstract import LLM`
- **Device Transparency**: vLLM-compatible API works on GPU and CPU
- **Runtime Switching**: Real-time switching between GPU and CPU
- **Multiple Serving Engines**: vLLM, Triton, TorchServe support
- **Plugin Architecture**: Easily add new resources and engines via plugin registry

---

## Getting Started

Each module has its own documentation:

- **RM Monitor**: See [rm_monitor/README.md](rm_monitor/README.md)
- **RM Abstract Layer**: See [rm_abstract_layer/README.md](rm_abstract_layer/README.md)

### Clone with Submodules

```bash
git clone --recursive https://github.com/ai-computing/ai-rm.git
cd ai-rm

# Or if already cloned without submodules:
git submodule update --init --recursive
```

---

## Repository Structure

```
.
├── rm_monitor/          # LLM inference monitoring stack (submodule)
├── rm_abstract_layer/   # Unified inference abstraction layer (submodule)
├── LICENSE
└── README.md
```

---

## License

This project is licensed under the BSD 3-Clause License - see the [LICENSE](LICENSE) file for details.
