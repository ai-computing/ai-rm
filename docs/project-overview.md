# Project overview

[Documentation](README.md) · [한국어](ko/project-overview.md)

## The problem

AI infrastructure increasingly combines accelerators with different execution backends, memory hierarchies and software interfaces. A device inventory alone does not explain where a workload should execute, how its state should move, or how to compare the result with another configuration.

AI-RM organizes this problem into five responsibilities: discover resources, move data, execute workloads, integrate the cluster and measure behavior. The target setting combines GPU, FuriosaAI RNGD, Rebellions ATOM, CPU and GB10 unified-memory research with Kubernetes + llm-d.

The engine direction is **Optimus Prime in `aicomp`**, including FASOP as its planner/search element. AI-RM remains the umbrella for resource/cluster integration and evidence. Existing inference source repositories are retained during the planned consolidation; no source migration is implemented here. See the [engine design](engine-integration.md).

## What this repository delivers

| Artifact | Why it exists |
|---|---|
| Layered architecture | Give each technology a defined responsibility and integration point. |
| Interface guides and component cards | Align implementations with rm-core's shared contracts. |
| Git submodule pointers | Record the exact component revisions associated with a hub revision. |
| `tools/airm.py` and Make targets | Discover component manifests and dispatch installation, tests and manifest deployment. |
| Public documentation and diagrams | Explain the project without requiring cluster or private research access. |
| KPI mapping | Connect research areas to measurement definitions and evidence locations. |

This is an umbrella integration repository. Device kernels, model execution logic, transport implementations and operator interfaces remain in their component repositories. Public access is described in [status](status.md); `duet` remains a private, optional component.

## The research questions

1. Can a shared device model describe the capabilities needed by heterogeneous workload placement?
2. Which explicit data path fits KV transfer, MoE expert offload or unified-memory search?
3. How should prefill, decode and training connect to the cluster runtime?
4. How can latency, throughput, power and SLO measurements remain comparable and traceable?

See [research scenarios](research-scenarios.md) and the [KPI map](kpi-map.md). The project description is a research scope, not a certification of hardware support, production readiness or performance gains.

## Hardware context

![Generic accelerator boards, a CPU motherboard and a compact compute system on a laboratory workbench](assets/hardware-workbench.png)
*AI-generated generic hardware illustration. The objects are not product-identification references or a record of project equipment. GPU/NPU models and supported configurations must be verified against each component's documentation.*

| Resource family | Role in the project |
|---|---|
| GPUs | Reference and heterogeneous execution backends. |
| FuriosaAI RNGD | NPU execution, prefill, expert offload and training research. |
| Rebellions ATOM | NPU decode and heterogeneous KV-transfer research. |
| CPU / host DRAM | Host computation, staging and memory-tier research. |
| GB10 unified memory | CPU–GPU cooperative vector-search research through private `duet`. |

Follow [architecture](architecture.md) for the logical design and [status](status.md) for the limits of the public integration snapshot.
