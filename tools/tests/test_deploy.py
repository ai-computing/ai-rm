"""Deployment routing: a chart must never fall through to legacy manifests."""
import argparse
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import airm


@pytest.mark.parametrize("dry_run", [False, True])
def test_chart_component_fails_with_helm_command_without_applying_manifests(monkeypatch, tmp_path, capsys, dry_run):
    comp = {"name": "rngd-pd", "path": str(tmp_path / "rngd-pd"),
            "spec": {"deploy": {"chart": "deploy/helm/rngd-pd", "manifests": "deploy/k8s"}}}
    monkeypatch.setattr(airm, "components", lambda *_: [comp])
    monkeypatch.setattr(airm.subprocess, "run", lambda *_a, **_k: pytest.fail("must not execute a deployment"))
    args = argparse.Namespace(cluster="lab", layer=None, components=["rngd-pd"], dry_run=dry_run)
    assert airm.cmd_deploy(args) == 1
    msg = capsys.readouterr().out
    assert "helm upgrade --install rngd-pd" in msg
    assert "deploy/helm/rngd-pd" in msg
    assert "values" in msg and "namespace" in msg


def test_chart_failure_is_checked_before_other_components_are_applied(monkeypatch, tmp_path):
    comps = [{"name": "first", "path": str(tmp_path), "spec": {"deploy": {"manifests": "k8s"}}},
             {"name": "chart", "path": str(tmp_path), "spec": {"deploy": {"chart": "chart"}}}]
    monkeypatch.setattr(airm, "components", lambda *_: comps)
    monkeypatch.setattr(airm.subprocess, "run", lambda *_a, **_k: pytest.fail("must validate all components first"))
    args = argparse.Namespace(cluster="lab", layer=None, components=[], dry_run=False)
    assert airm.cmd_deploy(args) == 1
