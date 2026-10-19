# Integration status and access

[Documentation](README.md) · [한국어](ko/status.md)

This page distinguishes the architecture and integration plan from verified implementation. **A component being listed or fetched does not prove that its adapters, charts or end-to-end scenarios are complete.** Use the component manifest, work card and actual conformance output at the pinned revision.

## Optimus Prime transition

The target engine is **Optimus Prime in `aicomp`**, with `opt_prime` runtime and `fasop` planning/search in the same product. The inspected source is `main`; `optimus-prime` is a **proposed, uncreated integration branch**. Its target revision is null, the engine submodule is inactive, and proposed `optimus-prime`/`fasop` adapters are not registered. Existing submodules remain the current executable sources. See [design and acceptance](engine-integration.md) and [planning registry](../config/engine-integration.yaml).

FASOP currently models training costs on heterogeneous GPUs. Inference-specific calibration, NPU planning and a reviewed llm-d placement adapter remain future work. This documentation change does not test or activate them.

## Repository access · 2026-10-19

| Repository | Access |
|---|---|
| ai-rm | Public integration hub |
| rm-core | Public shared protocol repository |
| aicomp | Public source for Optimus Prime (`opt_prime`) and FASOP (`fasop`); not an active engine submodule yet |
| rm_abstract_layer | Public |
| hetero-npu-p2p | Public |
| npu-offload | Public |
| rngd-pd | Public |
| npu-lora | Public |
| llm-d-setup | Public |
| rm-bench | Public |
| lmd-top | Public; sanitized history export, see below |
| duet | **Private; optional**, access required |

Use explicit submodule paths for a public-only checkout. `git clone --recursive` and `make setup` both attempt private `duet`. [Getting started](getting-started.md) explains the alternatives.

## What the umbrella currently implements

| Area | What is present | Boundary |
|---|---|---|
| Layer organization | Five-layer submodule layout, integration and interface guides | Each component's behavior lives in its own repository |
| Component inspection | `list`, `doctor` and manifest discovery | A missing manifest may produce no steps; this is not a test PASS |
| Installation / quick tests | Dispatch component-declared `install` / `test` commands | Depends on fetched revisions and local prerequisites |
| Deployment | `kubectl apply` for `deploy.manifests`; local Kustomize overlay support | No automatic Helm invocation from `deploy.chart` |
| Interface integration | rm-core protocol and component work cards | Confirm adapter implementation/conformance per component |
| Publication checks | Tracked-file sensitive-data scanner and CI | Not a complete history audit or hardware validation |

## Work still requiring independent validation

Component adapters, device-profile publication, charts and metrics readers have their own work cards and acceptance criteria. A combined umbrella chart, simulation cluster command, automated placement controller and compatibility registry are integration directions, **not available capabilities demonstrated by this documentation update**.

Report PASS, FAIL and hardware SKIP separately. Preserve the actual component combination and test conditions with every result.

## Layout migration notes

The previous `rm_monitor` roles are split: the monitoring stack and Grafana dashboards belong to `llm-d-setup/monitoring/`, trace/load generation to `rm-bench`, and the operations console to `lmd-top`. The old `rm_monitor` repository is archived. `rm_abstract_layer` resides under `components/l1-accel/`.

## lmd-top public history export

The public `lmd-top` repository contains sanitized branches/tags. Its previous repository, including historical PRs and issues, is preserved privately as `lmd-top-private-history`. Internal-address text was replaced with documentation addresses; the historical terminal recording and compiled Python cache were omitted from the public history. The umbrella pointer is updated to the corresponding sanitized commit. Existing developers should use a fresh clone or carefully rebase onto the sanitized history; merging old history can reintroduce removed material. The private archive is not a component to publish.
