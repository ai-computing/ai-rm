"""P:D rebalancer: the prefill:decode instance split a pool should have, from load or trace statistics.

Signals, read from Prometheus text exposition (a serving pod's /metrics, or a file):

    vllm:num_requests_waiting               gauge per pod; the pod's role comes from a label
    vllm:time_to_first_token_seconds        histogram
    vllm:time_per_output_token_seconds      histogram (vllm:inter_token_latency_seconds also read)
    airm_ttft_p90_ms, airm_tpot_p90_ms      rngd-pd gateway gauges, used when the histograms are absent
    vllm:request_success_total              counter: arrival rate (windowed between reads)
    vllm:request_prompt_tokens, vllm:request_generation_tokens   histograms: mean prompt / answer length
    airm_req_s, airm_tok_s                  gateway gauges: request rate, output tokens/s (mean answer = ratio)

These are the vLLM names that Optimus Prime will expose (aicomp #45). Histogram quantiles are taken over
the window since the previous read when there is one, else over the counters' lifetime.

Pressure: each role's is the largest of (latency / its SLO) and (waiting per instance / `queue_ref`),
floored at 0.25; no signal = 1. Nothing moves while both pressures are <= 1 (SLOs met, queues short).

Rule (`decide`), when the profiles know both device types: predict.py predicts both roles' pressure at
every split of the card budget, at an arrival rate calibrated on what the roles show now and on the
observed rate and mix (metrics above, else the pool's `workload` trace statistics). The split with the
lowest predicted worst-role pressure is the target only if that is below the current split's by `margin`
(default 20 %); otherwise the split holds and the note says why. Without profiles (`target`), the rule
is the linear one: needed instances = current x pressure, and the split that minimises the worst
need/instance is the target. Without metrics, the need comes from a workload mix and the throughput
profiles (mean rate x peak over one instance's capacity).

Hysteresis on top of either: a target must differ from the current split by more than `band` in P:D
ratio and be proposed `hold` times in a row, `cooldown_s` after the last change, so the controller writes
a new generation only on a real, lasting change.
"""
from __future__ import annotations

import math
import re
import time
import urllib.request
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from . import mix as mixes
from . import predict as pred
from . import profiles as prof

ROLE_LABELS = ("role", "llm_d_ai_role", "llm-d.ai/role", "airm_role")
WAITING = "vllm:num_requests_waiting"
TTFT = "vllm:time_to_first_token_seconds"
TPOT = ("vllm:time_per_output_token_seconds", "vllm:inter_token_latency_seconds")
SUCCESS = "vllm:request_success_total"
PROMPT, ANSWER = "vllm:request_prompt_tokens", "vllm:request_generation_tokens"
FLOOR = 0.25

_SAMPLE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)')
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_.\-/]*)="((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Sample:
    name: str
    labels: Tuple[Tuple[str, str], ...]
    value: float

    def label(self, key: str, default: str = "") -> str:
        return dict(self.labels).get(key, default)


def parse_prometheus(text: str) -> List[Sample]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = _SAMPLE.match(line)
        if not m:
            continue
        try:
            value = float(m.group(3))
        except ValueError:
            continue
        labels = tuple(sorted((k, v.replace('\\"', '"')) for k, v in _LABEL.findall(m.group(2) or "")))
        out.append(Sample(m.group(1), labels, value))
    return out


def read_source(src: str, timeout_s: float = 10.0) -> str:
    """Text from an http(s) URL or a file."""
    if src.startswith(("http://", "https://")):
        with urllib.request.urlopen(src, timeout=timeout_s) as r:   # noqa: S310 (operator-given URL)
            return r.read().decode("utf-8", "replace")
    with open(src, encoding="utf-8") as f:
        return f.read()


def histogram_quantile(q: float, buckets: Iterable[Tuple[float, float]]) -> Optional[float]:
    """Prometheus' histogram_quantile over (upper bound, cumulative count) pairs."""
    b = sorted(buckets)
    if not b or b[-1][1] <= 0:
        return None
    rank = q * b[-1][1]
    prev_le, prev_c = 0.0, 0.0
    for le, c in b:
        if c >= rank:
            if math.isinf(le):
                return prev_le
            return prev_le + (le - prev_le) * ((rank - prev_c) / (c - prev_c) if c > prev_c else 1.0)
        prev_le, prev_c = le, c
    return prev_le


def _role(s: Sample, role_label: Optional[str]) -> str:
    for key in ((role_label,) if role_label else ROLE_LABELS):
        v = s.label(key)
        if v:
            return v
    return ""


def _buckets(samples: List[Sample], names: Tuple[str, ...]) -> Dict[float, float]:
    out: Dict[float, float] = {}
    for s in samples:
        if s.name in tuple(n + "_bucket" for n in names):
            le = float("inf") if s.label("le") in ("+Inf", "inf") else float(s.label("le", "nan"))
            out[le] = out.get(le, 0.0) + s.value
    return out


