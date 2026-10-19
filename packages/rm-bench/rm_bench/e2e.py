"""End-to-end scenario runner: drive a gateway with a scenario, judge its SLO, emit Measurements."""
from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from rm_core import Measurement
from rm_core.errors import ContractError
from rm_core.workload import SLO_KEYS

from . import client
from .results import RequestRecord, make_tags, percentile, summarize
from .scenario import Scenario

# Measurements `rm-bench e2e` reports (ai-rm.yaml `metrics`).
E2E_METRICS = ("slo_attainment_pct", "tok_s", "ttft_p90_ms", "tpot_p90_ms")


@dataclass
class E2EResult:
    scenario: str
    run_id: str
    model: str
    sent: int
    failed: int
    wall_s: float
    measurements: list[Measurement]
    slo: dict[str, float]
    checks: dict[str, dict] = field(default_factory=dict)  # slo key -> {target, measured, ok}

    @property
    def passed(self) -> bool:
        return all(c["ok"] for c in self.checks.values())


def new_run_id(scenario: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{scenario}-{stamp}-{uuid.uuid4().hex[:6]}"


def _meets(r: RequestRecord, slo: Mapping[str, float]) -> bool:
    """Per-request SLO: every latency bound in the SLO holds for this request."""
    if not r.ok:
        return False
    for key, target in slo.items():
        if key.startswith("ttft_") and (r.ttft_ms is None or r.ttft_ms > target):
            return False
        if key.startswith("tpot_") and r.tpot_ms is not None and r.tpot_ms > target:
            return False
        if key.startswith("e2e_") and r.e2e_ms > target:
            return False
    return True


def judge(records: list[RequestRecord], wall_s: float, slo: Mapping[str, float],
          max_error_pct: float) -> dict[str, dict]:
    """Aggregate SLO checks: each percentile bound on the run, tok_s_min, and the error budget."""
    ok = [r for r in records if r.ok]
    series = {"ttft": [r.ttft_ms for r in ok if r.ttft_ms is not None],
              "tpot": [r.tpot_ms for r in ok if r.tpot_ms is not None],
              "e2e": [r.e2e_ms for r in ok]}
    checks = {}
    for key, target in slo.items():
        if key == "tok_s_min":
            measured = sum(r.out_tokens for r in ok) / max(wall_s, 1e-9)
            checks[key] = {"target": target, "measured": measured, "ok": measured >= target}
            continue
        what, pct, _ = key.split("_")          # e.g. ttft_p90_ms
        measured = percentile(series[what], int(pct[1:]) / 100.0)
        checks[key] = {"target": target, "measured": measured,
                       "ok": measured is not None and measured <= target}
    err_pct = 100.0 * (len(records) - len(ok)) / max(1, len(records))
    checks["errors_pct"] = {"target": max_error_pct, "measured": err_pct,
                            "ok": bool(records) and err_pct <= max_error_pct}
    return checks


def run(scenario: Scenario, gateway: str, model: str | None = None, *,
        slo: Mapping[str, float] | None = None, run_id: str | None = None,
        kv_transport: str | None = None) -> E2EResult:
    """Run `scenario` against `gateway`. `slo` overrides the scenario's SLO when given."""
    if not gateway:
        raise ValueError("no gateway: pass --gateway or set LLMD_GATEWAY_URL")
    slo = dict(scenario.slo if slo is None else slo)
    unknown = set(slo) - set(SLO_KEYS)
    if unknown:
        raise ContractError(f"unknown SLO keys {sorted(unknown)}; allowed {SLO_KEYS}")
    run_id = run_id or new_run_id(scenario.name)
    url = client.chat_url(gateway)
    model = model or scenario.model or client.discover_model(gateway, scenario.timeout_s)
    schedule = [r for r in scenario.schedule() if r[0] < scenario.duration_s]

    t0 = time.perf_counter()
    stop_at = t0 + scenario.duration_s

    def one(offset: float, prompt_tokens: int, max_tokens: int) -> RequestRecord:
        # Still queued when the run's time is up: count it as a failed (unserved) request.
        if time.perf_counter() >= stop_at:
            return RequestRecord(ok=False, e2e_ms=(time.perf_counter() - t0 - offset) * 1000.0)
        return client.stream_chat(url, model, prompt_tokens, max_tokens, scenario.timeout_s,
                                  scheduled_at=t0 + offset)

    with ThreadPoolExecutor(max_workers=scenario.concurrency) as pool:
        futures = []
        for offset, prompt_tokens, max_tokens in schedule:
            delay = offset - (time.perf_counter() - t0)
            if delay > 0:
                time.sleep(delay)
            futures.append(pool.submit(one, offset, prompt_tokens, max_tokens))
        records = [f.result() for f in futures]
    wall_s = time.perf_counter() - t0

    tags = make_tags(model=model, workload=scenario.name, run_id=run_id, kv_transport=kv_transport)
    summary = {m.name: m for m in summarize(records, wall_s, tags)}
    measurements = [summary[n] for n in E2E_METRICS if n in summary]
    # With no SLO every successful request attains it, so this is the success rate.
    attained = 100.0 * sum(_meets(r, slo) for r in records) / max(1, len(records))
    measurements.insert(0, Measurement("slo_attainment_pct", attained, dict(tags)).validate())
    return E2EResult(scenario=scenario.name, run_id=run_id, model=model, sent=len(records),
                     failed=sum(not r.ok for r in records), wall_s=wall_s, measurements=measurements,
                     slo=slo, checks=judge(records, wall_s, slo, scenario.max_error_pct))
