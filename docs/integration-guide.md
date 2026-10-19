# Component integration guide · protocol v0.1

[Documentation](README.md) · [한국어](ko/integration-guide.md)

Use [rm-core PROTOCOL.md](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md) for the contract and the relevant [component card](components/README.md) for the task. The cards describe requested integration work; verify implementation and conformance at the pinned revision.

**Consolidation direction:** use the [Optimus Prime plan](engine-integration.md) and [registry](../config/engine-integration.yaml) before adding engine-facing functionality. Target a single runtime owner in `aicomp/opt_prime` with FASOP in `aicomp/fasop`. Source-repository adapters below remain transition contracts; do not build a new independent inference engine in each source repository. This documentation does not activate the planned engine or create its branch.

![Discover, connect, execute and measure](assets/research-workflow.svg)

## Adapter model

A component adds a small adapter around its existing implementation and registers it through an entry point. Components do not import or copy each other's internal implementation. Runtime configuration selects names such as `p2p` or `shm`; changing a path must remain explicit.

| Layer | Integration surface |
|---|---|
| L1 | `AcceleratorProvider` → Kubernetes device profile and labels |
| L2 | `KVTransport`, or workload/memory-tier declarations for non-KV paths |
| L3 | Workload runner; named transport selection |
| L4 | Device-profile consumption and placement integration points |
| L5 | Shared `airm_*` metrics and validated measurements |

## Implementation sequence

1. Work on a component branch such as `airm/v0.1` and submit a PR. Keep commits scoped to your paths.
2. Add a pinned rm-core dependency where a Python adapter is used. For Rust/C++ or manifest-only components, follow the data formats or add a thin Python adapter as specified in the component card.
3. Wrap existing logic in `airm.py` or an `airm/` package. Preserve kernels, algorithms and active experiment paths.
4. Implement hardware-dependent `conformance_case()` support. If the hardware/ABI is unavailable, report `NoHardware`; do not substitute another backend silently.
5. Register the adapter and use common metrics.
6. Add the component's deployment assets where applicable and update `ai-rm.yaml`.
7. Run conformance, existing tests and the sensitive-data scanner; record PASS/SKIP with reasons in the PR.

```toml
# Example dependency and transport entry point
dependencies = ["rm-core @ git+https://github.com/ai-computing/rm-core@v0.1.0"]

[project.entry-points."airm.kv_transports"]
p2p = "hetero_p2p.airm:P2PTransport"
```

Confirm that the referenced protocol tag exists and matches your component's integration target before installing. The example is an integration convention, not a statement that every component already uses it.

```yaml
protocol: "0.1"
adapters:
  - group: airm.kv_transports
    name: p2p
metrics: [kv_transfer_ms, kv_transfer_gbps]
```

## Deployment asset conventions

Component charts, where implemented, use `deploy/helm/<component>/` with `Chart.yaml`, `values.yaml` and `templates/`. Keep site values outside the tracked chart.

```yaml
enabled: true
image: {repository: "", tag: ""}
airm:
  kvTransport: ""
  placement: ""
  metricsPort: 9400
nodeAffinity: {}
resources: {}
```

- Select nodes with `airm.ai-computing.io/<vendor>.<model>` labels rather than site addresses.
- Use `airm.ai-computing.io/scrape: "true"` where the monitoring setup supports that annotation.
- Put local overrides under untracked `deploy/clusters/<name>/`.
- **Current umbrella CLI behavior:** only `deploy.manifests` is dispatched through `kubectl apply`. `deploy.chart` is metadata; it does not trigger Helm automatically. A combined umbrella chart, simulation target and compatibility registry are future integration work, not commands available in this checkout.

## Validation and review

```bash
python -m pip install -e .
python -m rm_core.conformance
# Run the component's existing tests using its documented command.
python3 .research/check_sensitive.py .
```

The scanner path above applies where the component has the research helper; the umbrella equivalent is `python3 tools/check_sensitive.py .`. A component PR should include adapter names, the wrapped implementation, emitted metrics, conformance output and card completion evidence. Hardware SKIP is not hardware PASS.

After merge, maintainers may advance the umbrella submodule pointer using `make bump COMPONENT=<name>` and review the actual combined behavior. Do not describe unrun integration scenarios as validated.
