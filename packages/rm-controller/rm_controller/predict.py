"""What a P:D split would do: each role's SLO pressure after a candidate move, from the profiles.

The rebalancer (rebalance.py) asks this module before it moves a card. Pressure is latency / SLO, as the
rebalancer measures it, here predicted with the `optimal` policy's queueing model (optimal.py) for one device
type per role:

    prefill  n instances, one queue (M/G/c, Erlang C with Allen-Cunneen, exponential tail):
             TTFT p90 = prefill(p90 prompt) + p90 wait;  pressure = TTFT p90 / ttft SLO
    decode   per instance lam / n arrivals. A link with `admit_blocking` (shm in rngd-pd with PD_PREFETCH=0)
             loads each request's KV inside the decode loop, so every admission stalls all active streams
             for the transfer: a share rho_a = lam/n x transfer of the instance's time goes to admissions
             and the step stretches to TPOT(b) / (1 - rho_a). b lanes (TPOT SLO and KV room, as optimal)
             each hold a request for mean output x step; a request that waits for a lane sees the wait in
             its TPOT, spread over its tokens (the client's (wall - TTFT) / (tokens - 1)):
             TPOT p90 = step + p90 lane wait / (p50 output - 1);  pressure = TPOT p90 / tpot SLO
    either   no SLO for the role: pressure = utilisation / 0.9

Load. The model is calibrated on the current split before it predicts another:
    fitted   a role over its SLO is fitted: its rate is the one at which the model gives the pressure the
             role shows now. Short bursts (Azure code at x3: 24 requests in one second, against a mean of
             1.9/s) and engine costs the profiles leave out show up here as a higher effective rate, which
             a mean rate would miss. One arrival stream feeds both roles, so the highest fitted rate is the
             pool's; a calm role (at or under its SLO) is predicted at that rate, capped by its own fit
             (the highest rate at which the model shows what it shows now), since its latency is mostly
             service time the profiles do not split out and only bounds its load.
    known    with no role to fit, the mean rate (gateway `airm_req_s`, vLLM's request counter, or tok/s over
             the mean answer, else the workload's trace rate) x the mix's 60 s peak/mean.
    coupling decode receives what prefill passes: min(arrivals, prefill capacity). A split with more prefill
             lets more of a burst through to decode, so decode's rate at a candidate split is its fitted rate
             scaled by how much more (or less) prefill would pass.

A move is predicted at those rates and the new instance counts, so the donor role's loss is part of the
prediction (W5's code x3 run: decode at 0.66 on two cards measured 3.1-3.8 on one; the linear estimate said 1.3).
Candidates that all saturate a role (infinite pressure) are ranked by their highest utilisation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import mix as mixes
from . import profiles as prof
from .optimal import PREFILL_UTIL, _wait_p90_ms, decode_batch

INF = math.inf


@dataclass(frozen=True)
class Model:
    """One pool's prefill and decode device types, KV link and mix."""
    prefill: prof.DeviceProfile
    decode: prof.DeviceProfile
    mix: mixes.Mix
    slo: Dict[str, float]
    admit_ms: float = 0.0           # decode stall per admission (blocking KV load), 0 = none
    kv_ms_p90: float = 0.0          # KV handoff outside the decode loop, p90 prompt (adds to TTFT)

    @classmethod
    def build(cls, perf: prof.Profiles, prefill_kind: str, decode_kind: str, link_name: str, m: mixes.Mix,
              slo: Dict[str, float]) -> "Model":
        link = perf.links.get(link_name)
        admit = kv90 = 0.0
        if link is not None:
            if link.admit_blocking:
                admit = perf.kv_ms(link, m.mean_input)
            else:
                kv90 = perf.kv_ms(link, m.input.quantile(0.9))
        return cls(perf.devices[prefill_kind], perf.devices[decode_kind], m, dict(slo), admit, kv90)

    # -- per role -------------------------------------------------------------------------------------

    def prefill_pressure(self, n: int, lam: float) -> float:
        pp, m = self.prefill, self.mix
        s = pp.prefill_ms(m.mean_input)
        mu = 1000.0 / s
        if lam >= n * mu:
            return INF
        slo = self.slo.get("ttft_p90_ms")
        if not slo:
            return lam / (n * mu) / PREFILL_UTIL
        cs2 = m.input.cv2 * ((s - pp.prefill_overhead_ms) / s) ** 2
        return (pp.prefill_ms(m.input.quantile(0.9)) + self.kv_ms_p90 + _wait_p90_ms(n, mu, lam, cs2)) / slo

    def decode_pressure(self, n: int, lam: float) -> float:
        dp, m = self.decode, self.mix
        b = decode_batch(dp, m, self.slo)
        if b < 1:
            return INF
        per = lam / n
        rho_a = per * self.admit_ms / 1000.0
        if rho_a >= 1.0:
            return INF
        step = dp.tpot_ms(b) / (1.0 - rho_a)
        mu = 1000.0 / (step * m.mean_output)
        if per >= b * mu:
            return INF
        slo = self.slo.get("tpot_p90_ms")
        if not slo:
            return (per / (b * mu) + rho_a) / PREFILL_UTIL
        wait = _wait_p90_ms(b, mu, per, m.output.cv2)
        return (step + wait / max(1.0, m.output.quantile(0.5) - 1.0)) / slo

    def capacity(self, role: str, n: int) -> float:
        """Arrival rate at which the role saturates (the model's pressure goes to infinity)."""
        if role == "prefill":
            return n * 1000.0 / self.prefill.prefill_ms(self.mix.mean_input)
        b = decode_batch(self.decode, self.mix, self.slo)
        if b < 1:
            return 0.0
        lanes = n * b * 1000.0 / (self.decode.tpot_ms(b) * self.mix.mean_output)
        hi = min(lanes, n * 1000.0 / self.admit_ms) if self.admit_ms else lanes
        return _bisect(lambda lam: self.decode_pressure(n, lam) < INF, 0.0, hi)

    def pressure(self, role: str, n: int, lam: float) -> float:
        return self.prefill_pressure(n, lam) if role == "prefill" else self.decode_pressure(n, lam)

    def fit(self, role: str, n: int, observed: float) -> float:
        """Rate at which the model gives `observed` pressure on n instances (0 if it gives more at no load)."""
        cap = self.capacity(role, n)
        if cap <= 0 or self.pressure(role, n, 0.0) >= observed:
            return 0.0
        return _bisect(lambda lam: self.pressure(role, n, lam) <= observed, 0.0, cap)


