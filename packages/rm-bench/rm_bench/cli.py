"""rm-bench command line.

    rm-bench e2e --gateway $LLMD_GATEWAY_URL --scenario pd-smoke [--model M] [--out results/<run>.json]
                 [--deployment LABEL] [--cards N] [--power prom|cmd|none ...]
    rm-bench import guidellm|mlperf FILE [--out results/<name>.json] [--slo KEY=VALUE ...]
    rm-bench compare [LABEL=]RESULT.json ... [--out table.md]
    rm-bench traces fetch [NAME ...] [--dest DIR]       download real traces into $RM_BENCH_TRACES
    rm-bench traces stats SCENARIO|PATH [--limits ...]  rate, burstiness, lengths, prefix reuse, fit

Exit status: 0 when every SLO check passes, 1 when one fails, 2 on usage/setup errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests
import yaml
from rm_core.workload import SLO_KEYS

from . import compare, e2e, power, traces
from .imports import IMPORTERS
from .results import to_json, write_run
from .scenario import load_scenario


def _print_result(res: e2e.E2EResult, out: str) -> None:
    print(f"scenario={res.scenario} run_id={res.run_id} model={res.model} "
          f"sent={res.sent} failed={res.failed} wall_s={res.wall_s:.2f}")
    for key, c in res.checks.items():
        measured = "n/a" if c["measured"] is None else f"{c['measured']:.2f}"
        print(f"  {'PASS' if c['ok'] else 'FAIL'}  {key}: measured={measured} target={c['target']}")
    print(json.dumps(to_json(res.measurements), indent=2))
    rec = res.record
    if "itl_p90_ms" in rec:
        print(f"  ITL p50/p90/p99 ms: {rec['itl_p50_ms']:.1f} / {rec['itl_p90_ms']:.1f} / {rec['itl_p99_ms']:.1f}")
    pw = rec.get("power")
    if pw:
        tpj = "n/a" if pw["tok_per_j"] is None else f"{pw['tok_per_j']:.3f}"
        print(f"  power ({pw['source']}, scope={pw['scope']}, {pw['samples']} samples): "
              f"mean {pw['power_w']:.1f} W, peak {pw['power_peak_w']:.1f} W, {pw['energy_j']:.0f} J, {tpj} tok/J")
    print(f"SLO {'PASS' if res.passed else 'FAIL'}  -> {out}")


def _apply_trace_overrides(scenario, args) -> None:
    """--speedup/--start-s/--count/--duration adjust a scenario without editing its file."""
    if args.duration is not None:
        scenario.duration_s = float(args.duration)
    if args.count is not None:
        scenario.requests["count"] = int(args.count)
    trace = scenario.requests.get("trace")
    if isinstance(trace, dict):
        if args.speedup is not None:
            trace["speedup"] = float(args.speedup)
        if args.start_s is not None:
            trace["start_s"] = float(args.start_s)
        for k in ("max_prompt_tokens", "max_output_tokens", "max_total_tokens", "policy"):
            if getattr(args, k) is not None:
                trace[k] = getattr(args, k)
    elif any(getattr(args, k) is not None for k in ("speedup", "start_s", "max_prompt_tokens",
                                                       "max_output_tokens", "max_total_tokens", "policy")):
        raise ValueError("trace options apply to trace scenarios only")
    scenario.validate()


def cmd_e2e(args) -> int:
    gateway = args.gateway or os.environ.get("LLMD_GATEWAY_URL", "")
    if not gateway:
        print("error: pass --gateway or set LLMD_GATEWAY_URL", file=sys.stderr)
        return 2
    scenario = load_scenario(args.scenario)
    _apply_trace_overrides(scenario, args)
    sampler = power.make_sampler(args.power, url=args.power_url or os.environ.get("PROMETHEUS_URL"),
                                 query=args.power_query, command=args.power_cmd, regex=args.power_regex,
                                 interval_s=args.power_interval, scope=args.power_scope)
    run_id = e2e.new_run_id(scenario.name)
    res = e2e.run(scenario, gateway, args.model, run_id=run_id, kv_transport=args.kv_transport,
                  api=args.api, power=sampler, deployment=args.deployment, cards=args.cards)
    out = args.out or os.path.join("results", f"{run_id}.json")
    write_run(out, res.measurements, {run_id: res.record})
    _print_result(res, out)
    return 0 if res.passed else 1


def _parse_slo(items: list[str] | None) -> dict[str, float]:
    slo = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"--slo expects KEY=VALUE, got {item!r}")
        slo[key.strip()] = float(value)
    unknown = set(slo) - set(SLO_KEYS)
    if unknown:
        raise ValueError(f"unknown SLO keys {sorted(unknown)}; allowed {SLO_KEYS}")
    return slo


def cmd_import(args) -> int:
    measurements, runs = IMPORTERS[args.format](args.file, model=args.model, deployment=args.deployment,
                                                cards=args.cards, slo=_parse_slo(args.slo))
    stem = os.path.splitext(os.path.basename(args.file))[0]
    out = args.out or os.path.join("results", f"{args.format}-{stem}.json")
    write_run(out, measurements, runs)
    for run_id, rec in runs.items():
        verdict = {True: "PASS", False: "FAIL"}.get(rec.get("passed"), "not judged")
        print(f"{run_id}: {verdict}")
        for key, c in (rec.get("checks") or {}).items():
            print(f"  {'PASS' if c['ok'] else 'FAIL'}  {key}: measured={c['measured']} target={c['target']}")
    print(f"{len(measurements)} measurements, {len(runs)} run(s) -> {out}")
    return 0


def cmd_compare(args) -> int:
    text = compare.table(compare.load_rows(args.results))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
    print(text, end="")
    return 0


def cmd_traces_fetch(args) -> int:
    dest = traces.resolve(args.dest) if args.dest else None
    for path in traces.fetch(args.names or None, dest):
        print(path)
    print(f"attribution: {(dest or traces.traces_dir()) / 'ATTRIBUTION.md'}")
    return 0


def cmd_traces_stats(args) -> int:
    target = args.target
    if target.endswith((".csv", ".jsonl")):
        spec, count, duration = {"path": target}, args.count, args.duration
    else:
        sc = load_scenario(target)
        if sc.requests.get("source") != "trace":
            raise ValueError(f"scenario {sc.name} is not a trace scenario")
        spec = dict(sc.requests["trace"])
        count = args.count if args.count is not None else sc.requests.get("count")
        duration = args.duration if args.duration is not None else sc.duration_s
    for key in ("speedup", "start_s", "policy"):
        if getattr(args, key) is not None:
            spec[key] = getattr(args, key)
    limits = {k: getattr(args, k) for k in ("max_prompt_tokens", "max_output_tokens", "max_total_tokens")
              if getattr(args, k) is not None}
    if args.no_filter:  # look at the raw window, report how much of it fits the limits
        for k in ("max_prompt_tokens", "max_output_tokens", "max_total_tokens"):
            limits.setdefault(k, spec.pop(k, None))
        limits = {k: v for k, v in limits.items() if v is not None}
    else:
        spec.update(limits)
    window = traces.load(spec, count=count, duration_s=duration)
    print(json.dumps(traces.stats(window, limits=limits or None), indent=2))
    return 0


def _add_window_args(p) -> None:
    p.add_argument("--speedup", type=float, default=None, help="trace time compression (>1 faster)")
    p.add_argument("--start-s", dest="start_s", type=float, default=None, help="skip this much trace time")
    p.add_argument("--count", type=int, default=None, help="cap the number of requests")
    p.add_argument("--duration", type=float, default=None, help="schedule length in seconds")
    for k in ("max_prompt_tokens", "max_output_tokens", "max_total_tokens"):
        p.add_argument("--" + k.replace("_", "-"), dest=k, type=int, default=None,
                       help="limit of the target (trace requests over it are skipped or clipped)")
    p.add_argument("--policy", choices=traces.POLICIES, default=None, help="over-limit requests: skip | clip")


def _add_power_args(p) -> None:
    p.add_argument("--power", choices=power.SOURCES, default="none",
                   help="sample power during the run: prom (Prometheus query) | cmd (command output) | none")
    p.add_argument("--power-url", default=None, help="Prometheus base URL (default: $PROMETHEUS_URL)")
    p.add_argument("--power-query", default=None,
                   help=f"PromQL returning watts, summed (default: {power.DEFAULT_PROM_QUERY})")
    p.add_argument("--power-cmd", default=None, help="command printing watts (e.g. furiosa-smi info)")
    p.add_argument("--power-regex", default=None,
                   help=f"regex for the watts in --power-cmd output, matches summed (default: {power.DEFAULT_REGEX})")
    p.add_argument("--power-interval", type=float, default=1.0, help="sampling interval in seconds")
    p.add_argument("--power-scope", choices=power.SCOPES, default="card",
                   help="what the source measures: card (accelerators) or node (whole node)")


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
    p.add_argument("--deployment", default=None,
                   help="deployment label for compare (e.g. same-vendor-pd, vendor-pd, replication)")
    p.add_argument("--cards", type=int, default=None, help="accelerators serving the run (per-card goodput)")
    _add_power_args(p)
    _add_window_args(p)
    p.set_defaults(func=cmd_e2e)

    im = sub.add_parser("import", help="convert a GuideLLM report or MLPerf LoadGen log to rm-bench results")
    im.add_argument("format", choices=sorted(IMPORTERS))
    im.add_argument("file", help="GuideLLM benchmarks.json, or mlperf_log_summary.txt / mlperf_log_detail.txt")
    im.add_argument("--out", default=None, help="Measurement JSON path (default: results/<format>-<name>.json)")
    im.add_argument("--model", default=None, help="model tag (default: from the report when it has one)")
    im.add_argument("--deployment", default=None, help="deployment label for compare")
    im.add_argument("--cards", type=int, default=None, help="accelerators serving the run")
    im.add_argument("--slo", action="append", metavar="KEY=VALUE",
                    help="judge against an SLO bound (rm_core SLO_KEYS), repeatable")
    im.set_defaults(func=cmd_import)

    c = sub.add_parser("compare", help="markdown table of SLO attainment, goodput per card and tok/J")
    c.add_argument("results", nargs="+", help="result .json files, optionally LABEL=path")
    c.add_argument("--out", default=None, help="also write the table to this file")
    c.set_defaults(func=cmd_compare)

    t = sub.add_parser("traces", help="real request traces: download and inspect")
    tsub = t.add_subparsers(dest="traces_cmd", required=True)
    f = tsub.add_parser("fetch", help=f"download traces ({', '.join(traces.CATALOG)})")
    f.add_argument("names", nargs="*", help="catalog names (default: all)")
    f.add_argument("--dest", default=None, help="directory (default: $RM_BENCH_TRACES or ~/.cache/rm-bench/traces)")
    f.set_defaults(func=cmd_traces_fetch)
    st = tsub.add_parser("stats", help="rate, burstiness, lengths, prefix reuse of a trace window")
    st.add_argument("target", help="trace scenario name/.yaml, or a trace .csv/.jsonl path")
    st.add_argument("--no-filter", action="store_true",
                    help="keep every request; report the share that fits the limits instead of dropping")
    _add_window_args(st)
    st.set_defaults(func=cmd_traces_stats)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, TypeError, RuntimeError, yaml.YAMLError, requests.RequestException) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