@dataclass(frozen=True)
class Observation:
    prefill_waiting: Optional[float] = None
    decode_waiting: Optional[float] = None
    ttft_p90_ms: Optional[float] = None
    tpot_p90_ms: Optional[float] = None
    rate_rps: Optional[float] = None        # arrivals (completions) per second
    mean_input: Optional[float] = None      # tokens per prompt
    mean_output: Optional[float] = None     # tokens per answer
    tok_s: Optional[float] = None           # output tokens per second (gives the rate with a mean answer)


def _total(samples: List[Sample], name: str) -> Optional[float]:
    vals = [s.value for s in samples if s.name == name]
    return sum(vals) if vals else None


def observe(samples: List[Sample], *, role_label: Optional[str] = None, role: Optional[str] = None,
            previous: Optional[List[Sample]] = None, elapsed_s: Optional[float] = None) -> Observation:
    """Signals from one scrape. `role` forces every sample's role (a per-role source); `previous` is the
    scrape before, `elapsed_s` seconds earlier, so latency quantiles, the rate and the mean lengths cover
    only the window in between."""
    waiting: Dict[str, float] = {}
    for s in samples:
        if s.name == WAITING:
            r = role or _role(s, role_label)
            waiting[r] = waiting.get(r, 0.0) + s.value

    def quant(names, airm):
        now = _buckets(samples, names)
        if previous:
            before = _buckets(previous, names)
            window = {le: c - before.get(le, 0.0) for le, c in now.items()}
            if max(window.values() or [0]) > 0:
                now = window
        v = histogram_quantile(0.9, now.items())
        if v is not None:
            return v * 1000.0
        gauges = [s.value for s in samples if s.name == airm]
        return max(gauges) if gauges else None

    def delta(name):
        now = _total(samples, name)
        if now is None or not previous:
            return now
        before = _total(previous, name)
        return now - before if before is not None and now >= before else now

    def mean(name):
        n, total = delta(name + "_count"), delta(name + "_sum")
        return total / n if n and total is not None else None

    rate = None
    done = delta(SUCCESS)
    if done is not None and previous and elapsed_s:
        rate = done / elapsed_s
    req_s, tok_s = _total(samples, "airm_req_s"), _total(samples, "airm_tok_s")
    rate = rate if rate is not None else req_s
    out = mean(ANSWER)
    if out is None and req_s and tok_s is not None:
        out = tok_s / req_s
    return Observation(waiting.get("prefill"), waiting.get("decode"),
                       quant((TTFT,), "airm_ttft_p90_ms"), quant(TPOT, "airm_tpot_p90_ms"),
                       rate, mean(PROMPT), out, tok_s)


def merge(a: Observation, b: Observation) -> Observation:
    pick = lambda x, y: y if x is None else (x if y is None else max(x, y))  # noqa: E731
    return Observation(*(pick(getattr(a, f), getattr(b, f)) for f in Observation.__dataclass_fields__))


def pressures(obs: Observation, current: Tuple[int, int], slo: Dict[str, float],
              queue_ref: float = 2.0, floor: Optional[float] = FLOOR) -> Tuple[Optional[float], Optional[float]]:
    """(prefill, decode) pressure. With the default floor a role without signal reads 1; with floor=None
    it reads None and nothing is floored (what predict.py fits)."""
    n_p, n_d = current

    def one(latency, slo_ms, waiting, n):
        sig = []
        if latency is not None and slo_ms:
            sig.append(latency / slo_ms)
        if waiting is not None:
            sig.append(waiting / (max(n, 1) * queue_ref))
        if floor is None:
            return max(sig) if sig else None
        return max(floor, max(sig)) if sig else 1.0

    return (one(obs.ttft_p90_ms, slo.get("ttft_p90_ms"), obs.prefill_waiting, n_p),
            one(obs.tpot_p90_ms, slo.get("tpot_p90_ms"), obs.decode_waiting, n_d))


def observed_mix(obs: Optional[Observation], base: mixes.Mix) -> Tuple[mixes.Mix, Optional[float], str]:
    """The mix to predict with (the workload's shapes, scaled to observed mean lengths), the known mean
    arrival rate and where it came from."""
    rate, src = base.rate_rps, ("trace" if base.rate_rps else "no known rate")
    if obs is None:
        return base, rate, src
    inp = base.input.scaled(obs.mean_input / base.mean_input) if obs.mean_input else base.input
    out = base.output.scaled(obs.mean_output / base.mean_output) if obs.mean_output else base.output
    if obs.rate_rps is not None:
        rate, src = obs.rate_rps, "metrics"
    elif obs.tok_s is not None:
        rate, src = obs.tok_s / out.mean, "metrics: tok/s over the mean answer"
    return mixes.Mix(base.name, inp, out, rate, base.peak_ratio), rate, src


@dataclass(frozen=True)
class Decision:
    want: Tuple[int, int]
    why: str
    prediction: Optional[pred.Prediction] = None


