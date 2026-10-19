"""Topology-aware placement (entry point `airm.placements:topology`).

`place()` is the rm-core Placement contract for one workload. `place_pd()` places a prefill/decode pair
together, which the per-workload contract cannot express:

- prefill and decode on one node when the KV path is host-local (`shm`, `p2p`), on distinct cards
  unless the transport is `loopback`;
- nodes that are cordoned, not Ready or under pressure are skipped, and so are cards whose
  AcceleratorProfile reports them unhealthy (`healthy()`);
- prefill takes the highest peak (for the workload's precision when the profile states it), decode the
  most memory; ties go to the lowest card index, so the choice is stable across runs;
- cards already given to an earlier pool are not reused;
- nothing that fits gives empty decisions with the reason, never an exception.

Accelerator filters are `vendor.model` strings as in the node labels `airm.ai-computing.io/<vendor>.<model>`
(e.g. `furiosa.RNGD`), passed in `Workload.labels["airm.ai-computing.io/accelerator"]` for `place()`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rm_core import Accelerator, PlacementDecision, Workload

ACCEL_LABEL = "airm.ai-computing.io/accelerator"
HOST_LOCAL = ("shm", "p2p", "loopback")
HEALTH_KEY = "health"                       # Accelerator.extra key; kube.py also folds profile status into it
UNHEALTHY = ("unhealthy", "failed", "error", "false", "lost")


def healthy(a: Accelerator) -> bool:
    """False when the card's AcceleratorProfile says it is unhealthy (extra `health`/`healthy`)."""
    return (str(a.extra.get(HEALTH_KEY, "")).lower() not in UNHEALTHY
            and str(a.extra.get("healthy", "")).lower() not in ("false", "0", "no"))


def kind_of(a: Accelerator) -> str:
    return f"{a.vendor}.{a.model}"


def _index(a: Accelerator) -> int:
    m = re.search(r":(\d+)$", a.id)
    return int(m.group(1)) if m else 0


def _peak(a: Accelerator, precision: str) -> float:
    if not a.peak_tflops:
        return 0.0
    return float(a.peak_tflops.get(precision, max(a.peak_tflops.values())))


def _rank(role: str, precision: str):
    """Sort key: best first, stable on (node, index)."""
    if role == "prefill":
        return lambda a: (-_peak(a, precision), -a.memory_bytes, a.node, _index(a))
    return lambda a: (-a.memory_bytes, -_peak(a, precision), a.node, _index(a))


@dataclass(frozen=True)
class RoleSpec:
    accelerator: Optional[str] = None   # vendor.model filter, None = any
    count: int = 1


ANY = RoleSpec()


