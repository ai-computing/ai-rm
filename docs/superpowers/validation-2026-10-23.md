# Ecosystem safety validation — 2026-10-23

The fixes follow the [implementation plan](plans/2026-10-23-ecosystem-safety.md). No live rollout was performed.

| Repository / scope | Verification | Result |
|---|---|---|
| ai-rm tools, rm-controller, rm-bench | Combined pytest with explicit worktree imports and real Helm | **222 passed**, no skips |
| ai-rm umbrella chart | Dependency built from pinned rm-accel; strict lint for default, sim and example site; full template for all three with `controller.apply=true` | PASS |
| Onggi | Go 1.24.13 vet, full race suite with local VersityGW S3, CLI build and byte-identical base/delta restore | **113 test cases passed**, no skipped test cases |
| hetero-npu-p2p | Linux unittest suite, including compiled native fault injection | **149 passed**, 6 hardware skips |
| hetero-llm-d | Placement/EPP, installer, model-store discovery, EPP configs, Bash syntax | **22 passed** |
| ai-rm docs / sensitive-data / whitespace | Existing repository checkers and git diff check | PASS |

The final AI-RM run used Python 3.11, rm-core 0.1.2 and Helm 3.20.1. From the repository root:

```sh
export PYTHONPATH="$PWD/packages/rm-controller:$PWD/packages/rm-bench:$PWD/packages/rm-controller/tests:$PWD/packages/rm-bench/tests"
export HELM="$(command -v helm)"
python -m pytest -q --import-mode=importlib tools/tests packages/rm-controller/tests packages/rm-bench/tests
python tools/check_docs.py
python tools/check_sensitive.py .
```

Explicit paths avoid testing an unrelated editable installation. Importlib mode and test-directory paths avoid
pre-existing duplicate test-module names and sibling imports in the root suite. Package-local test runs work too.
The tools tests must run after Helm setup in CI so the chart regressions do not silently skip.

Regression tests were observed failing before their fixes. Independent review found two further benchmark gaps:
zero reported tokens contradicting nonempty output, and connection attempts exceeding one deadline across several
resolved addresses. Both now have regressions and fixes. A final independent review ran 61 targeted tests with no
new important finding. Controller option abbreviations were disabled so chart apply/namespace permission checks
cannot be bypassed with `--app` or `--namesp`.

## Published changes and integration boundary

- [onggi#67](https://github.com/ai-computing/onggi/pull/67): CSI lease ownership and bounded materializations, accurate P2/runtime documentation. This branch pins its reviewed commit `d0b16db`; merge that PR before the hub update. Its GitHub CI passed Go and both VersityGW/SeaweedFS S3 jobs.
- [hetero-npu-p2p#10](https://github.com/ai-computing/hetero-npu-p2p/pull/10): uncertain DMA quarantine, device identities and CUDA destination overlap. GitHub CI passed on Python 3.10 and 3.12. Existing hub pin unchanged.
- [hetero-llm-d#12](https://github.com/ai-computing/hetero-llm-d/pull/12): seed preservation and retrying partial KEDA updates. Existing hub pin unchanged.
- [organization profile#3](https://github.com/ai-computing/.github/pull/3): Onggi's role and runtime boundary. The organization short description was updated separately.

No NPU serving benchmark, privileged CSI mount or live Kubernetes patch was performed. P2P needs a vendor-header
build and real DMA validation, then an ABI 3 library/manifest rebuild before deployment. The native test harness
uses explicitly marked test UAPI stubs. rm-bench's live TLS/proxy paths were not exercised; DNS resolution remains
subject to the OS resolver. Onggi's compile/prefetch controllers, runtime metadata generation and UI/protocol
extensions remain future work, rather than inferred from artifact deduplication or file delta success.
