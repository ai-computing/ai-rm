# Research scenarios

[Documentation](README.md) · [한국어](ko/research-scenarios.md)

These scenarios explain why the components belong in the same project. They are **research and integration scenarios**, not a claim that every combination is validated. Follow each component's supported hardware, model and ABI constraints.

The [target owner](engine-integration.md) for inference execution, PD, KV integration and expert offload is Optimus Prime in `aicomp`; current repositories below are migration sources. FASOP is a planning element inside that product. Its existing training estimates require a separate inference model before planning these serving scenarios. Private duet remains an external search workload.

## 1. Split prefill and decode across NPUs

**Question:** how can different accelerator backends cooperate on the stages of an LLM request?

The `rngd-pd` scenario uses RNGD prefill and ATOM decode. A selected transport moves KV state; `hetero-npu-p2p` studies a completion-fenced same-host path, while the `shm` path uses host staging. Kubernetes + llm-d provides the serving integration environment.

![Target consolidated Optimus Prime prefill/decode flow; source backend migration remains planned](assets/request-flow.svg)

Evaluate TTFT, TPOT, throughput, KV transfer time and SLO attainment under a fixed workload. Record the exact selected path and hardware/ABI; do not attribute host-staging results to P2P.

## 2. Execute MoE experts across NPU and host

**Question:** how can a workload use host resources when expert working sets exceed a preferred device tier?

`npu-offload` keeps hot experts in NPU HBM and executes cold experts on the host CPU. This is a workload/memory-tier integration, not an interchangeable KV-transfer implementation. Evaluate throughput, token latency and power where measurement is available, with the offload policy and model held explicit.

## 3. Combine CPU and GPU work in unified memory

**Question:** which parts of vector search should run on CPU and GPU when they share memory?

Private optional `duet` studies GB10 vector search with CPU graph traversal and GPU distance computation. Evaluate request throughput, latency and task accuracy with the dataset and search configuration recorded. The public hub explains the role without making the private implementation available.

![Generic accelerator and compute workbench](assets/hardware-workbench.png)
*AI-generated generic hardware illustration, not a deployment photograph or a product diagram.*

## 4. Connect NPU training to the same resource vocabulary

`npu-lora` studies LoRA/full fine-tuning on inference-oriented NPUs, with backend-specific execution and reference comparisons. The integration targets a workload runner and Kubernetes Job configuration. Record training throughput and task accuracy, including dataset and backend; verify supported combinations in the component repository.

## 5. Observe, load and compare

`llm-d-setup` supplies the cluster/monitoring integration, `lmd-top` provides an operator view, and `rm-bench` supplies replay/synthetic load and measurements. Shared metric definitions allow a benchmark result and an operator view to refer to the same quantities.

Use the [KPI map](kpi-map.md) for measurement mapping, [interfaces](interfaces.md) for units and [status](status.md) for integration boundaries.
