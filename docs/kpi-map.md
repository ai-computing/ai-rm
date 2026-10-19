# KPI map and research evidence

[Documentation](README.md) · [한국어](ko/kpi-map.md)

This map connects the project's research areas to components and measurement definitions. **Unreleased numerical results and project evidence files are not published here.** Their designated records remain in private research tracking, MLflow and project evidence storage.

Under the [Optimus Prime consolidation plan](engine-integration.md), PD/KV/offload execution results will identify the accepted engine revision plus module provenance. FASOP estimates are planner artifacts, not measured KPI attainment; keep training cost-search results separate from inference TTFT/TPOT/SLO and measure the actual engine/cluster path after cutover. Until then, the source mapping below applies to the pinned components.

| KPI area | Measurement / context | Main layers | Components | Evidence |
|---|---|---|---|---|
| Model FLOPs utilization | `mfu_pct` with peak provenance | L2, L3 | rngd-pd, hetero-npu-p2p | PD experiment run, workload/precision and peak basis |
| Power efficiency | `gflops_per_w`, `power_w`, energy scope/window | L3, L5 | rngd-pd, rm-bench, hetero-llm-d exporters | Measurement run and sampling boundaries |
| Heterogeneous resource coverage | Vendor/model coverage and `accelerators` | L1, L4 | rm-accel, hetero-llm-d | Device discovery, registration and allocation records |
| SLO attainment | `slo_attainment_pct`, TTFT / TPOT under a declared SLO | L4, L5 | hetero-llm-d, rm-bench, lmd-top | Load profile, concurrency and benchmark run |
| Memory integration | `kv_transfer_ms`, transfer bandwidth and workload comparison | L2 | hetero-npu-p2p, npu-offload, duet | Path-specific memory experiment |
| Scalability | Node/device count and workload behavior | L4 | hetero-llm-d | Cluster configuration and test conditions |
| Application services | Defined service count and configuration | L3, L4 | rngd-pd, npu-offload, hetero-llm-d | Serving configuration and execution record |

## What makes a result traceable?

![Device discovery, contract integration, execution and evidence](assets/research-workflow.svg)

Record the hub revision, component revisions, hardware and software versions, model and dataset, workload shape/concurrency, named transport, metric units and measurement window. Link the raw artifact and the comparison baseline. Record assumptions such as a substituted peak value used in an MFU denominator.

Use the common metric names from [interfaces](interfaces.md). Where installed, the research reporting helper can associate `--metric`, `--param` and `--artifact` with the task/run. The public map establishes the correspondence; it does not assert that a target value has been achieved.
