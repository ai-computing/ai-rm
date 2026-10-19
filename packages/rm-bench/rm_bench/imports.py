"""Results of standard benchmarks -> rm-bench Measurements and run records.

    rm-bench import guidellm benchmarks.json   GuideLLM report (`guidellm benchmark ... --outputs json`);
                                               one run per benchmark of a sweep
    rm-bench import mlperf mlperf_log_summary.txt | mlperf_log_detail.txt
                                               MLPerf Inference LoadGen output (LLM, Server or Offline)

GuideLLM: every `benchmarks[]` entry (one rate of a sweep) becomes one run, run_id
`<report stem>-<index>-<strategy>`. Successful-request distributions give TTFT/TPOT/e2e
percentiles (`time_to_first_token_ms`, `time_per_output_token_ms`, `request_latency` in s), tok/s is
output tokens over the measured window (`scheduler_metrics.measure_*_time`; older reports
`run_stats`), req/s `requests_per_second.successful.mean`. `slo_attainment` (0..1, GuideLLM >= 0.7
with objectives configured) becomes `slo_attainment_pct`, `request_goodput` the goodput.

MLPerf: the summary's `Completed samples per second` / `Completed tokens per second` (Server) or
`Samples per second` / `Tokens per second` (Offline), `N percentile first token latency (ns)`
and `N percentile time to output token (ns)`; `ttft_latency (ns)` / `tpot_latency (ns)` are the
Server constraints. The detail log (`:::MLLOG {...}` lines) carries the same values under
`result_*`/`requested_*` keys. `Result is : VALID` is the pass verdict. MLPerf reports no per-request SLO share,
so no `slo_attainment_pct` is written.

With `slo` given (rm_core SLO_KEYS), each imported run is also judged against it from its
percentiles, as `rm-bench e2e` judges its own runs.
"""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping

from rm_core import Measurement

from .results import make_tags

PCTS = (50, 90, 99)


def _stem(path: str) -> str:
    base = os.path.basename(path)
    for ext in (".json", ".yaml", ".txt"):
        if base.endswith(ext):
            base = base[: -len(ext)]
    return base


def _check(slo: Mapping[str, float], values: Mapping[str, float | None]) -> dict[str, dict]:
    checks = {}
    for key, target in slo.items():
        if key == "tok_s_min":
            measured = values.get("tok_s")
            ok = measured is not None and measured >= target
        else:
            measured = values.get(key)
            ok = measured is not None and measured <= target
        checks[key] = {"target": target, "measured": measured, "ok": ok}
    return checks


def _measurements(values: Mapping[str, float | None], tags: Mapping[str, str]) -> list[Measurement]:
    return [Measurement(k, float(v), dict(tags)).validate() for k, v in values.items() if v is not None]


# --- GuideLLM -------------------------------------------------------------------------------------

def _dist(metrics: Mapping, name: str, status: str = "successful") -> Mapping:
    d = metrics.get(name) or {}
    d = d.get(status) if isinstance(d, Mapping) and status in d else d
    return d if isinstance(d, Mapping) else {}


def _pct(dist: Mapping, p: int, scale: float = 1.0) -> float | None:
    pcts = dist.get("percentiles") or {}
    v = pcts.get(f"p{p}")
    if v is None and p == 50:
        v = dist.get("median")       # GuideLLM < 0.4 keeps p50 as `median` only
    return None if v is None else float(v) * scale


def _strategy(bench: Mapping) -> str:
    cfg = bench.get("config") or {}
    st = cfg.get("strategy") or (bench.get("args") or {}).get("strategy") or {}
    kind = st.get("type_") or st.get("type") or "unknown"
    for key, fmt in (("rate", "{:g}rps"), ("streams", "{}streams"), ("max_concurrency", "c{}")):
        if st.get(key) is not None:
            return f"{kind}-" + fmt.format(st[key])
    return kind


def _window_s(bench: Mapping) -> float | None:
    for holder, a, b in ((bench.get("scheduler_metrics"), "measure_start_time", "measure_end_time"),
                         (bench.get("run_stats"), "start_time", "end_time"),
                         (bench, "start_time", "end_time")):
        if isinstance(holder, Mapping) and isinstance(holder.get(a), (int, float)) \
                and isinstance(holder.get(b), (int, float)) and holder[b] > holder[a]:
            return float(holder[b] - holder[a])
    d = bench.get("duration")
    return float(d) if isinstance(d, (int, float)) and d > 0 else None


