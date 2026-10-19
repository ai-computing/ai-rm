# Deployment boundary

[Documentation](../docs/README.md) · [한국어](README.ko.md)

AI-RM targets Kubernetes + llm-d. `hetero-llm-d` owns cluster setup, Gateway/EPP, model storage and monitoring. Other current components declare manifests for that environment where implemented.

**Optimus Prime transition:** the [engine/FASOP design](../docs/engine-integration.md) and [planning registry](../config/engine-integration.yaml) describe a future consolidated engine. They do not deploy it, create its branch or activate new adapters. Existing component sources remain the current deployment path until acceptance and an engine revision is pinned.

## Site layout

```text
deploy/clusters/
├── example/                    # tracked keys and placeholders
│   └── cluster.example.env
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

## Current dispatcher behavior

- Reads each fetched component's `ai-rm.yaml` / `deploy.manifests`.
- Applies it with `kubectl apply -f`, or `-k` when a `kustomization.yaml` is present.
- Prefers a site overlay at `deploy/clusters/<name>/<component>/` and applies it with Kustomize.
- Passes `cluster.local.env` values in the command environment; does not automatically template arbitrary YAML.
- Uses `--dry-run=client` when requested. A usable Kubernetes context/discovery setup may still be needed; dry run is not deployment validation.
- Skips components without manifests. `deploy.chart` alone does not invoke Helm.

Inspect `python3 tools/airm.py list` and the component README for the actual deployment assets at the pinned revision. A planned umbrella chart, simulation target or FASOP-driven controller is not provided by this documentation change.
