# Glossary

[Documentation](README.md) · [한국어](ko/glossary.md)

| Term | Meaning in AI-RM |
|---|---|
| Optimus Prime | Planned unified inference-engine owner in `aicomp`; current runtime source is `opt_prime/`. |
| FASOP | Planning/search element in the same product (`aicomp/fasop`); current training cost search is distinct from planned inference planning. |
| Integration plan | Non-executable ownership/migration registry; not the component manifest or a deployed runtime configuration. |
| Accelerator abstraction | Common device description/discovery boundary over hardware-specific implementations. |
| NPU | Neural processing unit; backend support depends on the vendor and component. |
| RNGD / ATOM | FuriosaAI / Rebellions accelerator families used in the project's heterogeneous NPU scenarios. |
| GB10 / unified memory | CPU–GPU system context used by the private `duet` search research. |
| HBM / host DRAM | Device-side high-bandwidth memory / host memory tiers. |
| Prefill / decode | Prompt processing / iterative token-generation stages of LLM inference. |
| PD disaggregation | Execute prefill and decode as separate serving stages. |
| KV cache | Attention key/value state reused during inference. |
| P2P / host staging | Direct peer transfer where supported / explicit transfer through host memory. |
| Completion fence | Synchronization boundary confirming that submitted transfer work has completed before consumption. |
| MoE / expert offload | Mixture of Experts / partition expert execution across device and host resources. |
| LoRA | Low-rank adaptation, one approach studied for parameter-efficient fine-tuning. |
| EPP / InferencePool | llm-d / Kubernetes inference-routing integration points; EPP is the Endpoint Picker extension. |
| TTFT / TPOT / E2E | Time to first token / time per output token / end-to-end request latency. |
| SLO | Service-level objective defined for a workload; attainment depends on the stated thresholds. |
| MFU | Model FLOPs utilization; interpretation requires precision and the source of peak capability. |
| Entry point / adapter | Named plugin registration / wrapper connecting an implementation to a shared contract. |
| Conformance SKIP | A check could not run under its required conditions; distinct from PASS. |
| Pinned submodule | Exact component commit recorded by the umbrella repository. |
