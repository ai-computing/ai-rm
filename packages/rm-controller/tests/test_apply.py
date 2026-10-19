"""Apply mode: Deployment patches from the placement document, printed with --dry-run."""
from __future__ import annotations

import json

from rm_controller import apply, controller, document, profiles
from test_controller import M, POOL, FakeIO

ANN = {apply.POOL_ANNOTATION: "koni-hetero-pd-pool"}


def dep(name, role, **spec):
    return {"metadata": {"name": name, "annotations": {**ANN, apply.ROLE_ANNOTATION: role}}, "spec": spec}


class ApplyIO(FakeIO):
    def __init__(self, deployments):
        super().__init__()
        self.deps, self.patched = deployments, []

    def deployments(self, namespace):
        return self.deps

    def patch_deployment(self, namespace, name, patch):
        self.patched.append((name, patch))


def _spec(tmp_path):
    s = tmp_path / "spec.yaml"
    s.write_text(json.dumps({"pools": [{"pool": "koni-hetero-pd-pool", "model": M, "kv_transport": "p2p",
                                        "prefill": {"accelerator": "furiosa.RNGD"},
                                        "decode": {"accelerator": "rebellions.ATOM", "count": 2}}]}),
                 encoding="utf-8")
    return controller.load_spec(str(s))


def test_patches_follow_decisions_and_atom_groups():
    io = ApplyIO([dep("pre", "prefill", replicas=1), dep("dec", "decode", replicas=3), dep("other", "serve")])
    groups = {**{k: d.group for k, d in profiles.load().devices.items()}, "rebellions.ATOM": 2}   # a TP-2 ATOM
    entries, _ = controller.plan(_spec_obj(), POOL, {"etri-esc8000-e11"})
    doc, _ = document.build(entries, document.parse(None), "topology")
    out = {p["name"]: p for p in apply.patches(doc, io.deps, POOL, groups)}
    dec = out["dec"]["patch"]
    assert dec["spec"]["replicas"] == 1                              # two ATOM cards = one TP-2 instance
    terms = dec["spec"]["template"]["spec"]["affinity"]["nodeAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"]["nodeSelectorTerms"]
    assert terms == [{"matchExpressions": [
        {"key": "airm.ai-computing.io/rebellions.ATOM", "operator": "Exists"},
        {"key": "kubernetes.io/hostname", "operator": "In", "values": ["etri-001"]}]}]
    assert dec["spec"]["template"]["metadata"]["annotations"][apply.IDS_ANNOTATION] == \
        "etri-001/rebellions:0,etri-001/rebellions:1"
    assert dec["metadata"]["annotations"][apply.GENERATION_ANNOTATION] == "1"
    assert out["pre"]["patch"]["spec"]["replicas"] == 1 and out["other"]["patch"] is None
    # a Deployment already matching gets nothing
    done = dep("dec", "decode", replicas=1, template={**dec["spec"]["template"],
                                                      "spec": {"affinity": {**dec["spec"]["template"]["spec"]["affinity"],
                                                                            "podAntiAffinity": {}}}})
    again = apply.patches(doc, [done], POOL, {"rebellions.ATOM": 2})
    assert again[0]["patch"] is None and again[0]["note"] == "up to date"


def _spec_obj():
    return {"pools": [{"pool": "koni-hetero-pd-pool", "model": M, "kv_transport": "p2p",
                       "prefill": {"accelerator": "furiosa.RNGD"},
                       "decode": {"accelerator": "rebellions.ATOM", "count": 2}}]}


def test_dry_run_prints_patches_and_apply_patches(tmp_path, capsys):
    spec, perf = _spec(tmp_path), profiles.load()
    io = ApplyIO([dep("pre", "prefill"), dep("dec", "decode")])
    assert controller.run_once(spec, io, namespace="llm-serving", dry_run=True, apply=True, perf=perf) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["document"]["generation"] == 1 and len([p for p in out["patches"] if p["patch"]]) == 2
    assert io.patched == [] and io.applied == []
    assert controller.run_once(spec, io, namespace="llm-serving", dry_run=False, apply=True, perf=perf) == 0
    assert [n for n, _ in io.patched] == ["dec", "pre"] and len(io.applied) == 1


def test_without_apply_nothing_is_patched(tmp_path, capsys):
    io = ApplyIO([dep("pre", "prefill")])
    controller.run_once(_spec(tmp_path), io, namespace="llm-serving", dry_run=True)
    assert "decisions" in json.loads(capsys.readouterr().out) and io.patched == []


def test_empty_decision_leaves_deployment_alone():
    entries, unplaced = controller.plan({"pools": [{**_spec_obj()["pools"][0],
                                                    "decode": {"accelerator": "rebellions.ATOM", "count": 9}}]},
                                        POOL, set())
    doc, _ = document.build(entries, document.parse(None), "topology")
    out = apply.patches(doc, [dep("dec", "decode")], POOL)
    assert unplaced and out[0]["patch"] is None and out[0]["note"].startswith("left alone")


def test_serve_pool_deployment_follows_its_decision(tmp_path):
    """Two pools, two models: the aggregated pool's `serve` Deployment gets its card count and node."""
    from test_controller import _two_pools
    spec, perf = _two_pools(tmp_path, decode="furiosa.RNGD"), profiles.load()
    qwen = {"metadata": {"name": "qwen", "annotations": {apply.POOL_ANNOTATION: "qwen3-4b-pool",
                                                        apply.ROLE_ANNOTATION: "serve"}}, "spec": {"replicas": 0}}
    pd = [{"metadata": {"name": n, "annotations": {apply.POOL_ANNOTATION: "llama8b-pd-pool",
                                                  apply.ROLE_ANNOTATION: r}}, "spec": {"replicas": 0}}
          for n, r in (("pre", "prefill"), ("dec", "decode"))]
    io = ApplyIO([qwen] + pd)
    assert controller.run_once(spec, io, namespace="llm-serving", dry_run=False, apply=True, perf=perf) == 0
    got = dict(io.patched)
    assert {n: p["spec"]["replicas"] for n, p in got.items()} == {"qwen": 1, "pre": 1, "dec": 1}
    assert got["qwen"]["spec"]["template"]["metadata"]["annotations"][apply.IDS_ANNOTATION] == "etri-001/furiosa:3"