def _bisect(ok, lo: float, hi: float, steps: int = 60) -> float:
    """Largest x in [lo, hi) with ok(x), for a monotone ok."""
    for _ in range(steps):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


@dataclass(frozen=True)
class Candidate:
    split: Tuple[int, int]
    prefill: float                  # predicted pressure
    decode: float
    util: float                     # highest share of a role's capacity in use (ranks splits that all saturate)

    @property
    def worst(self) -> float:
        return max(self.prefill, self.decode)

    def key(self) -> Tuple[float, float]:
        return (self.worst, self.util)

    def describe(self) -> str:
        f = lambda v: "inf" if v == INF else f"{v:.2f}"  # noqa: E731
        return f"{self.split[0]}:{self.split[1]} P {f(self.prefill)} D {f(self.decode)}"


@dataclass(frozen=True)
class Prediction:
    arrivals: float                 # burst-effective arrival rate (req/s) the prediction assumes
    decode_now: float               # rate reaching decode at the current split
    source: str                     # which signal set the rate: prefill / decode fit, metrics or trace
    current: Candidate
    candidates: Tuple[Candidate, ...]

    @property
    def best(self) -> Candidate:
        cur = self.current.split
        return min(self.candidates, key=lambda c: (c.key(), c.split != cur, abs(c.split[0] - cur[0])))


def splits(budget_cards: int, groups: Tuple[int, int]) -> List[Tuple[int, int]]:
    gp, gd = groups
    out = []
    for n_p in range(1, budget_cards // gp + 1):
        n_d = (budget_cards - n_p * gp) // gd
        if n_d >= 1:
            out.append((n_p, n_d))
    return out


def predict(model: Model, current: Tuple[int, int], budget_cards: int, groups: Tuple[int, int],
            observed: Tuple[Optional[float], Optional[float]], known_rate: Optional[float] = None,
            known_source: str = "trace", over: float = 1.0) -> Prediction:
    """Predicted pressures of every split of the budget (module doc, "Load").

    `observed` is the (prefill, decode) pressure now, unfloored (None = no signal); `known_rate` the mean
    arrival rate (None = unknown). A role over `over` sets the rate it is fitted at. Below it, latency is
    mostly service time the profiles do not split out (download, KV save), which a fit reads as queueing,
    so there the fit is only an upper bound on the role's rate."""
    n_p, n_d = current
    known = (known_rate or 0.0) * max(model.mix.peak_ratio, 1.0)
    # a calm role that reads at or below the model's no-load pressure is fitted just above it: the highest
    # rate at which the model still shows (almost) no queueing bounds its load
    fits = [model.fit(role, n, max(o, 1.05 * model.pressure(role, n, 0.0))) if o is not None else None
            for role, n, o in (("prefill", n_p, observed[0]), ("decode", n_d, observed[1]))]
    hot = [f if f is not None and o is not None and o > over else 0.0 for f, o in zip(fits, observed)]
    # one arrival stream feeds both roles: a burst that shows on one role is there for the other too
    lam = max(hot)
    source = ("prefill fit" if lam == hot[0] else "decode fit") if lam else known_source
    lam = lam or known

    def bounded(rate: float, i: int) -> float:  # a calm role's own fit caps the rate it is predicted at
        return min(rate, fits[i]) if fits[i] else rate

    lam_p = hot[0] or bounded(lam, 0)
    # decode receives what prefill passes: at most prefill's capacity, so more prefill lets more of a burst through
    passed = lambda n: min(lam, model.capacity("prefill", n))  # noqa: E731
    dec_now = hot[1] or bounded(passed(n_p), 1)

    def cand(s):
        through = passed(s[0])
        ld = dec_now * through / passed(n_p) if passed(n_p) > 0 else through
        util = max(lam_p / max(model.capacity("prefill", s[0]), 1e-9), ld / max(model.capacity("decode", s[1]), 1e-9))
        return Candidate(s, model.prefill_pressure(s[0], lam_p), model.decode_pressure(s[1], ld), util)

    cands = tuple(cand(s) for s in splits(budget_cards, groups))
    cur = next((c for c in cands if c.split == tuple(current)), None) or cand(tuple(current))
    return Prediction(lam, dec_now, source, cur, cands)
