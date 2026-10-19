# Shared interfaces

[Documentation](README.md) · [한국어](ko/interfaces.md)

**Normative definitions live in [rm-core](https://github.com/ai-computing/rm-core)**: [PROTOCOL.md](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md), `src/rm_core` types and `python -m rm_core.conformance`. This page summarizes integration responsibilities; follow the pinned rm-core protocol for exact signatures and validation rules.

## Optimus Prime target boundary

Inference execution, backend-specific PD, KV integration and expert offload are planned to share the Optimus Prime runtime owner. Resource discovery, cluster routing and observations remain hub-facing contracts. FASOP belongs to the same engine product but connects through the placement boundary, rather than replacing EPP.

The [integration plan](engine-integration.md) proposes `airm.workloads` / `optimus-prime` and `airm.placements` / `fasop` adapters. They are **not registered implementations** and introduce no new normative protocol group. Existing source adapters remain the executable path until cutover. FASOP's current training-search output requires an inference-specific model and explicit validation before it can become a placement proposal.

| Contract | Entry-point group | Responsibility | Integration target |
|---|---|---|---|
| `Accelerator` / `AcceleratorProvider` | `airm.accelerator_providers` | Describe and discover devices, memory, precision, peak provenance, power and interconnect | rm_abstract_layer |
| `AcceleratorProfile` | — | Publish capabilities through Kubernetes CRDs and `airm.ai-computing.io/<vendor>.<model>` node labels | rm-core Kubernetes helpers and L1 daemon |
| `MemoryTier` / `KVLayout` / `KVTransport` | `airm.kv_transports` | Describe KV movement and completion fences; select paths by name | hetero-npu-p2p; rngd-pd host staging |
| `Workload` / `Placement` | `airm.placements` | Describe what runs where, including its KV path | llm-d EPP integration and serving configuration |
| Workload runner | `airm.workloads` | Start serving, training or search workloads | rngd-pd, npu-offload, npu-lora, duet |
| `Measurement` / metrics | — | Common names, units and tags; Prometheus `airm_<name>` series | Benchmark tools, exporters and research records |

## Metrics used in the v0.1 integration guides

| Key | Unit | Meaning / required context |
|---|---|---|
| `ttft_p50_ms`, `ttft_p90_ms`, `ttft_p99_ms` | ms | Time to first token |
| `tpot_p50_ms`, `tpot_p90_ms`, `tpot_p99_ms` | ms | Time per output token |
| `e2e_p90_ms` | ms | End-to-end request latency |
| `tok_s`, `req_s` | tokens/s, requests/s | Throughput |
| `power_w`, `energy_j` | W, J | Power and energy; power includes `scope=card` or `scope=node` |
| `gflops_per_w` | GFLOPS/W | Power efficiency; record the operation/precision basis |
| `mfu_pct` | % | Model FLOPs utilization; record `peak_source` |
| `kv_transfer_ms`, `kv_transfer_gbps` | ms, GB/s | KV transfer; record `kv_transport` |
| `accuracy_pct` | % | Task accuracy; record `dataset` |
| `slo_attainment_pct` | % | Attainment under the stated SLO and workload |
| `accelerators` | count | Device count; record `vendor` and `model` |

Validate names, units and tags against rm-core's `METRICS` / `TAG_KEYS`. Request new metrics in rm-core before introducing component-specific alternatives. Research reports and dashboard exporters should use the same definitions.

## Integration invariants

- Choose transport and placement implementations by registered name.
- Do not silently replace a failed transport with another data path.
- A transport completion fence must complete before the receiver consumes the transferred KV.
- Keep benchmark provenance: hub/component revisions, selected path, hardware, workload and measurement scope.
- Record hardware-dependent conformance SKIP explicitly.

Continue with the [integration guide](integration-guide.md) and [component cards](components/README.md).