def import_guidellm(path: str, *, model: str | None = None, deployment: str | None = None,
                    cards: int | None = None, slo: Mapping[str, float] | None = None
                    ) -> tuple[list[Measurement], dict[str, dict]]:
    with open(path, encoding="utf-8") as f:
        report = json.load(f)
    benches = report.get("benchmarks") if isinstance(report, Mapping) else None
    if not isinstance(benches, list) or not benches:
        raise ValueError(f"{path}: no `benchmarks` list (not a GuideLLM JSON report)")
    rcfg = report.get("config") or {}
    model = model or rcfg.get("model") or None
    slo = dict(slo or {})
    measurements: list[Measurement] = []
    runs: dict[str, dict] = {}
    for i, bench in enumerate(benches):
        m = bench.get("metrics") or {}
        strategy = _strategy(bench)
        run_id = f"{_stem(path)}-{i}-{strategy}"
        ttft = _dist(m, "time_to_first_token_ms")
        tpot = _dist(m, "time_per_output_token_ms")
        itl = _dist(m, "inter_token_latency_ms")
        e2e = _dist(m, "request_latency")
        out_tok = _dist(m, "output_token_count")
        window = _window_s(bench)
        tokens = out_tok.get("total_sum")
        if window and isinstance(tokens, (int, float)):
            tok_s = float(tokens) / window
        else:
            tok_s = _dist(m, "output_tokens_per_second").get("mean")
        values: dict[str, float | None] = {
            "tok_s": tok_s,
            "req_s": _dist(m, "requests_per_second").get("mean"),
            **{f"ttft_p{p}_ms": _pct(ttft, p) for p in PCTS},
            **{f"tpot_p{p}_ms": _pct(tpot, p) for p in PCTS},
            "e2e_p90_ms": _pct(e2e, 90, 1000.0),
        }
        attain = m.get("slo_attainment")
        if isinstance(attain, (int, float)):
            values = {"slo_attainment_pct": 100.0 * attain, **values}
        tags = make_tags(model=model, workload=f"guidellm-{strategy}", run_id=run_id)
        ms = _measurements(values, tags)
        if cards:
            ms.append(Measurement("accelerators", float(cards), dict(tags)).validate())
        measurements += ms
        totals = m.get("request_totals") or {}
        record = {"source": "guidellm", "deployment": deployment or "", "cards": cards, "model": model,
                  "workload": f"guidellm-{strategy}", "file": os.path.basename(path),
                  "sent": totals.get("total"), "failed": totals.get("errored"), "wall_s": window,
                  "out_tokens": tokens, "slo": slo,
                  **{f"itl_p{p}_ms": _pct(itl, p) for p in PCTS}}
        goodput = _dist(m, "request_goodput").get("mean")
        if goodput is not None:
            record["goodput_req_s"] = goodput
        if slo:
            record["checks"] = _check(slo, values)
            record["passed"] = all(c["ok"] for c in record["checks"].values())
        runs[run_id] = record
    return measurements, runs


# --- MLPerf LoadGen -------------------------------------------------------------------------------

_SUMMARY_LINE = re.compile(r"^\s*([^:]+?)\s*:\s*(.*?)\s*$")


