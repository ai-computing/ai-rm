# Deployment boundary

[Documentation](../docs/README.md) · [한국어](README.ko.md)

AI-RM targets Kubernetes + llm-d. `hetero-llm-d` owns cluster setup, Gateway/EPP, model storage and monitoring. Other current components declare manifests for that environment where implemented.

**Optimus Prime transition:** the [engine/FASOP design](../docs/engine-integration.md) and [planning registry](../config/engine-integration.yaml) describe a future consolidated engine. They do not deploy it, create its branch or activate new adapters. Existing component sources remain the current deployment path until acceptance and an engine revision is pinned.

## Site layout

```text
deploy/clusters/
├── example/                    # tracked keys and placeholders
│   ├── cluster.example.env
│   ├── ai-rm.values.yaml       # umbrella chart site values
│   └── <component>.values.yaml # per-chart examples
└── <name>/                     # untracked actual site settings
    ├── cluster.local.env
    └── <component>/            # optional Kustomize overlay
```

```bash
mkdir -p deploy/clusters/local
cp deploy/clusters/example/cluster.example.env deploy/clusters/local/cluster.local.env
# Edit the untracked local file; review the intended kubeconfig context.
python3 tools/airm.py deploy --cluster local --dry-run --layer l3-serving
```

Review actual manifests and cluster selection before omitting `--dry-run` to apply them.

## Umbrella chart

[`charts/ai-rm`](../charts/ai-rm) installs the ai-rm control path with one `helm install`:

| Piece | Source | Resources |
|---|---|---|
| L1 node daemon | rm-accel chart `rm-abstract-node` (subchart, alias `node`, from the pinned submodule) | DaemonSet, ServiceAccount, ClusterRole; image `ghcr.io/ai-computing/rm-accel` |
| `AcceleratorProfile` CRD | rm-core v0.1.1 `k8s/`, copied to `charts/ai-rm/crds/` | CRD (installed first, never upgraded or deleted by Helm) |
| L4 rm-controller | [`packages/rm-controller`](../packages/rm-controller) | Deployment, ConfigMap with its spec (`controller.pools`), ClusterRole (profiles, nodes), Role (`airm-placement` only); image `ghcr.io/ai-computing/rm-controller` |
| `airm-placement` | hetero-llm-d `deploy/airm/README.md` format | ConfigMap with an empty v0.1 document, created only if missing and kept on upgrade/uninstall; rm-controller owns its contents |

```bash
git submodule update --init components/l1-accel/rm-accel
helm dependency update charts/ai-rm
mkdir -p deploy/clusters/local
cp deploy/clusters/example/ai-rm.values.yaml deploy/clusters/local/ai-rm.values.yaml   # edit pools, namespace
helm upgrade --install airm charts/ai-rm -n airm-system --create-namespace \
  -f deploy/clusters/local/ai-rm.values.yaml
make chart          # helm lint + template (default and sim values)
```

`placementNamespace` is where the EPP scorer and lmd-top read `airm-placement` (llm-d's namespace). If
hetero-llm-d's `airm-install.sh` already created the CRD or the ConfigMap, the chart leaves them as they are. The
node daemon needs no init container any more: the image carries rm-abstract, rm-core and the Kubernetes client, and
the host's vendor tools are mounted from `/usr/bin` (`node.hostBin`). Images are published by
`.github/workflows/rm-controller-image.yml` here and by rm-accel's `Image` workflow.

## Simulated cluster

The same chart runs on [kind](https://kind.sigs.k8s.io/) with rm-core's `sim` accelerator provider (one RNGD and
one ATOM per node, placeholder figures), images built from source, and
[`tools/fake_openai.py`](../tools/fake_openai.py) standing in for the PD pool. CI runs it on every pull request
(`.github/workflows/sim-e2e.yml`).

```bash
make up-sim         # kind cluster airm-sim (2 nodes), images built and loaded, charts/ai-rm + ci/sim-values.yaml
make e2e-sim        # rm-controller --once, airm-placement checked, rm-bench pd-smoke against the fake pool
make e2e-sim NO_CLUSTER=1   # the same checks in-process, no Docker or kind
make down-sim
```

`e2e-sim` passes when the profiles exist (2 per node), each pool in `charts/ai-rm/ci/sim-values.yaml` has a
prefill and a decode decision with cards of the requested kind on one node, the two pools use different nodes,
and `rm-bench` reports `slo_attainment_pct` 100 with no failed request (`results/sim-e2e.json`). It needs
Docker, kind, kubectl, Helm, and `pip install -e packages/rm-controller -e packages/rm-bench`. The simulation
checks the control path and the measurement path, not serving performance.

## Current dispatcher behavior

- Reads each fetched component's `ai-rm.yaml` / `deploy.manifests`.
- Applies it with `kubectl apply -f`, or `-k` when a `kustomization.yaml` is present.
- Prefers a site overlay at `deploy/clusters/<name>/<component>/` and applies it with Kustomize.
- Passes `cluster.local.env` values in the command environment; does not automatically template arbitrary YAML.
- Uses `--dry-run=client` when requested. A usable Kubernetes context/discovery setup may still be needed; dry run is not deployment validation.
- Skips components without manifests. `deploy.chart` alone does not invoke Helm; use the umbrella chart above.

Inspect `python3 tools/airm.py list` and the component README for the actual deployment assets at the pinned revision. A FASOP-driven controller is not provided.
