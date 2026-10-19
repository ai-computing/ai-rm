# Optimus Prime · unified engine target

[Component directory](README.md) · [Design / 한국어](../ko/engine-integration.md) · [English design](../engine-integration.md)

**Source:** [`ai-computing/aicomp`, `opt_prime/`](https://github.com/ai-computing/aicomp/tree/62a783114afa3531beeb7955c66da2e6aaf4ba65/opt_prime). **Planned branch:** `optimus-prime` (not created here). **Status:** architecture target; no active AI-RM engine submodule, manifest or adapter registration.

The runtime owns the planned consolidation of engine-facing backend adapters, PD serving, KV integration and expert offload. FASOP is a [planning element](fasop.md) of the same product. L1 resource discovery and L4/L5 cluster/operations responsibilities remain outside the runtime.

## Implementation acceptance · future work

- [ ] Create the implementation branch and preserve an exact reviewed source revision.
- [ ] Define module boundaries for current source technologies without changing their behavior by implication.
- [ ] Implement and test the engine workload adapter and manifest.
- [ ] Preserve explicit KV-path choice, completion fences and failure semantics.
- [ ] Validate supported backends, output correctness and existing scenarios on the actual hardware.
- [ ] Validate the llm-d serving boundary and common metric output.
- [ ] Include FASOP only through a documented, validated planning interface.
- [ ] Pin the accepted engine revision in AI-RM before retiring any legacy source pointer.

These are acceptance requirements, not completed work. [Planning configuration](../../config/engine-integration.yaml) is documentation and does not install or activate the engine.

**한국어:** 이번 작업은 통합 책임과 검증 기준만 정의합니다. 브랜치·엔진 코드·adapter는 구현 담당자가 후속 진행하며 기존 소스는 검증 완료까지 유지합니다.
