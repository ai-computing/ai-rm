"""rm-controller: place the pools a spec asks for and write the airm-placement ConfigMap.

    rm-controller --spec spec.yaml --dry-run      # print the document it would write
    rm-controller --spec spec.yaml --once         # write it if the decisions changed
    rm-controller --spec spec.yaml                # keep doing that every --interval seconds

Spec (YAML):

    namespace: llm-serving                 # where airm-placement lives (llm-d's namespace)
    pools:
      - pool: llama8b-pd-pool              # InferencePool name
        model: meta-llama/Llama-3.1-8B-Instruct
        kv_transport: shm                  # airm.kv_transports name
        slo: {tpot_p90_ms: 100}
        precision: bf16
        prefill: {accelerator: furiosa.RNGD, count: 1}
        decode:  {accelerator: furiosa.RNGD, count: 1}

Pools are placed in order; a card given to one pool is not offered to the next.
Exit status: 0 written or unchanged, 1 a pool could not be placed (the document still records why),
2 usage or cluster errors.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from typing import List, Tuple

import yaml
from rm_core import Workload

from . import document, kube
from .policy import ACCEL_LABEL, RoleSpec, TopologyPlacement


def load_spec(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}
    if not isinstance(spec.get("pools"), list) or not spec["pools"]:
        raise ValueError(f"{path}: 'pools' must be a non-empty list")
    for p in spec["pools"]:
        for key in ("pool", "model", "kv_transport", "prefill", "decode"):
            if key not in p:
                raise ValueError(f"{path}: pool {p.get('pool', '?')} is missing '{key}'")
    return spec


def plan(spec: dict, profiles, unschedulable) -> Tuple[List[dict], List[str]]:
    """Decision entries for every pool, and the pools that could not be placed."""
    policy = TopologyPlacement(unschedulable)
    used: set = set()
    entries, unplaced = [], []
    for p in spec["pools"]:
        slo = dict(p.get("slo") or {})
        precision = p.get("precision", "bf16")
        roles = {}
        for role in ("prefill", "decode"):
            r = p[role] or {}
            labels = {ACCEL_LABEL: r["accelerator"]} if r.get("accelerator") else {}
            roles[role] = (Workload(kind=role, model=p["model"], slo=slo, precision=precision, labels=labels),
                           RoleSpec(r.get("accelerator"), int(r.get("count", 1))))
        dp, dd = policy.place_pd(roles["prefill"][0], roles["decode"][0], profiles,
                                 kv_transport=p["kv_transport"], prefill_spec=roles["prefill"][1],
                                 decode_spec=roles["decode"][1], used=used)
        if not dp.accelerator_ids:
            unplaced.append(p["pool"])
        used.update(dp.accelerator_ids, dd.accelerator_ids)
        entries.append(document.decision_entry(p["pool"], roles["prefill"][0], dp))
        entries.append(document.decision_entry(p["pool"], roles["decode"][0], dd))
    return entries, unplaced


def run_once(spec: dict, io, *, namespace: str, dry_run: bool) -> int:
    profiles = io.profiles()
    entries, unplaced = plan(spec, profiles, io.unschedulable_nodes())
    previous = document.parse(io.placement_configmap(namespace))
    doc, changed = document.build(entries, previous, TopologyPlacement.name)
    if dry_run:
        print(json.dumps(doc, indent=2))
    elif changed:
        io.apply(document.configmap(doc, namespace))
    state = "would write" if dry_run and changed else ("written" if changed else "unchanged")
    print(f"rm-controller: {len(profiles)} profiles, {len(entries)} decisions, generation "
          f"{doc['generation']} {state}" + (f"; not placed: {', '.join(unplaced)}" if unplaced else ""),
          file=sys.stderr)
    return 1 if unplaced else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rm-controller", description=__doc__.split("\n")[0])
    ap.add_argument("--spec", required=True, help="pools to place (YAML)")
    ap.add_argument("--namespace", default=None, help="namespace of airm-placement (default: spec, else llm-serving)")
    ap.add_argument("--once", action="store_true", help="place once and exit")
    ap.add_argument("--dry-run", action="store_true", help="print the document instead of writing it (implies --once)")
    ap.add_argument("--interval", type=float, default=60.0, help="seconds between placements when not --once")
    ap.add_argument("--kube", choices=("auto", "kubectl", "client"), default="auto")
    args = ap.parse_args(argv)
    try:
        spec = load_spec(args.spec)
        namespace = args.namespace or spec.get("namespace") or "llm-serving"
        io = kube.connect(args.kube)
        if args.once or args.dry_run:
            return run_once(spec, io, namespace=namespace, dry_run=args.dry_run)
        while True:
            try:
                run_once(spec, io, namespace=namespace, dry_run=False)
            except RuntimeError as e:  # a failed cluster call: report and try again next round
                print(f"rm-controller: {e}", file=sys.stderr)
            time.sleep(args.interval)
    except (OSError, ValueError, RuntimeError, yaml.YAMLError) as e:
        print(f"rm-controller: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
