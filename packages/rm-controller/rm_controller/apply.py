"""Apply mode (`--apply`): make annotated serving Deployments follow the placement document.

A Deployment opts in with two annotations:

    airm.ai-computing.io/pool: llama8b-pd-pool     # the InferencePool / decision pool
    airm.ai-computing.io/role: decode              # prefill | decode | serve

and gets a merge patch with
- `spec.replicas` = cards of the decision / cards per instance of that device type (profiles `group`);
- required node affinity: the node label `airm.ai-computing.io/<vendor>.<model>` exists and
  `kubernetes.io/hostname` is one of the decision's nodes (one term per device type);
- pod-template annotation `airm.ai-computing.io/accelerator-ids` with the card ids, for charts that pin
  devices from it, and the Deployment annotation `airm.ai-computing.io/placement-generation`.

A role that mixes device types (`optimal` with mixed roles) needs one Deployment per type, each with the
annotation `airm.ai-computing.io/accelerator: <vendor>.<model>`: it then follows only that type's cards of
the decision, and goes to 0 replicas when the decision has none. Without it a Deployment takes all of them.

A Deployment that already matches gets no patch, so re-running is quiet; a decision that is empty (nothing
fits) leaves its Deployment alone. Pinning the device inside the pod is the serving chart's job.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from rm_core import Accelerator
from rm_core.k8s import LABEL_PREFIX

POOL_ANNOTATION = "airm.ai-computing.io/pool"
ROLE_ANNOTATION = "airm.ai-computing.io/role"
IDS_ANNOTATION = "airm.ai-computing.io/accelerator-ids"
GENERATION_ANNOTATION = "airm.ai-computing.io/placement-generation"
ACCEL_ANNOTATION = "airm.ai-computing.io/accelerator"
HOSTNAME = "kubernetes.io/hostname"


def _kind(card_id: str, cards: Dict[str, Accelerator]) -> str:
    a = cards.get(card_id)
    return f"{a.vendor}.{a.model}" if a else card_id.split("/", 1)[1].split(":")[0]


def desired(decision, cards: Dict[str, Accelerator], groups: Dict[str, int],
            kind: Optional[str] = None) -> Tuple[int, dict, str]:
    """(replicas, node affinity, ids annotation) for one decision (rm_core.placement.Decision), or for its
    cards of one device type."""
    ids = [i for i in decision.accelerator_ids if kind is None or _kind(i, cards) == kind]
    by_kind: Dict[str, List[str]] = {}
    for i in ids:
        by_kind.setdefault(_kind(i, cards), []).append(i)
    replicas = sum(max(1, len(v) // groups.get(k, 1)) for k, v in by_kind.items())
    terms = [{"matchExpressions": [
        {"key": LABEL_PREFIX + k, "operator": "Exists"},
        {"key": HOSTNAME, "operator": "In", "values": sorted({i.split("/", 1)[0] for i in v})}]}
        for k, v in sorted(by_kind.items())]
    affinity = {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {"nodeSelectorTerms": terms}}}
    return replicas, affinity, ",".join(ids)


def patches(doc, deployments: Sequence[dict], cards: Sequence[Accelerator],
            groups: Optional[Dict[str, int]] = None) -> List[dict]:
    """[{"name", "patch" (None when nothing to do), "note"}] for every annotated Deployment."""
    by_id = {a.id: a for a in cards}
    decisions = {(d.pool, d.workload.kind): d for d in doc.decisions}
    out = []
    for dep in sorted(deployments, key=lambda d: d["metadata"]["name"]):
        meta = dep.get("metadata") or {}
        ann = meta.get("annotations") or {}
        name, pool, role = meta["name"], ann.get(POOL_ANNOTATION), ann.get(ROLE_ANNOTATION, "serve")
        d = decisions.get((pool, role))
        if d is None:
            out.append({"name": name, "patch": None, "note": f"no decision for pool {pool} role {role}"})
            continue
        if not d.accelerator_ids:
            out.append({"name": name, "patch": None, "note": f"left alone: {d.reason}"})
            continue
        kind = ann.get(ACCEL_ANNOTATION)
        if kind and not any(_kind(i, by_id) == kind for i in d.accelerator_ids):
            if (dep.get("spec") or {}).get("replicas") == 0:
                out.append({"name": name, "patch": None, "note": "up to date"})
            else:
                out.append({"name": name, "note": f"{role} of {pool}: no {kind} cards in the decision",
                            "patch": {"metadata": {"annotations": {GENERATION_ANNOTATION: str(doc.generation)}},
                                      "spec": {"replicas": 0}}})
            continue
        replicas, affinity, ids = desired(d, by_id, groups or {}, kind)
        spec = dep.get("spec") or {}
        tmpl = spec.get("template") or {}
        current_affinity = ((tmpl.get("spec") or {}).get("affinity") or {}).get("nodeAffinity")
        same = (spec.get("replicas") == replicas and current_affinity == affinity["nodeAffinity"]
                and ((tmpl.get("metadata") or {}).get("annotations") or {}).get(IDS_ANNOTATION) == ids)
        if same:
            out.append({"name": name, "patch": None, "note": "up to date"})
            continue
        patch = {"metadata": {"annotations": {GENERATION_ANNOTATION: str(doc.generation)}},
                 "spec": {"replicas": replicas,
                          "template": {"metadata": {"annotations": {IDS_ANNOTATION: ids}},
                                       "spec": {"affinity": affinity}}}}
        out.append({"name": name, "patch": patch,
                    "note": f"{role} of {pool}: {replicas} replica(s) on {', '.join(d.nodes)}"})
    return out
