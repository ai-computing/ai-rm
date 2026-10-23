# Component contract

[Documentation](README.md) · [한국어](ko/component-contract.md)

Every integrated component declares its installation, test and deployment metadata in a root-level `ai-rm.yaml`. The umbrella dispatcher reads this file; [rm-core](https://github.com/ai-computing/rm-core) defines the runtime contracts.

The [Optimus Prime architecture registry](../config/engine-integration.yaml) is separate from a component manifest. It is a non-executable migration plan. FASOP and the runtime share the `aicomp` source repository; do not create two submodule clones or pretend that planned adapters already provide install/deploy commands. Actual engine metadata is added only when implemented, reviewed and pinned. See [cutover criteria](engine-integration.md).

## Manifest example

```yaml
name: hetero-npu-p2p
layer: l2-memory              # l1-accel | l2-memory | l3-serving | l4-cluster | l5-ops
kind: library                 # library | service | workload | cluster | tool
summary: KV transfer between compatible same-host NPUs
maturity: experimental        # experimental | prototype | stable
hardware: [RNGD, ATOM]
install:
  - python -m pip install -e .
test:
  - PYTHONPATH=src python -m unittest discover -s tests
deploy:
  target: llm-d               # llm-d | k8s | none
  manifests: null             # manifest / Kustomize directory; null if absent
  image: null
config:
  env_example: cluster.example.env
interfaces:
  provides: [KVTransport]
  uses: [Accelerator, Metrics]
kpi: [power-efficiency, SLO]
protocol: "0.1"
adapters:
  - group: airm.kv_transports
    name: p2p
metrics: [kv_transfer_ms, kv_transfer_gbps]
```

This is a contract example, not evidence that the named component already contains every field or passes every check. `deploy.chart` identifies a Helm chart. When any selected component declares it, the umbrella deploy command stops before applying any manifests and prints a `helm upgrade --install` command. Supply the serving namespace and site values shown as placeholders; `--dry-run` adds Helm's client dry run. Components without a chart continue to use `deploy.manifests` through kubectl.

## Required component README information

Include an `## ai-rm` section covering the layer and role, how it integrates with Kubernetes + llm-d, missing integration pieces, install/test commands, provided and consumed interfaces, related KPIs and required local configuration keys.

## Configuration boundary

- Keep node/gateway addresses and credentials out of tracked code, documentation and manifests.
- Document configuration keys in an example file with placeholders; put actual values in untracked `cluster.local.env`.
- Fail clearly on missing required settings. Do not hide a site-specific address in a default.
- Use `<gateway-host>` or RFC 5737 documentation addresses such as `192.0.2.x` for examples.
- Run the [sensitive-data checks](security.md) before publication.

## Version boundary

Tag meaningful library changes and pin exact component commits in AI-RM. `make bump COMPONENT=<name>` stages a pointer update; review and commit the resulting integration change. A new pointer must not imply validation that was not performed.