class TopologyPlacement:
    name = "topology"

    def __init__(self, unschedulable_nodes: Iterable[str] = ()):
        self.unschedulable = frozenset(unschedulable_nodes)

    def usable(self, a: Accelerator) -> bool:
        return a.node not in self.unschedulable and healthy(a)

    # -- rm-core Placement contract: one workload ---------------------------------------------------

    def place(self, workload: Workload, pool: Sequence[Accelerator],
              metrics: Optional[Dict[str, float]] = None) -> PlacementDecision:
        workload.validate()
        want = workload.labels.get(ACCEL_LABEL)
        cands = [a for a in pool if self.usable(a) and (not want or kind_of(a) == want)]
        if not cands:
            return PlacementDecision([], reason=self._why_empty(pool, want, 1))
        role = "prefill" if workload.kind == "prefill" else "decode"
        best = sorted(cands, key=_rank(role, workload.precision))[0]
        what = "highest peak" if role == "prefill" else "most memory"
        return PlacementDecision([best.id], "", f"topology: {workload.kind} -> {best.id} ({kind_of(best)}, {what})")

    # -- prefill/decode pair --------------------------------------------------------------------------

    def place_pd(self, prefill: Workload, decode: Workload, pool: Sequence[Accelerator], *,
                 kv_transport: str, prefill_spec: RoleSpec = ANY, decode_spec: RoleSpec = ANY,
                 used: Iterable[str] = ()) -> Tuple[PlacementDecision, PlacementDecision]:
        prefill.validate()
        decode.validate()
        taken = set(used)
        free = [a for a in pool if a.id not in taken and self.usable(a)]
        same_node = kv_transport in HOST_LOCAL
        share_card = kv_transport == "loopback"

        def pick(cands: List[Accelerator], spec: RoleSpec, role: str, wl: Workload, exclude=()):
            c = [a for a in cands if a.id not in exclude and (not spec.accelerator or kind_of(a) == spec.accelerator)]
            c.sort(key=_rank(role, wl.precision))
            return c[: spec.count] if len(c) >= spec.count else None

        options = []
        groups = ({n: [a for a in free if a.node == n] for n in sorted({a.node for a in free})}
                  if same_node else {"*": free})
        for node, cands in groups.items():
            p = pick(cands, prefill_spec, "prefill", prefill)
            if not p:
                continue
            d = pick(cands, decode_spec, "decode", decode, exclude=() if share_card else {a.id for a in p})
            if not d:
                continue
            score = (-sum(_peak(a, prefill.precision) for a in p), -sum(a.memory_bytes for a in d),
                     -len(cands), node)
            options.append((score, node, p, d))
        if not options:
            why = self._why_empty_pd(pool, taken, kv_transport, prefill_spec, decode_spec)
            return PlacementDecision([], kv_transport, why), PlacementDecision([], kv_transport, why)
        _, node, p, d = sorted(options, key=lambda o: o[0])[0]
        where = f"on {node}" if same_node else "across nodes"
        need = f"; {kv_transport} keeps prefill and decode on one node" if same_node else ""
        pr = (f"topology: prefill {', '.join(a.id for a in p)} ({kind_of(p[0])}, highest peak) {where}"
              f"{need}")
        dr = (f"topology: decode {', '.join(a.id for a in d)} ({kind_of(d[0])}, most memory) {where}"
              f"{need}")
        return (PlacementDecision([a.id for a in p], kv_transport, pr),
                PlacementDecision([a.id for a in d], kv_transport, dr))

    # -- aggregated pool: `count` single-card replicas, prefill and decode on the same card ----------

    def place_serve(self, workload: Workload, pool: Sequence[Accelerator], *, spec: RoleSpec = ANY,
                    used: Iterable[str] = ()) -> PlacementDecision:
        """`spec.count` free cards of `spec.accelerator` for an aggregated (`serve`) pool. Replicas need
        no KV path between them, so they may span nodes; the node with the most matching free cards
        goes first (fewer nodes per pool), then most memory, then the lowest card index."""
        workload.validate()
        taken = set(used)
        cands = [a for a in pool if a.id not in taken and self.usable(a)
                 and (not spec.accelerator or kind_of(a) == spec.accelerator)]
        if len(cands) < spec.count:
            why = self._why_empty(pool, spec.accelerator, spec.count)
            if taken:
                why += f"; {len(taken)} card(s) already placed"
            return PlacementDecision([], "", why)
        per_node = {n: sum(1 for a in cands if a.node == n) for n in {a.node for a in cands}}
        best = sorted(cands, key=lambda a: (-per_node[a.node], a.node, -a.memory_bytes, _index(a)))[: spec.count]
        nodes = sorted({a.node for a in best})
        return PlacementDecision([a.id for a in best], "",
                                 f"topology: serve {', '.join(a.id for a in best)} ({kind_of(best[0])}, "
                                 f"{spec.count} replica(s), aggregated) on {', '.join(nodes)}")

    # -- reasons for an empty decision -----------------------------------------------------------

    def _why_empty(self, pool: Sequence[Accelerator], want: Optional[str], count: int) -> str:
        if not pool:
            return "empty pool"
        skipped = sorted({a.node for a in pool if a.node in self.unschedulable})
        parts = [f"no schedulable {want or 'accelerator'} x{count}"]
        if skipped:
            parts.append("skipped unschedulable " + ", ".join(skipped))
        sick = sorted(a.id for a in pool if not healthy(a))
        if sick:
            parts.append("skipped unhealthy " + ", ".join(sick))
        return "; ".join(parts)

    def _why_empty_pd(self, pool, taken, kv_transport, ps: RoleSpec, ds: RoleSpec) -> str:
        if not pool:
            return "empty pool"
        need = f"{ps.accelerator or 'any'} x{ps.count} for prefill and {ds.accelerator or 'any'} x{ds.count} for decode"
        where = " on one node" if kv_transport in HOST_LOCAL else ""
        parts = [f"no free {need}{where} ({kv_transport})"]
        skipped = sorted({a.node for a in pool if a.node in self.unschedulable})
        if skipped:
            parts.append("skipped unschedulable " + ", ".join(skipped))
        sick = sorted(a.id for a in pool if not healthy(a))
        if sick:
            parts.append("skipped unhealthy " + ", ".join(sick))
        if taken:
            parts.append(f"{len(taken)} card(s) already placed")
        return "; ".join(parts)
