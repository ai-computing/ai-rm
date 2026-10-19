"""Workload mix: request lengths, arrival rate and burstiness, from a spec or from trace statistics.

TRACES holds what rm-bench's trace atlas measured over the whole public traces (docs/workload-traces.md,
2026-10-19): mean rate, 60 s peak/mean, and input/output token p50/p90/p99. Lengths are rebuilt from those
quantiles as a piecewise log-linear distribution (p0 = p50/8, p100 = 1.25 x p99), so the means here are
reconstructions, not trace means. Per-trace SLOs are this package's choice (long-context Mooncake prompts
cannot meet a chat TTFT), not part of the traces.

Spec form (pool `workload:`):

    workload: {trace: azure-conv}                                   # statistics of a known trace
    workload: {trace: azure-code, rate_rps: 1.5}                    # ... at another rate
    workload: {mean_input_tokens: 900, mean_output_tokens: 150, rate_rps: 2, peak_ratio: 1.5}
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# name -> rate, 60 s peak / mean, input (p50, p90, p99), output (p50, p90, p99), SLO used by sim/optimal
TRACES: Dict[str, dict] = {
    "azure-conv": {"rate_rps": 5.5, "peak_ratio": 1.5, "input": (1020, 2735, 4142), "output": (129, 424, 601),
                   "slo": {"ttft_p90_ms": 2000, "tpot_p90_ms": 100}},
    "azure-code": {"rate_rps": 2.6, "peak_ratio": 4.1, "input": (1469, 5188, 7436), "output": (13, 55, 251),
                   "slo": {"ttft_p90_ms": 4000, "tpot_p90_ms": 100}},
    "burstgpt": {"rate_rps": 0.27, "peak_ratio": 69.0, "input": (262, 1824, 3389), "output": (36, 276, 1505),
                 "slo": {"ttft_p90_ms": 2000, "tpot_p90_ms": 100}},
    "mooncake-conv": {"rate_rps": 3.4, "peak_ratio": 1.2, "input": (6909, 27367, 85400), "output": (350, 597, 1119),
                      "slo": {"ttft_p90_ms": 15000, "tpot_p90_ms": 100}},
    "mooncake-tool": {"rate_rps": 6.7, "peak_ratio": 1.2, "input": (6346, 16806, 61661), "output": (30, 507, 898),
                      "slo": {"ttft_p90_ms": 15000, "tpot_p90_ms": 100}},
}


class Lengths:
    """Token-length distribution through (cumulative probability, tokens) points, log-linear in between."""

    def __init__(self, points: List[Tuple[float, float]]):
        self.points = sorted(points)
        self.us = [u for u, _ in self.points]
        n = 2000
        xs = [self.quantile((i + 0.5) / n) for i in range(n)]
        self.mean = sum(xs) / n
        self.cv2 = (sum((x - self.mean) ** 2 for x in xs) / n) / (self.mean ** 2) if self.mean else 0.0

    @classmethod
    def from_quantiles(cls, p50: float, p90: float, p99: float) -> "Lengths":
        return cls([(0.0, max(1.0, p50 / 8)), (0.5, p50), (0.9, p90), (0.99, p99), (1.0, p99 * 1.25)])

    @classmethod
    def constant(cls, value: float) -> "Lengths":
        return cls([(0.0, value), (1.0, value)])

    def quantile(self, u: float) -> float:
        u = min(max(u, 0.0), 1.0)
        i = max(1, min(bisect.bisect_left(self.us, u), len(self.points) - 1))
        (u0, x0), (u1, x1) = self.points[i - 1], self.points[i]
        if u1 == u0 or x0 == x1:
            return x1
        f = (u - u0) / (u1 - u0)
        return math.exp(math.log(x0) + f * (math.log(x1) - math.log(x0)))

    def cdf(self, x: float) -> float:
        if x < self.points[0][1]:
            return 0.0
        if x >= self.points[-1][1]:
            return 1.0
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if self.quantile(mid) <= x else (lo, mid)
        return lo


@dataclass(frozen=True)
class Mix:
    name: str
    input: Lengths
    output: Lengths
    rate_rps: Optional[float] = None    # mean arrival rate; None = unknown (optimal maximises goodput per card)
    peak_ratio: float = 1.0             # 60 s peak / mean; capacity is sized for the peak

    @property
    def mean_input(self) -> float:
        return self.input.mean

    @property
    def mean_output(self) -> float:
        return self.output.mean

    def fits(self, kv_tokens: int) -> float:
        """Share of requests whose prompt plus a mean answer fit `kv_tokens` of KV."""
        return self.input.cdf(kv_tokens - self.mean_output)

    def with_rate(self, rate_rps: Optional[float]) -> "Mix":
        return Mix(self.name, self.input, self.output, rate_rps, self.peak_ratio)


DEFAULT = Mix("default", Lengths.constant(1024), Lengths.constant(128))


def from_trace(name: str, rate_rps: Optional[float] = None) -> Mix:
    if name not in TRACES:
        raise ValueError(f"unknown trace {name!r}; known: {sorted(TRACES)}")
    t = TRACES[name]
    return Mix(name, Lengths.from_quantiles(*t["input"]), Lengths.from_quantiles(*t["output"]),
               t["rate_rps"] if rate_rps is None else rate_rps, t["peak_ratio"])


def from_spec(w: Optional[dict]) -> Mix:
    if not w:
        return DEFAULT
    rate = w.get("rate_rps")
    rate = None if rate is None else float(rate)
    if w.get("trace"):
        m = from_trace(str(w["trace"]), rate)
        return m if "peak_ratio" not in w else Mix(m.name, m.input, m.output, m.rate_rps, float(w["peak_ratio"]))
    try:
        mi, mo = float(w["mean_input_tokens"]), float(w["mean_output_tokens"])
    except KeyError as e:
        raise ValueError(f"workload needs 'trace' or mean_input_tokens and mean_output_tokens (missing {e})") from None
    return Mix("spec", Lengths.constant(mi), Lengths.constant(mo), rate, float(w.get("peak_ratio", 1.0)))


def trace_slo(name: str) -> Dict[str, float]:
    return dict(TRACES[name]["slo"]) if name in TRACES else {}
