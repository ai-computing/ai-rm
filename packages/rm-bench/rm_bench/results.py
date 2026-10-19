"""Per-request records -> rm-core Measurements, and the results/<run>.json format.

The file is a JSON list `[{"name", "value", "tags"}]`; every entry is validated against
`rm_core.metrics.METRICS`/`TAG_KEYS` before anything is written.
"""
from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rm_core import Measurement

COMPONENT = "rm-bench"


@dataclass(frozen=True)
class RequestRecord:
    ok: bool
    e2e_ms: float
    ttft_ms: float | None = None
    tpot_ms: float | None = None
    out_tokens: int = 0


def percentile(values: Sequence[float], p: float) -> float | None:
    """Linear-interpolated percentile (p in [0, 1]); None for no data. Same as loadgen/."""
    if not values:
        return None
    data = sorted(values)
    k = (len(data) - 1) * p
    f, c = math.floor(k), math.ceil(k)
    if f == c:
        return float(data[int(k)])
    return float(data[f] * (c - k) + data[c] * (k - f))


def make_tags(**tags: str | None) -> dict[str, str]:
    """component=rm-bench plus the given tags, dropping empty values."""
    out = {"component": COMPONENT}
    out.update({k: str(v) for k, v in tags.items() if v not in (None, "")})
    return out


def summarize(records: Sequence[RequestRecord], wall_s: float, tags: Mapping[str, str]) -> list[Measurement]:
    """Latency/throughput Measurements for one run. Percentiles with no samples are omitted, never 0."""
    ok = [r for r in records if r.ok]
    ttft = [r.ttft_ms for r in ok if r.ttft_ms is not None]
    tpot = [r.tpot_ms for r in ok if r.tpot_ms is not None]
    e2e = [r.e2e_ms for r in ok]
    wall_s = max(wall_s, 1e-9)
    values = {
        "tok_s": sum(r.out_tokens for r in ok) / wall_s,
        "req_s": len(ok) / wall_s,
        "ttft_p50_ms": percentile(ttft, 0.50),
        "ttft_p90_ms": percentile(ttft, 0.90),
        "ttft_p99_ms": percentile(ttft, 0.99),
        "tpot_p50_ms": percentile(tpot, 0.50),
        "tpot_p90_ms": percentile(tpot, 0.90),
        "tpot_p99_ms": percentile(tpot, 0.99),
        "e2e_p90_ms": percentile(e2e, 0.90),
    }
    return [Measurement(k, float(v), dict(tags)).validate() for k, v in values.items() if v is not None]


def to_json(measurements: Sequence[Measurement]) -> list[dict]:
    return [{"name": m.name, "value": m.value, "tags": dict(m.tags)} for m in measurements]


def from_json(items: Sequence[Mapping]) -> list[Measurement]:
    return [Measurement(i["name"], i["value"], dict(i.get("tags", {}))).validate() for i in items]


def write_measurements(path: str, measurements: Sequence[Measurement]) -> str:
    """Validate every Measurement, then write them as JSON to `path` (parents created)."""
    for m in measurements:
        m.validate()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        json.dump(to_json(measurements), f, indent=2)
        f.write("\n")
    return path
