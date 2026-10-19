"""The `airm-placement` ConfigMap document, as rm-core defines it (PROTOCOL §5.4, `rm_core.placement`).

    {"protocol": "0.1", "generation": N, "updatedAt": "...Z", "placement": "topology",
     "decisions": [{"pool", "workload": {"kind", "model", "slo", "labels"}, "acceleratorIds",
                    "kvTransport", "reason"}]}

`generation` goes up only when the decisions change, so readers that apply a document once are not
woken by a rewrite of the same placement. This module only adds rm-controller's ConfigMap label; the
bytes written are those of `rm_core.placement` (identical to rm-controller 0.1's).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

from rm_core import PlacementDecision, Workload
from rm_core.placement import CONFIGMAP, KEY, Decision, PlacementDocument, build as _build, parse

__all__ = ["CONFIGMAP", "KEY", "Decision", "PlacementDocument", "build", "configmap", "decision_entry", "parse"]
MANAGED_BY = {"app.kubernetes.io/managed-by": "rm-controller"}


def decision_entry(pool: str, workload: Workload, d: PlacementDecision) -> Decision:
    return Decision.from_placement(pool, workload, d)


def build(entries: List[Decision], previous: PlacementDocument, placement: str,
          now: Optional[datetime] = None) -> Tuple[PlacementDocument, bool]:
    """The next document and whether it differs from `previous` in placement or decisions."""
    return _build(entries, previous, placement, now)


def configmap(doc: PlacementDocument, namespace: str) -> dict:
    from rm_core.placement import configmap as _configmap
    return _configmap(doc, namespace, labels=MANAGED_BY)
