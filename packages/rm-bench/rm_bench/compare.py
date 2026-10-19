"""Baseline comparison: runs from several result files in one markdown table.

    rm-bench compare [LABEL=]results/a.json [LABEL=]results/b.json ... [--out table.md]

One row per run_id (a GuideLLM sweep gives several). The row label is LABEL when given, else the
run record's `deployment`, else the file name. Columns:

    SLO          slo_attainment_pct, and PASS/FAIL when the run was judged
    Goodput      requests meeting the SLO per second: the run record's `goodput_req_s` (rm-bench e2e,
                 GuideLLM with objectives), else req_s x attainment
    per card     goodput / cards (run record `cards`, else the `accelerators` Measurement)
    tok/J        output tokens / energy (run record), else tok_s / power_w
"""
from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field

from .results import read_run


@dataclass
class Row:
    label: str
    run_id: str
    values: dict[str, float] = field(default_factory=dict)
    record: dict = field(default_factory=dict)

    def get(self, name: str) -> float | None:
        return self.values.get(name)

    @property
    def cards(self) -> float | None:
        c = self.record.get("cards") or self.get("accelerators")
        return float(c) if c else None

    @property
    def goodput(self) -> float | None:
        g = self.record.get("goodput_req_s")
        if g is None and self.get("req_s") is not None and self.get("slo_attainment_pct") is not None:
            g = self.get("req_s") * self.get("slo_attainment_pct") / 100.0
        return g

    @property
    def tok_per_j(self) -> float | None:
        p = self.record.get("power") or {}
        if p.get("tok_per_j") is not None:
            return p["tok_per_j"]
        if self.get("tok_s") is not None and self.get("power_w"):
            return self.get("tok_s") / self.get("power_w")
        return None

    @property
    def peak_w(self) -> float | None:
        return (self.record.get("power") or {}).get("power_peak_w")


def _split(arg: str) -> tuple[str | None, str]:
    label, sep, path = arg.partition("=")
    if sep and label and not os.path.exists(arg):
        return label, path
    return None, arg


def load_rows(args: Sequence[str]) -> list[Row]:
    rows: list[Row] = []
    seen: set[str] = set()
    for arg in args:
        label, path = _split(arg)
        if path.endswith(".meta.json"):       # `results/*.json` also matches the run records
            path = path[: -len(".meta.json")] + ".json"
        if path in seen:
            continue
        seen.add(path)
        measurements, runs = read_run(path)
        by_run: dict[str, Row] = {}
        for m in measurements:
            rid = m.tags.get("run_id", "")
            row = by_run.get(rid)
            if row is None:
                record = runs.get(rid, {})
                name = label or record.get("deployment") or os.path.basename(path)
                row = by_run[rid] = Row(label=name, run_id=rid, record=record)
            row.values[m.name] = m.value
        rows += by_run.values()
    return rows


def _fmt(v, digits: int = 1) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and abs(v) < 10 ** -digits and v != 0:
        return f"{v:.3g}"
    return f"{v:,.{digits}f}"


def _slo(row: Row) -> str:
    att = row.get("slo_attainment_pct")
    passed = row.record.get("passed")
    parts = []
    if att is not None:
        parts.append(f"{att:.1f} %")
    if passed is not None:
        parts.append("PASS" if passed else "FAIL")
    return " ".join(parts) or "—"


def table(rows: Sequence[Row]) -> str:
    head = ("Deployment", "Run", "Source", "SLO", "TTFT p90 ms", "TPOT p90 ms", "tok/s",
            "Goodput req/s", "per card", "Power W (peak)", "tok/J")
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for r in rows:
        cards, goodput = r.cards, r.goodput
        per_card = goodput / cards if goodput is not None and cards else None
        power = r.get("power_w")
        power_s = "—" if power is None else _fmt(power) + (f" ({_fmt(r.peak_w)})" if r.peak_w else "")
        cells = (r.label, f"`{r.run_id}`", r.record.get("source") or "—", _slo(r),
                 _fmt(r.get("ttft_p90_ms")), _fmt(r.get("tpot_p90_ms")), _fmt(r.get("tok_s")),
                 _fmt(goodput, 2), _fmt(per_card, 2), power_s, _fmt(r.tok_per_j, 2))
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines) + "\n"
