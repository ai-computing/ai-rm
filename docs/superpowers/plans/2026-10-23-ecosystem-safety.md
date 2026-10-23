# Ecosystem safety implementation plan

> **For agentic workers:** Use the test-driven-development and verification-before-completion skills for each independent repository.

**Goal:** Correct the confirmed measurement, deployment, placement and transfer failures, and document Onggi accurately.

**Architecture:** Keep fixes in the component that owns the behavior. Preserve existing protocols unless an unsafe native completion result requires an explicit ABI change. Publish reviewable branches; do not deploy to a live cluster.

**Tech stack:** Python, Go, C, Helm, Bash; existing dependencies only.

**Spec:** The preceding ecosystem review and the user's request to implement its improvements with verification.

## Constraints and review focus

- Existing provider sessions and their worktrees remain read-only.
- Missing timing cannot establish SLO success; a continuously transmitting peer must still hit the request deadline.
- A successful Deployment patch must not suppress retrying a failed ScaledObject patch; newer generations stay protected.
- A DMA error without a completion fence must retain ownership and prevent recovery.
- A failed CSI lease acquisition must not pin an otherwise unused artifact. Concurrent distinct pulls must have a bounded working set.
- Documentation distinguishes published component capabilities, pinned hub revisions and future integration.

## Independent deliverables

- [x] `packages/rm-bench`: regress unknown TPOT and real HTTP drip deadlines; fix shared client/SLO logic; run all package tests.
- [x] `tools/airm.py`, controller chart: regress chart dispatch and apply-mode permissions; reject unsupported generic deployment safely and render least-privilege RBAC; run tools/controller tests and Helm checks.
- [x] `hetero-llm-d/scripts/airm-*`: regress seed preservation and partial placement retries; reconcile independently without generation rollback; run Python and shell checks.
- [x] `hetero-npu-p2p`: regress uncertain DMA, device identity mismatch and overlapping CUDA destinations; fix native/Python ownership together; run CPU suite and native fault harness.
- [x] `onggi/pkg/csi`: regress volume-record failure and distinct-digest concurrent pulls; preserve established leases and bound pulls; run Go tests, race checks, vet and build on Linux.
- [x] Update English/Korean hub and Onggi READMEs, component status, organization profile and short description. Check links and avoid claiming unverified NPU serving performance.
- [x] Review final diffs, rerun appropriate suites, commit and publish reviewable PRs with evidence and hardware limitations.
