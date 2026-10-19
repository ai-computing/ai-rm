"""The `airm-placement` ConfigMap document (llm-d-setup deploy/airm/README.md, key `decisions.json`).

    {"protocol": "0.1", "generation": N, "updatedAt": "...Z", "placement": "topology",
     "decisions": [{"pool", "workload": {"kind", "model", "slo", "labels"}, "acceleratorIds",
                    "kvTransport", "reason"}]}

`generation` goes up only when the decisions change, so readers that apply a document once are not
woken by a rewrite of the same placement.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from rm_core import PlacementDecision, Workload

PROTOCOL = "0.1"
KEY = "decisions.json"
CONFIGMAP = "airm-placement"


def decision_entry(pool: str, workload: Workload, d: PlacementDecision) -> dict:
    return {"pool": pool,
            "workload": {"kind": workload.kind, "model": workload.model, "slo": dict(workload.slo),
                         "labels": dict(workload.labels)},
            "acceleratorIds": list(d.accelerator_ids), "kvTransport": d.kv_transport, "reason": d.reason}


def parse(cm: Optional[dict]) -> dict:
    """The document inside a ConfigMap object (or an empty v0.1 document)."""
    raw = ((cm or {}).get("data") or {}).get(KEY)
    if not raw:
        return {"protocol": PROTOCOL, "generation": 0, "updatedAt": None, "decisions": []}
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise ValueError(f"{CONFIGMAP}/{KEY} is not a JSON object")
    return doc


def build(entries: List[dict], previous: dict, placement: str, now: Optional[datetime] = None) -> Tuple[dict, bool]:
    """The next document and whether it differs from `previous` in placement or decisions."""
    changed = previous.get("decisions") != entries or previous.get("placement") != placement
    if not changed:
        return previous, False
    now = now or datetime.now(timezone.utc)
    return {"protocol": PROTOCOL, "generation": int(previous.get("generation") or 0) + 1,
            "updatedAt": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "placement": placement,
            "decisions": entries}, True


def configmap(doc: dict, namespace: str) -> dict:
    return {"apiVersion": "v1", "kind": "ConfigMap",
            "metadata": {"name": CONFIGMAP, "namespace": namespace,
                         "labels": {"app.kubernetes.io/managed-by": "rm-controller"}},
            "data": {KEY: json.dumps(doc, indent=2) + "\n"}}
