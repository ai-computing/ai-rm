"""rm-controller: place the pools a spec asks for and write the airm-placement ConfigMap.

    rm-controller --spec spec.yaml --dry-run      # print the document it would write
    rm-controller --spec spec.yaml --once         # write it if the decisions changed
    rm-controller --spec spec.yaml                # keep doing that every --interval seconds
    rm-controller --spec spec.yaml --apply        # also patch annotated Deployments (--dry-run prints them)
    rm-controller --spec spec.yaml --rebalance    # also adjust P:D per pool from metrics or trace stats

Spec (YAML):

    namespace: llm-serving                 # where airm-placement lives (llm-d's namespace)
    placement: topology                    # topology (default) | optimal
    objective: per_card                    # optimal only: per_card (default) | goodput
    mixed_roles: true                      # optimal only: a role may mix device types (default true)
    profiles: profiles.yaml                # optimal/rebalance/apply: throughput table (default: packaged)
    pools:
      - pool: llama8b-pd-pool              # InferencePool name
        model: meta-llama/Llama-3.1-8B-Instruct
        kv_transport: shm                  # airm.kv_transports name; `auto` lets optimal choose
        slo: {tpot_p90_ms: 100}
        precision: bf16
        prefill: {accelerator: furiosa.RNGD, count: 1}   # optimal: accelerator filters, count ignored
        decode:  {accelerator: furiosa.RNGD, count: 1}
        workload: {trace: azure-conv}      # optimal/rebalance: mix (mix.py)
        budget: 6                          # optimal/rebalance: most cards for the pool
        rebalance: {metrics: http://prefill-pod:8000/metrics, band: 0.2, hold: 3, cooldown_s: 300,
                    margin: 0.2}           # a move must cut the predicted worst-role pressure by 20 %

Pools are placed in order; a card given to one pool is not offered to the next. A placement that is still
valid is kept (no churn): only a role whose card disappeared, became unhealthy or whose node became
unschedulable is re-placed, and the generation moves with it.
Exit status: 0 written or unchanged, 1 a pool could not be placed (the document still records why),
2 usage or cluster errors.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Dict, List, Optional, Tuple

import yaml
from rm_core import Accelerator, PlacementDecision, Workload
from rm_core.errors import ContractError

from . import apply as applying
from . import document, kube
from . import mix as mixes
from . import predict as pred
from . import profiles as prof
from . import rebalance as rb
from .optimal import MIXED_ROLES, OptimalPlacement
from .policy import ACCEL_LABEL, HOST_LOCAL, RoleSpec, TopologyPlacement, healthy, kind_of

POLICIES = ("topology", "optimal")


def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}
    if not isinstance(spec.get("pools"), list) or not spec["pools"]:
        raise ValueError(f"{path}: 'pools' must be a non-empty list")
    if spec.get("placement", "topology") not in POLICIES:
        raise ValueError(f"{path}: placement must be one of {POLICIES}")
    if not isinstance(spec.get("mixed_roles", MIXED_ROLES), bool):
        raise ValueError(f"{path}: mixed_roles must be true or false")
    for p in spec["pools"]:
        for key in ("pool", "model", "kv_transport", "prefill", "decode"):
            if key not in p:
                raise ValueError(f"{path}: pool {p.get('pool', '?')} is missing '{key}'")
        if p["kv_transport"] == "auto" and spec.get("placement", "topology") != "optimal":
            raise ValueError(f"{path}: pool {p['pool']}: kv_transport auto needs placement: optimal")
        mixes.from_spec(p.get("workload"))   # validates
    return spec


def make_policy(spec: dict, unschedulable, perf: Optional[prof.Profiles] = None):
    if spec.get("placement", "topology") == "optimal":
        return OptimalPlacement(unschedulable, profiles=perf, objective=spec.get("objective", "per_card"),
                                mixed_roles=spec.get("mixed_roles", MIXED_ROLES))
    return TopologyPlacement(unschedulable)


def _group(perf: Optional[prof.Profiles], kind: Optional[str]) -> int:
    return perf.devices[kind].group if perf and kind in perf.devices else 1


def _shape(ids) -> Tuple[int, Tuple[str, ...]]:
    return len(ids), tuple(sorted(i.split("/", 1)[1].split(":")[0] for i in ids))


def _lost_why(card_id: str, cards: Dict[str, Accelerator], policy, used) -> str:
    a = cards.get(card_id)
    if a is None:
        return "gone"
    if not healthy(a):
        return "unhealthy"
    if a.node in policy.unschedulable:
        return f"node {a.node} unschedulable"
    return "taken" if card_id in used else "unavailable"


def _reuse(pool: str, fresh: Tuple[PlacementDecision, PlacementDecision], prev: dict, cards: Dict[str, Accelerator],
           policy, used: set, perf) -> Tuple[PlacementDecision, PlacementDecision]:
    """Keep the previous decisions while they are valid; re-place only a role that lost a card."""
    old = (prev.get((pool, "prefill")), prev.get((pool, "decode")))
    if not all(o and o.accelerator_ids for o in old) or not all(f.accelerator_ids for f in fresh):
        return fresh
    if any(o.kv_transport != f.kv_transport or _shape(o.accelerator_ids) != _shape(f.accelerator_ids)
           for o, f in zip(old, fresh)):
        return fresh      # the spec, the policy's choice of counts/types, or the rebalancer changed the shape
    ok = lambda i: i in cards and policy.usable(cards[i]) and i not in used  # noqa: E731
    lost = [[i for i in o.accelerator_ids if not ok(i)] for o in old]
    if not lost[0] and not lost[1]:
        return old[0].decision, old[1].decision
    if lost[0] and lost[1]:
        why = "; ".join(f"{i} {_lost_why(i, cards, policy, used)}" for i in lost[0] + lost[1])
        return tuple(PlacementDecision(f.accelerator_ids, f.kv_transport, f"re-placed ({why}): {f.reason}")
                     for f in fresh)
    r = 0 if lost[0] else 1
    keep_role, fix = old[1 - r], old[r]
    host_local = fix.kv_transport in HOST_LOCAL or (
        perf and fix.kv_transport in perf.links and perf.links[fix.kv_transport].scope == "host")
    survivors = [i for i in fix.accelerator_ids if i not in lost[r]]
    busy = used | set(keep_role.accelerator_ids) | set(survivors)
    out = list(survivors)
    for gone in lost[r]:   # a role may mix device types: replace each card with one of its own type
        node = gone.split("/", 1)[0]
        kind = kind_of(cards[gone]) if gone in cards else kind_of(cards[fresh[r].accelerator_ids[0]])
        group = _group(perf, kind)
        cands = sorted((a for a in cards.values() if a.id not in busy and policy.usable(a) and kind_of(a) == kind
                        and (a.node == node or not (host_local or group > 1))),
                       key=lambda a: (a.node != node, a.node, a.id))
        if not cands:
            why = "; ".join(f"{i} {_lost_why(i, cards, policy, used)}" for i in lost[r])
            return tuple(PlacementDecision(f.accelerator_ids, f.kv_transport, f"re-placed ({why}): {f.reason}")
                         for f in fresh)
        out.append(cands[0].id)
        busy.add(cands[0].id)
    role = ("prefill", "decode")[r]
    why = ", ".join(f"{i} {_lost_why(i, cards, policy, used)}" for i in lost[r])
    fixed = PlacementDecision(out, fix.kv_transport,
                              f"re-placed {role} ({why}) -> {', '.join(sorted(set(out) - set(survivors)))}; "
                              f"{('decode', 'prefill')[r]} kept")
    return (fixed, keep_role.decision) if r == 0 else (keep_role.decision, fixed)


def plan(spec: dict, profiles, unschedulable, previous=None, *, perf: Optional[prof.Profiles] = None,
         overrides: Optional[Dict[str, Tuple[int, int]]] = None) -> Tuple[List, List[str]]:
    """Decision entries for every pool, and the pools that could not be placed.

    `previous` (a PlacementDocument) keeps still-valid decisions; `overrides` maps a pool to (prefill,
    decode) instance counts from the rebalancer."""
    policy = make_policy(spec, unschedulable, perf)
    perf = perf or getattr(policy, "profiles", None)
    cards = {a.id: a for a in profiles}
    prev = ({(d.pool, d.workload.kind): d for d in previous.decisions}
            if previous is not None and previous.placement == policy.name else {})
    used: set = set()
    entries, unplaced = [], []
    for p in spec["pools"]:
        slo = dict(p.get("slo") or {})
        precision = p.get("precision", "bf16")
        counts = (overrides or {}).get(p["pool"])
        roles = {}
        for i, role in enumerate(("prefill", "decode")):
            r = p[role] or {}
            labels = {ACCEL_LABEL: r["accelerator"]} if r.get("accelerator") else {}
            count = int(r.get("count", 1))
            if counts and isinstance(policy, TopologyPlacement):
                count = counts[i] * _group(perf, r.get("accelerator"))
            roles[role] = (Workload(kind=role, model=p["model"], slo=slo, precision=precision, labels=labels),
                           RoleSpec(r.get("accelerator"), count))
        kw = dict(kv_transport=p["kv_transport"], prefill_spec=roles["prefill"][1], decode_spec=roles["decode"][1],
                  used=used)
        if isinstance(policy, OptimalPlacement):
            kw.update(mix=mixes.from_spec(p.get("workload")), budget=p.get("budget"), counts=counts)
        fresh = policy.place_pd(roles["prefill"][0], roles["decode"][0], profiles, **kw)
        dp, dd = _reuse(p["pool"], fresh, prev, cards, policy, used, perf)
        if not dp.accelerator_ids:
            unplaced.append(p["pool"])
        used.update(dp.accelerator_ids, dd.accelerator_ids)
        entries.append(document.decision_entry(p["pool"], roles["prefill"][0], dp))
        entries.append(document.decision_entry(p["pool"], roles["decode"][0], dd))
    return entries, unplaced


class Rebalancing:
    """Per-pool P:D targets across rounds (hysteresis lives in rebalance.Rebalancer)."""

    def __init__(self, spec: dict, perf: prof.Profiles, *, once: bool):
        self.spec, self.perf = spec, perf
        self.pools = {p["pool"]: p for p in spec["pools"] if p.get("rebalance")}
        self.hyst = {name: rb.Rebalancer(float(p["rebalance"].get("band", 0.2)),
                                         1 if once else int(p["rebalance"].get("hold", 3)),
                                         0.0 if once else float(p["rebalance"].get("cooldown_s", 300)))
                     for name, p in self.pools.items()}
        self.overrides: Dict[str, Tuple[int, int]] = {}
        self.scrapes: Dict[Tuple[str, str], Tuple[list, float]] = {}

    def _observe(self, pool: str, cfg: dict, notes: Optional[List[str]] = None) -> Optional[rb.Observation]:
        src = cfg.get("metrics")
        if not src:
            return None
        sources = src.items() if isinstance(src, dict) else [(None, src)]
        obs = rb.Observation()
        for role, s in sources:
            try:
                text = rb.read_source(str(s))
            except OSError as e:
                # No signal from this source (the gateway is not up yet, or restarting): the role
                # counts as unpressured, so the split holds, and placement still runs this round.
                if notes is not None:
                    notes.append(f"{pool}: metrics {s} unreadable ({e}); split held")
                continue
            samples, now = rb.parse_prometheus(text), time.monotonic()
            before, then = self.scrapes.get((pool, str(s)), (None, None))
            o = rb.observe(samples, role_label=cfg.get("role_label"), role=role, previous=before,
                           elapsed_s=None if then is None else now - then)
            self.scrapes[(pool, str(s))] = (samples, now)
            obs = rb.merge(obs, o)
        return obs

    def update(self, previous, cards: Dict[str, Accelerator]) -> List[str]:
        notes = []
        for name, p in self.pools.items():
            cfg = p["rebalance"]
            kinds, cur = [], []
            for role in ("prefill", "decode"):
                d = next((d for d in previous.decisions if d.pool == name and d.workload.kind == role), None)
                ids = d.accelerator_ids if d else []
                k = (kind_of(cards[ids[0]]) if ids and ids[0] in cards else (p[role] or {}).get("accelerator"))
                kinds.append(k)
                n = len(ids) if ids else int((p[role] or {}).get("count", 1))
                cur.append(max(1, n // _group(self.perf, k)))
            current = self.overrides.get(name, tuple(cur))
            groups = (_group(self.perf, kinds[0]), _group(self.perf, kinds[1]))
            budget = int(p.get("budget") or cfg.get("budget") or current[0] * groups[0] + current[1] * groups[1])
            slo = dict(p.get("slo") or {})
            obs = self._observe(name, cfg, notes)
            if obs is not None:
                qref = float(cfg.get("queue_ref", 2))
                model, rate, src = None, None, "trace"
                if kinds[0] in self.perf.devices and kinds[1] in self.perf.devices:
                    m, rate, src = rb.observed_mix(obs, mixes.from_spec(cfg.get("workload") or p.get("workload")))
                    model = pred.Model.build(self.perf, kinds[0], kinds[1], p["kv_transport"], m, slo)
                dec = rb.decide(current, budget, groups, obs, slo, model, known_rate=rate, known_source=src,
                                queue_ref=qref, margin=float(cfg.get("margin", 0.2)))
                want = dec.want
                pp, pd = rb.pressures(obs, current, slo, qref)
                fmt = lambda v: "-" if v is None else f"{v:.0f}"  # noqa: E731
                notes.append(f"{name}: TTFT p90 {fmt(obs.ttft_p90_ms)} ms, TPOT p90 {fmt(obs.tpot_p90_ms)} ms, "
                             f"pressure P {pp:.2f} D {pd:.2f}, target {want[0]}:{want[1]} at {current[0]}:{current[1]}"
                             f" ({dec.why})")
            else:
                m = mixes.from_spec(cfg.get("workload") or p.get("workload"))
                if not (kinds[0] in self.perf.devices and kinds[1] in self.perf.devices):
                    notes.append(f"{name}: no profile for {kinds}; not rebalanced")
                    continue
                need = rb.need_from_mix(m, self.perf.devices[kinds[0]], self.perf.devices[kinds[1]], slo)
                want = rb.target(current, budget, groups, need=need)
            got = self.hyst[name].propose(name, current, want)
            if got:
                self.overrides[name] = got
                notes.append(f"{name}: P:D {current[0]}:{current[1]} -> {got[0]}:{got[1]}")
            elif name not in self.overrides:
                self.overrides[name] = current
        return notes


def run_once(spec: dict, io, *, namespace: str, dry_run: bool, apply: bool = False,
             perf: Optional[prof.Profiles] = None, rebalancing: Optional[Rebalancing] = None) -> int:
    profiles = io.profiles()
    previous = document.parse(io.placement_configmap(namespace))
    notes = rebalancing.update(previous, {a.id: a for a in profiles}) if rebalancing else []
    entries, unplaced = plan(spec, profiles, io.unschedulable_nodes(), previous, perf=perf,
                             overrides=rebalancing.overrides if rebalancing else None)
    policy_name = spec.get("placement", "topology")
    doc, changed = document.build(entries, previous, policy_name)
    patch_list = []
    if apply:
        groups = {k: d.group for k, d in (perf.devices.items() if perf else [])}
        patch_list = applying.patches(doc, io.deployments(namespace), profiles, groups)
    if dry_run:
        out = doc.to_dict() if not apply else {"document": doc.to_dict(), "patches": patch_list}
        print(json.dumps(out, indent=2))
    else:
        if changed:
            io.apply(document.configmap(doc, namespace))
        for pt in patch_list:
            if pt["patch"]:
                io.patch_deployment(namespace, pt["name"], pt["patch"])
    state = "would write" if dry_run and changed else ("written" if changed else "unchanged")
    patched = sum(1 for pt in patch_list if pt["patch"])
    print(f"rm-controller: {len(profiles)} profiles, {len(entries)} decisions, generation "
          f"{doc.generation} {state}" + (f"; not placed: {', '.join(unplaced)}" if unplaced else "")
          + (f"; {patched} deployment patch(es) {'to apply' if dry_run else 'applied'}" if apply else "")
          + "".join(f"; rebalance {n}" for n in notes),
          file=sys.stderr)
    return 1 if unplaced else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rm-controller", description=__doc__.split("\n")[0])
    ap.add_argument("--spec", required=True, help="pools to place (YAML)")
    ap.add_argument("--namespace", default=None, help="namespace of airm-placement (default: spec, else llm-serving)")
    ap.add_argument("--once", action="store_true", help="place once and exit")
    ap.add_argument("--dry-run", action="store_true", help="print the document instead of writing it (implies --once)")
    ap.add_argument("--apply", action="store_true", help="also patch Deployments annotated with "
                                                         f"{applying.POOL_ANNOTATION} (with --dry-run: print the patches)")
    ap.add_argument("--rebalance", action="store_true", help="adjust P:D of pools that have a `rebalance:` section")
    ap.add_argument("--profiles", default=None, help="throughput profile table (default: spec `profiles`, else packaged)")
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between placements when not --once")
    ap.add_argument("--kube", choices=("auto", "kubectl", "client"), default="auto")
    args = ap.parse_args(argv)
    try:
        spec = load_spec(args.spec)
        namespace = args.namespace or spec.get("namespace") or "llm-serving"
        perf = prof.load(args.profiles or spec.get("profiles"))
        once = args.once or args.dry_run
        rebalancing = Rebalancing(spec, perf, once=once) if args.rebalance else None
        io = kube.connect(args.kube)
        kw = dict(namespace=namespace, apply=args.apply, perf=perf, rebalancing=rebalancing)
        if once:
            return run_once(spec, io, dry_run=args.dry_run, **kw)
        while True:
            try:
                run_once(spec, io, dry_run=False, **kw)
            except (RuntimeError, OSError) as e:  # a failed cluster or metrics call: report, try next round
                print(f"rm-controller: {e}", file=sys.stderr)
            time.sleep(args.interval)
    except (OSError, ValueError, RuntimeError, ContractError, yaml.YAMLError) as e:
        print(f"rm-controller: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
