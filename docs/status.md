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
| rm-accel | Public |
| hetero-npu-p2p | Public |
| npu-offload | Public |
| rngd-pd | Public |
| npu-train | Public |
| hetero-llm-d | Public |
| rm-bench, rm-controller | In-tree under `packages/` (rm-bench moved here 2026-10-19; its old repository is archived) |
| lmd-top | Public; sanitized history export, see below |
| duet | **Private; optional**, access required |

Use explicit submodule paths for a public-only checkout. `git clone --recursive` and `make setup` both attempt private `duet`. [Getting started](getting-started.md) explains the alternatives.

## What the umbrella currently implements

| Area | What is present | Boundary |
|---|---|---|
| Layer organization | Five-layer submodule layout, integration and interface guides | Each component's behavior lives in its own repository |
| In-tree packages | `packages/rm-bench` (measurement, real-trace replay), `packages/rm-controller` (topology and optimal placement, P:D rebalancer, re-placement, `--apply`); CI runs their tests and contract checks | `optimal`, `--apply` and `--rebalance` run live on the RNGD+ATOM node ([baselines](baselines.md)); the rebalancer follows the mix but mis-sizes the donor role; ATOM prefill profile still an estimate |
| Component inspection | `list`, `doctor` and manifest discovery | A missing manifest may produce no steps; this is not a test PASS |
| Installation / quick tests | Dispatch component-declared `install` / `test` commands | Depends on fetched revisions and local prerequisites |
| Deployment | `kubectl apply` for `deploy.manifests`; local Kustomize overlay support | No automatic Helm invocation from `deploy.chart` |
| Interface integration | rm-core protocol and component work cards | Confirm adapter implementation/conformance per component |
| Publication checks | Tracked-file sensitive-data scanner and CI | Not a complete history audit or hardware validation |

## Protocol v0.1 integration · verified 2026-10-19

The v0.1 adapters were merged in every component and the submodules point at those merge commits. Verification
ran with every Python component installed in **one** environment (rm-core v0.1.1) on an RNGD + ATOM node, plus
component hosts where a check needs their environment.

| Component | Pinned | Adapter / role | Result |
|---|---|---|---|
| rm-accel | `c72f356` (0.4.1, chart 0.4.2) | `airm.accelerator_providers:rm-abstract` | Conformance PASS; 3 RNGD + 4 ATOM on etri-001, matching the device plugins. *Correction:* the first record here said 2 ATOM matched the vendor tools; it did not — `rbln-stat` numbering, fixed in 0.4.1 |
| hetero-npu-p2p | `9556e1a` | `airm.kv_transports:p2p` | 91 unit tests PASS; conformance **SKIP** (needs `HETERO_P2P_HELPER` and a live-buffer fixture) |
| npu-offload | `486d1e7` | `airm.workloads:npu-offload`, memory tiers | 6/6 tests PASS with `RNGD_LLMD`; chart renders and lints |
| rngd-pd | `83ba553` | `airm.kv_transports:shm`, `airm.workloads:rngd-pd` | `shm` conformance PASS; 44 tests PASS; chart renders and lints |
| npu-train | `f9b7bc5` | `airm.workloads:npu-lora`, `airm_tok_s` | Tests PASS; chart renders and lints |
| hetero-llm-d | `0f4f58e` | CRD, `airm_*` scrape, dashboard, placement ConfigMap | Server-side dry-run PASS on the live cluster |
| lmd-top | `73e07d7` | reads `AcceleratorProfile`, `airm_*`, placement | 447 + 11 cargo tests PASS, clippy clean |
| rm-bench | in-tree | `airm.workloads:rm-bench`, measurements, trace replay | 26 tests PASS |
| rm-controller | in-tree | `airm.placements:topology`, `airm.placements:optimal` | conformance PASS, 51 tests PASS |

The L1 → L5 wiring check passes through rm-core alone, and on 2026-10-19 the layers ran together on the live
cluster: L1 profiles placed rngd-pd's PD pods, requests went through the llm-d gateway and EPP, KV moved over
`shm`, and rm-bench and lmd-top measured and displayed the result — see the [end-to-end run](e2e.md) for numbers,
the fixes it produced and what remains (placement controller, P2P with live buffers, RNGD→ATOM decode).
Sensitive-data scans of every component tree are clean.

## Work still requiring independent validation

Component adapters, device-profile publication, charts and metrics readers have their own work cards and acceptance criteria. A combined umbrella chart, simulation cluster command, load-aware placement that serving pods follow, and a compatibility registry are integration directions, **not available capabilities**. The placement controller exists as a first version (dry-run verified on the cluster).

Report PASS, FAIL and hardware SKIP separately. Preserve the actual component combination and test conditions with every result.

## Layout migration notes

The previous `rm_monitor` roles are split: the monitoring stack and Grafana dashboards belong to `hetero-llm-d/monitoring/`, trace/load generation to `rm-bench`, and the operations console to `lmd-top`. The old `rm_monitor` repository is archived. `rm-accel` resides under `components/l1-accel/`.

## lmd-top public history export

The public `lmd-top` repository contains sanitized branches/tags. Its previous repository, including historical PRs and issues, is preserved privately as `lmd-top-private-history` (archived, read-only). Internal-address text was replaced with documentation addresses; the historical terminal recording and compiled Python cache were omitted from the public history. The umbrella pointer is updated to the corresponding sanitized commit. Existing developers should use a fresh clone or carefully rebase onto the sanitized history; merging old history can reintroduce removed material. The private archive is not a component to publish.
