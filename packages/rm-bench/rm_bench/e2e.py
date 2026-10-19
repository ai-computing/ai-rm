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

from . import client, traces
from .power import PowerSampler
from .results import RequestRecord, make_tags, percentile, summarize
from .scenario import API_KINDS, Scenario

# Measurements `rm-bench e2e` reports (ai-rm.yaml `metrics`).
E2E_METRICS = ("slo_attainment_pct", "tok_s", "ttft_p90_ms", "tpot_p90_ms")
# Added when configured: a power sampler (power_w, energy_j) and --cards (accelerators).
EVIDENCE_METRICS = ("power_w", "energy_j", "accelerators")


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
    record: dict = field(default_factory=dict)  # this run's entry in the run record (results.write_run)

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
        kv_transport: str | None = None, api: str | None = None,
        power: PowerSampler | None = None, deployment: str | None = None,
        cards: int | None = None) -> E2EResult:
    """Run `scenario` against `gateway`. `slo` overrides the scenario's SLO when given, `api`
    the scenario's request API (chat | completions). `power` samples power while requests run;
    `deployment` labels the run for `rm-bench compare` and `cards` (accelerators serving it) gives
    per-card goodput."""
    if not gateway:
        raise ValueError("no gateway: pass --gateway or set LLMD_GATEWAY_URL")
    slo = dict(scenario.slo if slo is None else slo)
    unknown = set(slo) - set(SLO_KEYS)
    if unknown:
        raise ContractError(f"unknown SLO keys {sorted(unknown)}; allowed {SLO_KEYS}")
    run_id = run_id or new_run_id(scenario.name)
    api = api or scenario.api
    if api not in API_KINDS:
        raise ValueError(f"api must be one of {API_KINDS}")
    url = client.chat_url(gateway) if api == "chat" else client.completions_url(gateway)
    send = {"chat": client.stream_chat, "completions": client.complete,
            "completions-stream": client.stream_completions}[api]
    model = model or scenario.model or client.discover_model(gateway, scenario.timeout_s)
    schedule = [r for r in scenario.schedule() if r[0] < scenario.duration_s]

    if power is not None:
        power.start()
    t0 = time.perf_counter()
    stop_at = t0 + scenario.duration_s

    from_trace = scenario.requests.get("source", "synthetic") == "trace"
    block_tokens = int((scenario.requests.get("trace") or {}).get("block_tokens", 512))

    def one(index: int, offset: float, prompt_tokens: int, max_tokens: int, blocks=None) -> RequestRecord:
        # Still queued when the run's time is up: count it as a failed (unserved) request.
        if time.perf_counter() >= stop_at:
            return RequestRecord(ok=False, e2e_ms=(time.perf_counter() - t0 - offset) * 1000.0)
        # Trace prompts must not share a prefix by accident; Mooncake ones share it where the trace did.
        prompt = (traces.prompt_for(prompt_tokens, blocks=blocks, block_tokens=block_tokens, salt=index)
                  if from_trace else None)
        return send(url, model, prompt_tokens, max_tokens, scenario.timeout_s, scheduled_at=t0 + offset,
                    prompt=prompt)

    with ThreadPoolExecutor(max_workers=scenario.concurrency) as pool:
        futures = []
        for index, (offset, prompt_tokens, max_tokens, *blocks) in enumerate(schedule):
            delay = offset - (time.perf_counter() - t0)
            if delay > 0:
                time.sleep(delay)
            futures.append(pool.submit(one, index, offset, prompt_tokens, max_tokens, *blocks))
        records = [f.result() for f in futures]
    wall_s = time.perf_counter() - t0
    out_tokens = sum(r.out_tokens for r in records if r.ok)
    psum = power.stop(window_s=wall_s, out_tokens=out_tokens) if power is not None else None

    tags = make_tags(model=model, workload=scenario.name, run_id=run_id, kv_transport=kv_transport)
    summary = {m.name: m for m in summarize(records, wall_s, tags)}
    measurements = [summary[n] for n in E2E_METRICS if n in summary]
    # With no SLO every successful request attains it, so this is the success rate.
    meets = sum(_meets(r, slo) for r in records)
    attained = 100.0 * meets / max(1, len(records))
    measurements.insert(0, Measurement("slo_attainment_pct", attained, dict(tags)).validate())
    if psum is not None:
        ptags = dict(tags, scope=psum.scope)
        measurements.append(Measurement("power_w", psum.mean_w, ptags).validate())
        measurements.append(Measurement("energy_j", psum.energy_j, ptags).validate())
    if cards:
        measurements.append(Measurement("accelerators", float(cards), dict(tags)).validate())
    checks = judge(records, wall_s, slo, scenario.max_error_pct)
    itl = [g for r in records if r.ok for g in r.itl_ms]
    record = {"source": "rm-bench e2e", "deployment": deployment or "", "cards": cards,
              "model": model, "workload": scenario.name, "api": api, "slo": dict(slo),
              "checks": checks, "passed": all(c["ok"] for c in checks.values()),
              "sent": len(records), "failed": sum(not r.ok for r in records), "wall_s": wall_s,
              "out_tokens": out_tokens, "goodput_req_s": meets / max(wall_s, 1e-9)}
    if itl:
        record.update({f"itl_p{p}_ms": percentile(itl, p / 100.0) for p in (50, 90, 99)})
    if psum is not None:
        record["power"] = psum.as_dict()
        record["power"]["errors"] = power.errors
    return E2EResult(scenario=scenario.name, run_id=run_id, model=model, sent=len(records),
                     failed=record["failed"], wall_s=wall_s, measurements=measurements,
                     slo=slo, checks=checks, record=record)