def _parse_summary(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = _SUMMARY_LINE.match(line)
        if m and not line.lstrip().startswith(("*", "=")):
            out.setdefault(m.group(1), m.group(2))
    return out


def _parse_detail(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        if line.startswith(":::MLLOG"):
            try:
                ev = json.loads(line[len(":::MLLOG"):])
            except ValueError:
                continue
            out[ev.get("key")] = ev.get("value")
    return out


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _mlperf_values(text: str) -> dict:
    """Common fields from either LoadGen file."""
    if ":::MLLOG" in text:
        d = _parse_detail(text)
        ns = lambda k: None if _num(d.get(k)) is None else _num(d.get(k)) / 1e6  # noqa: E731
        validity = d.get("result_validity")
        return {
            "scenario": d.get("effective_scenario") or d.get("requested_scenario"),
            "valid": None if validity is None else str(validity).upper() == "VALID",
            "tok_s": _num(d.get("result_completed_tokens_per_second", d.get("result_tokens_per_second"))),
            "req_s": _num(d.get("result_completed_samples_per_sec", d.get("result_samples_per_second"))),
            **{f"ttft_p{p}_ms": ns(f"result_first_token_{p:.2f}_percentile_latency_ns") for p in PCTS},
            **{f"tpot_p{p}_ms": ns(f"result_time_per_output_token_{p:.2f}_percentile_ns") for p in PCTS},
            "targets": (ns("requested_server_ttft_latency"), ns("requested_server_tpot_latency")),
            "e2e_p90_ms": ns("result_90.00_percentile_latency_ns"),
            "sut": None,
        }
    s = _parse_summary(text)
    ns = lambda k: None if _num(s.get(k)) is None else _num(s.get(k)) / 1e6  # noqa: E731
    result = s.get("Result is")
    return {
        "scenario": s.get("Scenario"),
        "valid": None if result is None else result.upper() == "VALID",
        "tok_s": _num(s.get("Completed tokens per second", s.get("Tokens per second"))),
        "req_s": _num(s.get("Completed samples per second", s.get("Samples per second"))),
        **{f"ttft_p{p}_ms": ns(f"{p:.2f} percentile first token latency (ns)") for p in PCTS},
        **{f"tpot_p{p}_ms": ns(f"{p:.2f} percentile time to output token (ns)") for p in PCTS},
        "e2e_p90_ms": ns("90.00 percentile latency (ns)"),
        "targets": (ns("ttft_latency (ns)"), ns("tpot_latency (ns)")),
        "sut": s.get("SUT name"),
    }


def import_mlperf(path: str, *, model: str | None = None, deployment: str | None = None,
                  cards: int | None = None, slo: Mapping[str, float] | None = None
                  ) -> tuple[list[Measurement], dict[str, dict]]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    v = _mlperf_values(text)
    if v["scenario"] is None and v["tok_s"] is None:
        raise ValueError(f"{path}: not an MLPerf LoadGen summary or detail log")
    scenario = str(v["scenario"] or "unknown")
    run_id = f"{_stem(path)}-{scenario.lower()}"
    values = {k: v[k] for k in ("tok_s", "req_s", *(f"ttft_p{p}_ms" for p in PCTS),
                                *(f"tpot_p{p}_ms" for p in PCTS), "e2e_p90_ms")}
    tags = make_tags(model=model, workload=f"mlperf-{scenario.lower()}", run_id=run_id)
    measurements = _measurements(values, tags)
    if cards:
        measurements.append(Measurement("accelerators", float(cards), dict(tags)).validate())
    ttft_target, tpot_target = v["targets"]
    checks: dict[str, dict] = {}
    # LoadGen's own Server constraints are p99 bounds on TTFT and TPOT
    if ttft_target and values.get("ttft_p99_ms") is not None:
        checks["ttft_p99_ms"] = {"target": ttft_target, "measured": values["ttft_p99_ms"],
                                 "ok": values["ttft_p99_ms"] <= ttft_target}
    if tpot_target and values.get("tpot_p99_ms") is not None:
        checks["tpot_p99_ms"] = {"target": tpot_target, "measured": values["tpot_p99_ms"],
                                 "ok": values["tpot_p99_ms"] <= tpot_target}
    checks.update(_check(dict(slo or {}), values))
    if v["valid"] is not None:
        checks["mlperf_valid"] = {"target": "VALID", "measured": "VALID" if v["valid"] else "INVALID",
                                  "ok": v["valid"]}
    record = {"source": "mlperf", "deployment": deployment or "", "cards": cards, "model": model,
              "workload": f"mlperf-{scenario.lower()}", "file": os.path.basename(path),
              "scenario": scenario, "sut": v["sut"], "slo": dict(slo or {}), "checks": checks}
    if checks:
        record["passed"] = all(c["ok"] for c in checks.values())
    return measurements, {run_id: record}


IMPORTERS = {"guidellm": import_guidellm, "mlperf": import_mlperf}
