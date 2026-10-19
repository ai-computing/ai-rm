# Getting started

[Documentation](README.md) · [한국어](ko/getting-started.md)

**Transition scope:** these commands use existing pinned component sources. The [Optimus Prime + FASOP plan](engine-integration.md) is not an active runtime: the proposed branch is uncreated, and the planning YAML is not consumed by this CLI.

## 1. Choose your scope

| Scope | Requires | Does not establish |
|---|---|---|
| Read docs / inspect the umbrella | Git; Python for CLI inspection | Component installation or hardware support |
| Fetch selected public components | Git and network access | Component runtime readiness |
| Install / test components | Python 3.8+, PyYAML and each component's prerequisites | That skipped hardware paths passed |
| Deploy into a cluster | Authorized kubeconfig, kubectl, component manifests; Helm where required | End-to-end validation from a dry run alone |
| Include `duet` | Explicit access to its private repository and its prerequisites | Public availability of that implementation |

The shell examples below target Linux / Bash. On Windows, `python` can replace `python3` when it names the correct interpreter; run component setup in its supported Linux/WSL environment. Bash continuations, `mkdir -p` and Make are not native PowerShell syntax.

## 2. Clone the umbrella

```bash
git clone https://github.com/ai-computing/ai-rm.git
cd ai-rm
python3 tools/airm.py list
python3 tools/check_sensitive.py .
```

Do not add `--recursive` for a public-only checkout: it also attempts private `duet`.

## 3. Initialize selected components

```bash
git submodule update --init -- \
  components/l1-accel/rm-accel \
  components/l2-memory/hetero-npu-p2p \
  components/l2-memory/npu-offload \
  components/l3-serving/rngd-pd \
  components/l3-serving/npu-train \
  components/l4-cluster/hetero-llm-d \
  components/l5-ops/lmd-top
```

The list includes the public, sanitized `lmd-top` export. See [history migration notes](status.md) if you have a checkout from before its cleanup.

Only members with access to private `duet` should initialize it:

```bash
git submodule update --init -- components/l2-memory/duet
```

These commands fetch the **pinned** revisions. Do not use `--remote` unless intentionally updating and reviewing the integration combination.

## 4. Inspect requirements, then install and test

```bash
python3 -m pip install PyYAML
python3 tools/airm.py doctor
python3 tools/airm.py list
python3 tools/airm.py setup --layer l3-serving
python3 tools/airm.py test --layer l3-serving
```

`doctor` looks for Git, Python, kubectl, Helm, Cargo and Docker. Missing optional tools are reported; its exit status is not a comprehensive readiness guarantee. Each component may require additional vendor drivers, SDKs, model access or build tools.

The current dispatcher skips unfetched components. A fetched component without `ai-rm.yaml` has no declared install/test steps; zero steps is **not** a passed component test. Check the manifest and component README before interpreting the output.

For selected components, call the Python CLI directly. **`make setup` depends on `make init`, which fetches every submodule even when a layer filter is provided.** It therefore requires private `duet` access.

## 5. Prepare site configuration

```bash
mkdir -p deploy/clusters/local
cp deploy/clusters/example/cluster.example.env deploy/clusters/local/cluster.local.env
```

Edit the untracked file with the authorized site's values. Review your kubeconfig context before any deploy operation. The CLI passes environment values to `kubectl`; it does not automatically substitute them into arbitrary YAML.

```bash
python3 tools/airm.py deploy --cluster local --dry-run --layer l3-serving
```

The current dispatcher applies `deploy.manifests` with `kubectl apply`; a site overlay at `deploy/clusters/<name>/<component>/` takes precedence and uses Kustomize. A `deploy.chart` field alone does not make the current CLI invoke Helm. Missing manifests cause a skip. Client dry run may still need a usable Kubernetes context/discovery setup.

After reviewing the actual resources and the selected cluster, omit `--dry-run` only when you intend to apply them. See [deployment](../deploy/README.md).

## 6. Try the stack on a simulated cluster

No accelerator or site cluster needed: Docker, [kind](https://kind.sigs.k8s.io/), kubectl and Helm on Linux (or
WSL with Docker). The umbrella chart runs with rm-core's `sim` accelerators and a fake OpenAI-compatible PD pool.

```bash
git submodule update --init components/l1-accel/rm-accel
python3 -m pip install PyYAML -e packages/rm-controller -e packages/rm-bench
make e2e-sim NO_CLUSTER=1   # placement + rm-bench in-process (no Docker): a quick first check
make up-sim                 # kind cluster airm-sim with charts/ai-rm
make e2e-sim                # AcceleratorProfiles -> rm-controller -> airm-placement, rm-bench pd-smoke
make down-sim
```

On a real cluster the same chart installs with site values; see [deployment](../deploy/README.md#umbrella-chart).

## Troubleshooting

| Symptom | Check |
|---|---|
| Recursive clone fails on `duet` | Clone without recursion and initialize the explicit public paths above. |
| A component says `not fetched` | Initialize its submodule; check repository permissions. |
| `PyYAML is required` | Install PyYAML in the interpreter environment running `airm.py`. |
| A command reports zero steps | Inspect the component's `ai-rm.yaml`; absence of steps is not validation. |
| Deployment says `no manifests` | The pinned component has no `deploy.manifests`; check its README and work card. |
| P2P is unsupported | Verify same-host devices, ABI and declared support; select host staging explicitly if appropriate. |
| Conformance skips hardware | Record SKIP and the reason; it is not a hardware PASS. |
| `make up-sim` says `missing tools` or rm-accel has no Dockerfile | Install Docker, kind, kubectl, Helm; fetch `components/l1-accel/rm-accel` at the pinned revision. |

Next: [architecture](architecture.md), [integration guide](integration-guide.md), [status](status.md).
