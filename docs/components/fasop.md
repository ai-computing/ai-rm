# FASOP · planning element inside Optimus Prime

[Component directory](README.md) · [한국어 설계](../ko/engine-integration.md) · [English design](../engine-integration.md)

**Source:** [`aicomp/fasop`](https://github.com/ai-computing/aicomp/tree/62a783114afa3531beeb7955c66da2e6aaf4ba65/fasop), in the same repository as the Optimus Prime runtime. **Current scope:** cost-based TP/PP/DP strategy search for Transformer training on heterogeneous GPU clusters. **Planned role:** inference planning adapter within the unified engine product, logically connected at L4.

## Implementation acceptance · future work

- [ ] Define inference workload profiles and device-capability inputs with their provenance.
- [ ] Calibrate prefill/decode, memory and communication costs; do not relabel training step costs as inference latency.
- [ ] Define a reviewed plan output mapped to rm-core's existing placement boundary, proposing protocol changes separately where required.
- [ ] Validate candidate plans against supported engine backends and memory/transport constraints.
- [ ] Implement a proposed `airm.placements` / `fasop` adapter only after its contract is reviewed.
- [ ] Compare estimates against actual TTFT/TPOT/throughput/SLO measurements from rm-bench.
- [ ] Keep plan generation separate from live cluster mutation; no automatic EPP reconfiguration is enabled by this plan.

The runtime and planner should use one source checkout, not duplicated submodules. [Registry](../../config/engine-integration.yaml) records the current source versus future scope.

**한국어:** FASOP은 Optimus Prime 제품 내부의 계획·탐색 요소입니다. 현재 학습 비용 모델과 추론용 모델·adapter를 구분하고, 추정값을 실측 KPI로 보고하지 않습니다.
