"""Render the controller chart with Helm; no Kubernetes API or submodule is needed."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

HELM = os.environ.get("HELM") or shutil.which("helm")
pytestmark = pytest.mark.skipif(not HELM, reason="requires Helm (or HELM=/path/to/helm)")
CHART = Path(__file__).resolve().parents[2] / "charts/ai-rm"


@pytest.fixture
def chart(tmp_path):
    dest = tmp_path / "ai-rm"
    shutil.copytree(CHART, dest)
    # Isolate controller templates from the unavailable node submodule dependency.
    metadata = yaml.safe_load((dest / "Chart.yaml").read_text(encoding="utf-8"))
    metadata.pop("dependencies", None)
    (dest / "Chart.yaml").write_text(yaml.safe_dump(metadata), encoding="utf-8")
    return dest


def render(chart, values):
    overrides = chart.parent / "site.yaml"
    overrides.write_text(yaml.safe_dump(values), encoding="utf-8")
    return subprocess.run([HELM, "template", "test", str(chart), "--namespace", "control",
                           "-f", str(overrides)], capture_output=True, text=True)


@pytest.mark.parametrize("controller, enabled", [({}, False), ({"apply": True}, True),
                                                     ({"extraArgs": ["--apply"]}, True),
                                                     ({"apply": True, "extraArgs": ["--apply"]}, True)])
@pytest.mark.parametrize("namespace", ["", "serving"])
def test_apply_argument_and_deployment_permissions_are_coupled(chart, controller, enabled, namespace):
    result = render(chart, {"node": {"enabled": False}, "placementNamespace": namespace, "controller": controller})
    assert result.returncode == 0, result.stderr
    objects = [o for o in yaml.safe_load_all(result.stdout) if o]
    deployment = next(o for o in objects if o["kind"] == "Deployment")
    args = deployment["spec"]["template"]["spec"]["containers"][0]["args"]
    assert args.count("--apply") == int(enabled)
    config = next(o for o in objects if o["kind"] == "ConfigMap"
                  and o["metadata"]["name"] == "test-rm-controller")
    assert yaml.safe_load(config["data"]["spec.yaml"])["namespace"] == (namespace or "control")
    writers = [(o, rule) for o in objects if o["kind"] in ("Role", "ClusterRole")
               for rule in o["rules"] if "deployments" in rule["resources"]]
    assert len(writers) == int(enabled)
    if enabled:
        role, rule = writers[0]
        assert role["kind"] == "Role"
        assert role["metadata"]["namespace"] == (namespace or "control")
        # kubectl patch reads the object before patching; the client SDK needs list/patch.
        assert rule == {"apiGroups": ["apps"], "resources": ["deployments"], "verbs": ["get", "list", "patch"]}
        binding = next(o for o in objects if o["kind"] == "RoleBinding"
                       and o["metadata"]["namespace"] == (namespace or "control"))
        assert binding["roleRef"]["name"] == role["metadata"]["name"]
        assert binding["subjects"][0]["namespace"] == "control"


@pytest.mark.parametrize("extra", [["--namespace=elsewhere"], ["--namespace", "elsewhere"]])
def test_apply_namespace_override_fails_with_actionable_namespace_setting(chart, extra):
    result = render(chart, {"controller": {"apply": True, "extraArgs": extra}})
    assert result.returncode != 0
    assert "placementNamespace" in result.stderr
