"""rm-bench command line.

    rm-bench e2e --gateway $LLMD_GATEWAY_URL --scenario pd-smoke [--model M] [--out results/<run>.json]

Exit status: 0 when every SLO check passes, 1 when one fails, 2 on usage/setup errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests
import yaml

from . import e2e
from .results import to_json, write_measurements
from .scenario import load_scenario


def _print_result(res: e2e.E2EResult, out: str) -> None:
    print(f"scenario={res.scenario} run_id={res.run_id} model={res.model} "
          f"sent={res.sent} failed={res.failed} wall_s={res.wall_s:.2f}")
    for key, c in res.checks.items():
        measured = "n/a" if c["measured"] is None else f"{c['measured']:.2f}"
        print(f"  {'PASS' if c['ok'] else 'FAIL'}  {key}: measured={measured} target={c['target']}")
    print(json.dumps(to_json(res.measurements), indent=2))
    print(f"SLO {'PASS' if res.passed else 'FAIL'}  -> {out}")


def cmd_e2e(args) -> int:
    gateway = args.gateway or os.environ.get("LLMD_GATEWAY_URL", "")
    if not gateway:
        print("error: pass --gateway or set LLMD_GATEWAY_URL", file=sys.stderr)
        return 2
    scenario = load_scenario(args.scenario)
    run_id = e2e.new_run_id(scenario.name)
    res = e2e.run(scenario, gateway, args.model, run_id=run_id, kv_transport=args.kv_transport,
                  api=args.api)
    out = args.out or os.path.join("results", f"{run_id}.json")
    write_measurements(out, res.measurements)
    _print_result(res, out)
    return 0 if res.passed else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rm-bench")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("e2e", help="run an end-to-end scenario against an OpenAI-compatible gateway")
    p.add_argument("--gateway", default=None, help="gateway base URL (default: $LLMD_GATEWAY_URL)")
    p.add_argument("--scenario", required=True, help="scenario name in scenarios/ or a .yaml path")
    p.add_argument("--model", default=None, help="model id (default: scenario, else gateway /v1/models)")
    p.add_argument("--out", default=None, help="Measurement JSON path (default: results/<run_id>.json)")
    p.add_argument("--kv-transport", default=None, help="KV transport name under test, recorded as a tag")
    p.add_argument("--api", choices=("chat", "completions"), default=None,
                   help="request API (default: the scenario's api, else chat)")
    args = ap.parse_args(argv)
    try:
        return cmd_e2e(args)
    except (OSError, ValueError, TypeError, RuntimeError, yaml.YAMLError, requests.RequestException) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