def decide(current: Tuple[int, int], budget_cards: int, groups: Tuple[int, int], obs: Observation,
           slo: Dict[str, float], model: Optional[pred.Model], *, known_rate: Optional[float] = None,
           known_source: str = "trace", queue_ref: float = 2.0, margin: float = 0.2) -> Decision:
    """Target split from an observation: the predicted best split if it beats the current one by `margin`
    (module doc); the linear `target` when there is no model (a device type without a profile)."""
    pp, pd = pressures(obs, current, slo, queue_ref)
    if pp <= 1.0 and pd <= 1.0:
        return Decision(current, "SLOs met")
    if model is None:
        return Decision(target(current, budget_cards, groups, obs=obs, slo=slo, queue_ref=queue_ref),
                        "linear rule (no profile)")
    raw = pressures(obs, current, slo, queue_ref, floor=None)
    p = pred.predict(model, current, budget_cards, groups, raw, known_rate, known_source)
    now, best = p.current, p.best
    at = f"at {p.arrivals:.2f} req/s ({p.source})"
    if best.split == now.split:
        others = sorted((c for c in p.candidates if c.split != now.split), key=lambda c: c.key())
        alt = f"; best other {others[0].describe()}" if others else ""
        return Decision(current, f"hold: no split predicted better than now {now.describe()}{alt} {at}", p)
    if math.isinf(now.worst) and math.isinf(best.worst):
        better = best.util < now.util * (1.0 - margin)
    else:
        better = best.worst < now.worst * (1.0 - margin)
    if not better:
        return Decision(current, f"hold: best {best.describe()} not {margin:.0%} better than now "
                                 f"{now.describe()} {at}", p)
    return Decision(best.split, f"predicted {now.describe()} -> {best.describe()} {at}", p)


def need_from_mix(m: mixes.Mix, pp: prof.DeviceProfile, dp: prof.DeviceProfile,
                  slo: Dict[str, float], util: float = 0.8) -> Tuple[float, float]:
    """Instances each role needs for the mix's peak rate at `util` utilisation."""
    if not m.rate_rps:
        raise ValueError(f"mix {m.name} has no rate; give rate_rps")
    lam = m.rate_rps * max(m.peak_ratio, 1.0)
    b = max(1, min(dp.batch_for(slo.get("tpot_p90_ms")),
                   int(dp.kv_tokens // max(1.0, m.mean_input + m.mean_output))))
    per_p = 1000.0 / pp.prefill_ms(m.mean_input)
    per_d = b * 1000.0 / (dp.tpot_ms(b) * m.mean_output)
    return lam / (per_p * util), lam / (per_d * util)


def split(need: Tuple[float, float], budget_cards: int, groups: Tuple[int, int] = (1, 1),
          current: Optional[Tuple[int, int]] = None) -> Tuple[int, int]:
    """Instances (prefill, decode) within `budget_cards` that minimise the worst need per instance."""
    gp, gd = groups
    best = None
    for n_p in range(1, budget_cards // gp + 1):
        n_d = (budget_cards - n_p * gp) // gd
        if n_d < 1:
            break
        worst = max(need[0] / n_p, need[1] / n_d)
        key = (round(worst, 9), 0 if current == (n_p, n_d) else 1, n_p)
        if best is None or key < best[0]:
            best = (key, (n_p, n_d))
    if best is None:
        raise ValueError(f"budget {budget_cards} cannot hold one prefill ({gp}) and one decode ({gd}) instance")
    return best[1]


def target(current: Tuple[int, int], budget_cards: int, groups: Tuple[int, int], *,
           obs: Optional[Observation] = None, slo: Optional[Dict[str, float]] = None,
           need: Optional[Tuple[float, float]] = None, queue_ref: float = 2.0) -> Tuple[int, int]:
    """Target split from an observation (needs `slo`) or from a precomputed need (trace statistics)."""
    if need is None:
        pp, pd = pressures(obs or Observation(), current, slo or {}, queue_ref)
        if pp <= 1.0 and pd <= 1.0:
            return current
        need = (current[0] * pp, current[1] * pd)
    return split(need, budget_cards, groups, current)


class Rebalancer:
    """Hysteresis over successive targets, per pool."""

    def __init__(self, band: float = 0.2, hold: int = 3, cooldown_s: float = 300.0,
                 clock: Callable[[], float] = time.monotonic):
        self.band, self.hold, self.cooldown_s, self.clock = band, hold, cooldown_s, clock
        self.state: Dict[str, dict] = {}

    def propose(self, pool: str, current: Tuple[int, int], want: Tuple[int, int]) -> Optional[Tuple[int, int]]:
        """`want` once it has held long enough and moved far enough, else None."""
        st = self.state.setdefault(pool, {"want": None, "streak": 0, "changed": None})
        ratio = lambda s: s[0] / s[1]  # noqa: E731
        if want == current or (abs(ratio(want) / ratio(current) - 1) <= self.band
                               and sum(want) == sum(current)):
            st.update(want=None, streak=0)
            return None
        st["streak"] = st["streak"] + 1 if st["want"] == want else 1
        st["want"] = want
        now = self.clock()
        if st["streak"] < self.hold or (st["changed"] is not None and now - st["changed"] < self.cooldown_s):
            return None
        st.update(want=None, streak=0, changed=now)
        return want
