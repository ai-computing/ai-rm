"""Discrete-event simulation of a prefill/decode placement under a trace's statistics.

    python -m rm_controller.sim --compare               # topology vs optimal on the reference card sets
    python -m rm_controller.sim --compare --format json
    python -m rm_controller.sim --episode               # the W5 rebalancer episode, old vs new rule (episode.py)

Requests are drawn from a workload mix (mix.py: the trace atlas's length quantiles; arrivals Poisson within
60 s windows whose rate follows an on/off burst model: one window in every round(2 x peak) runs at the
trace's 60 s peak/mean ratio, starting with the first, the rest at the rate that keeps the mean). Half the
requests arrive in peak windows, so every run, however short, meets a burst; a run shorter than one peak
window tests the peak rate alone. Sub-minute bursts (Azure code's 26x busiest second) are not modelled.

Serving model, from the same profiles the `optimal` policy reads (profiles.yaml):
- prefill: one request at a time per instance, FCFS from one queue, time = overhead + tokens / tok/s;
- KV handoff: the link's cost for the prompt's KV; decode instance = least loaded one the request fits;
- a role that mixes device types with routing weights (`optimal` with mixed roles) has one group per type:
  arrivals go to a prefill group by smooth weighted round-robin and queue FCFS within it, and a prefill
  output goes to a decode group the same way (among groups with an instance it fits), then to the least
  loaded instance of that group. Layouts without weights (topology, the baselines) keep the rules above;
- decode: continuous batching up to the TPOT-SLO batch (and KV capacity), every active request advances
  one token per TPOT(current batch).
A request meets the SLO when its TTFT (arrival to its first decode step) and its mean TPOT are within the
thresholds. Goodput is the highest mean rate at which >= 90 % of requests meet it.

The simulator checks the analytical model in `optimal` (queueing, bursts, KV fit, routing), not the
profile numbers themselves: both read the same table, so an error in a profile moves both alike.
"""
from __future__ import annotations

import argparse
import heapq
import json
import random
import sys
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from rm_core import Accelerator, Workload

from . import mix as mixes
from . import profiles as prof
from .optimal import OptimalPlacement, estimate
from .policy import RoleSpec, TopologyPlacement, kind_of

WINDOW_S = 60.0


@dataclass(frozen=True)
class Layout:
    name: str
    prefill: Tuple[Tuple[str, str], ...]       # (kind, node) per instance
    decode: Tuple[Tuple[str, str], ...]
    transport: str
    cards: int
    prefill_weights: Tuple[Tuple[str, float], ...] = ()    # routing weight per device type (mixed roles)
    decode_weights: Tuple[Tuple[str, float], ...] = ()

    def describe(self) -> str:
        def role(insts):
            if not insts:
                return "-"
            kinds = sorted({k for k, _ in insts})
            return "+".join(f"{sum(1 for k2, _ in insts if k2 == k)}x {k.split('.')[1]}" for k in kinds)
        nodes = len({n for _, n in self.prefill + self.decode})
        return f"P {role(self.prefill)} / D {role(self.decode)}, {self.transport}" + (f", {nodes} nodes" if nodes > 1 else "")


def layout(name: str, prefill_ids: Sequence[str], decode_ids: Sequence[str], transport: str,
           cards: Sequence[Accelerator], profiles: prof.Profiles, plan=None) -> Layout:
    """Instances from a decision's card ids: consecutive cards of one type and node, `group` at a time."""
    by_id = {a.id: a for a in cards}

    def instances(ids):
        out, pending = [], {}
        for i in ids:
            a = by_id[i]
            k = kind_of(a)
            g = profiles.devices[k].group if k in profiles.devices else 1
            pending.setdefault((k, a.node), []).append(i)
            if len(pending[(k, a.node)]) == g:
                out.append((k, a.node))
                pending[(k, a.node)] = []
        return tuple(out)

    e = plan.estimate if plan is not None else None
    return Layout(name, instances(prefill_ids), instances(decode_ids), transport,
                  len(set(prefill_ids) | set(decode_ids)), e.prefill_weights if e else (), e.decode_weights if e else ())


class _WRR:
    """Smooth weighted round-robin (nginx): deterministic, each group's share follows its weight."""

    def __init__(self, weights: Sequence[float]):
        self.w, self.cur = list(weights), [0.0] * len(weights)

    def pick(self, eligible: Sequence[int]) -> int:
        live = [g for g in eligible if self.w[g] > 0] or list(eligible)
        for g in live:
            self.cur[g] += self.w[g]
        best = max(live, key=lambda g: (self.cur[g], -g))
        self.cur[best] -= sum(self.w[g] for g in live)
        return best


def _groups(insts, weights) -> Tuple[List[int], List[float]]:
    """Group index per instance and weight per group: one group per weighted type, or a single group."""
    w = dict(weights)
    if len(w) < 2:
        return [0] * len(insts), [1.0]
    kinds = sorted(w)
    return [kinds.index(k) for k, _ in insts], [w[k] for k in kinds]


def estimate_layout(lay: Layout, m: mixes.Mix, slo: Dict[str, float], profiles: prof.Profiles) -> Optional[float]:
    """The `optimal` model's goodput for a layout with one device type per role (None otherwise)."""
    pk, dk = {k for k, _ in lay.prefill}, {k for k, _ in lay.decode}
    if len(pk) != 1 or len(dk) != 1:
        return None
    link = profiles.links[lay.transport]
    kv90 = profiles.kv_ms(link, m.input.quantile(0.9))
    return estimate(profiles.devices[pk.pop()], len(lay.prefill), profiles.devices[dk.pop()], len(lay.decode),
                    kv90, m, slo).goodput_rps


def requests(m: mixes.Mix, rate: float, n: int, seed: int = 1) -> List[Tuple[float, int, int]]:
    """(arrival s, prompt tokens, output tokens); the same seed gives the same lengths and burst windows at
    every rate, so rates compare on common random numbers."""
    r_len, r_arr = random.Random(seed), random.Random(seed + 1)
    peak = max(m.peak_ratio, 1.0)
    # deterministic windows: a random draw (the first version) left short, fast runs without any peak window
    period = max(2, round(2.0 * peak)) if peak > 1 else 1
    low = (1.0 - peak / period) / (1.0 - 1.0 / period) if period > 1 else 1.0
    out, t, w_end, w_rate, w = [], 0.0, 0.0, 0.0, 0
    for _ in range(n):
        e = r_arr.expovariate(1.0)
        while True:
            if t >= w_end:
                w_rate = rate * (peak if w % period == 0 else low)
                w_end, w = t + WINDOW_S, w + 1
            need = e / w_rate
            if t + need <= w_end:
                t += need
                break
            e -= (w_end - t) * w_rate
            t = w_end
        out.append((t, max(1, round(m.input.quantile(r_len.random()))), max(1, round(m.output.quantile(r_len.random())))))
    return out


@dataclass
class _Req:
    arrival: float
    prompt: int
    output: int
    admit: Optional[float] = None
    first: Optional[float] = None
    done: Optional[float] = None


@dataclass
class _Decode:
    prof: prof.DeviceProfile
    node: str
    cap: int
    active: Dict[int, float] = field(default_factory=dict)   # request index -> tokens left
    queue: deque = field(default_factory=deque)
    kv_used: int = 0
    last: float = 0.0
    version: int = 0


@dataclass(frozen=True)
class Result:
    rate: float
    attainment: float
    ttft_p90_ms: float
    tpot_p90_ms: float
    served: int
    measured: int


def _p90(xs: List[float]) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    return s[min(len(s) - 1, int(0.9 * (len(s) - 1) + 0.5))]


def simulate(lay: Layout, m: mixes.Mix, slo: Dict[str, float], rate: float, profiles: prof.Profiles,
             n: int = 3000, seed: int = 1, warmup: float = 0.1) -> Result:
    devices = profiles.devices
    link = profiles.links[lay.transport]
    tpot_slo, ttft_slo = slo.get("tpot_p90_ms"), slo.get("ttft_p90_ms")
    reqs = [_Req(*r) for r in requests(m, rate, n, seed)]
    p_of, p_w = _groups(lay.prefill, lay.prefill_weights)
    d_of, d_w = _groups(lay.decode, lay.decode_weights)
    pre_free = [[j for j in range(len(lay.prefill)) if p_of[j] == g] for g in range(len(p_w))]
    pre_q = [deque() for _ in p_w]
    p_rr, d_rr = _WRR(p_w), _WRR(d_w)
    decs = [_Decode(devices[k], node, max(1, devices[k].batch_for(tpot_slo))) for k, node in lay.decode]
    ev: list = []
    seq = 0

    def push(t, kind, a, b=None):
        nonlocal seq
        seq += 1
        heapq.heappush(ev, (t, seq, kind, a, b))

    for i, r in enumerate(reqs):
        push(r.arrival, "arrive", i)

    def start_prefill(t, g):
        while pre_q[g] and pre_free[g]:
            i, j = pre_q[g].popleft(), pre_free[g].pop(0)
            push(t + devices[lay.prefill[j][0]].prefill_ms(reqs[i].prompt) / 1000.0, "pdone", i, j)

    def advance(d: _Decode, t):
        if d.active:
            tau = d.prof.tpot_ms(len(d.active)) / 1000.0
            step = (t - d.last) / tau
            for i in d.active:
                d.active[i] -= step
        d.last = t

    def admit(d: _Decode, t):
        while d.queue and len(d.active) < d.cap:
            i = d.queue[0]
            need = reqs[i].prompt + reqs[i].output
            if d.kv_used + need > d.prof.kv_tokens:
                break
            d.queue.popleft()
            d.active[i] = float(reqs[i].output)
            d.kv_used += need
            reqs[i].admit = t

    def schedule(d: _Decode, k: int, t):
        d.version += 1
        for i in d.active:
            if reqs[i].first is None:
                reqs[i].first = t + d.prof.tpot_ms(len(d.active)) / 1000.0
        if d.active:
            tau = d.prof.tpot_ms(len(d.active)) / 1000.0
            push(t + max(0.0, min(d.active.values())) * tau, "dstep", k, d.version)

    while ev:
        t, _, kind, a, b = heapq.heappop(ev)
        if kind == "arrive":
            g = p_rr.pick(range(len(p_w))) if len(p_w) > 1 else 0
            pre_q[g].append(a)
            start_prefill(t, g)
        elif kind == "pdone":
            g = p_of[b]
            pre_free[g].append(b)
            pre_free[g].sort()
            start_prefill(t, g)
            r = reqs[a]
            node = lay.prefill[b][1]
            fits = [k for k, d in enumerate(decs) if d.prof.kv_tokens >= r.prompt + r.output
                    and (link.scope == "cluster" or d.node == node)]
            if fits and len(d_w) > 1:
                g = d_rr.pick(sorted({d_of[k] for k in fits}))
                fits = [k for k in fits if d_of[k] == g]
            if fits:   # else the request is never served and counts as a miss
                k = min(fits, key=lambda k: ((len(decs[k].active) + len(decs[k].queue)) / decs[k].cap, k))
                push(t + profiles.kv_ms(link, r.prompt) / 1000.0, "darrive", a, k)
        elif kind == "darrive":
            d = decs[b]
            advance(d, t)
            d.queue.append(a)
            admit(d, t)
            schedule(d, b, t)
        elif kind == "dstep":
            d = decs[a]
            if b != d.version:
                continue
            advance(d, t)
            for i in [i for i, left in d.active.items() if left <= 1e-6]:
                del d.active[i]
                d.kv_used -= reqs[i].prompt + reqs[i].output
                reqs[i].done = t
            admit(d, t)
            schedule(d, a, t)

    measured = reqs[int(len(reqs) * warmup):]
    ttfts, tpots, met = [], [], 0
    for r in measured:
        if r.done is None:
            continue
        ttft = (r.first - r.arrival) * 1000.0
        tpot = (r.done - r.admit) * 1000.0 / r.output
        ttfts.append(ttft)
        tpots.append(tpot)
        if (ttft_slo is None or ttft <= ttft_slo) and (tpot_slo is None or tpot <= tpot_slo):
            met += 1
    return Result(rate, met / max(1, len(measured)), _p90(ttfts), _p90(tpots), len(ttfts), len(measured))


def max_rate(lay: Layout, m: mixes.Mix, slo: Dict[str, float], profiles: prof.Profiles, *, target: float = 0.9,
             n: int = 3000, seed: int = 1, steps: int = 12) -> float:
    """Highest mean rate (req/s) at which `target` of requests meet the SLO; 0 if none does."""
    if not lay.prefill or not lay.decode:
        return 0.0
    ok = lambda rate: simulate(lay, m, slo, rate, profiles, n, seed).attainment >= target  # noqa: E731
    lo, hi = 0.0, 0.02
    while ok(hi):
        lo, hi = hi, hi * 2
        if hi > 1e4:
            return lo
    if lo == 0.0 and not ok(hi / 8):
        return 0.0
    for _ in range(steps):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


# -- reference comparison ------------------------------------------------------------------------

GB = 1 << 30


def card(node: str, kind: str, i: int) -> Accelerator:
    if kind == "furiosa.RNGD":
        return Accelerator(id=f"{node}/furiosa:{i}", node=node, vendor="furiosa", model="RNGD",
                           memory_bytes=48 * GB, memory_kind="hbm", peak_tflops={"bf16": 256.0},
                           peak_source="datasheet")
    if kind == "nvidia.A100":
        return Accelerator(id=f"{node}/nvidia:{i}", node=node, vendor="nvidia", model="A100", memory_bytes=80 * GB,
                           memory_kind="hbm", peak_tflops={"bf16": 312.0}, peak_source="datasheet")
    return Accelerator(id=f"{node}/rebellions:{i}", node=node, vendor="rebellions", model="ATOM",
                       memory_bytes=16 * GB, memory_kind="gddr", peak_tflops={"fp16": 32.0}, peak_source="datasheet")


def node_cards(node: str, rngd: int, atom: int, a100: int = 0) -> List[Accelerator]:
    return ([card(node, "nvidia.A100", i) for i in range(a100)] + [card(node, "furiosa.RNGD", i) for i in range(rngd)]
            + [card(node, "rebellions.ATOM", i) for i in range(atom)])


CARD_SETS = {
    "1 node: 2 RNGD + 4 ATOM": node_cards("node-a", 2, 4),
    "2 nodes: 2 x (2 RNGD + 4 ATOM)": node_cards("node-a", 2, 4) + node_cards("node-b", 2, 4),
}
TOPOLOGY_SPECS = {   # the two pools in examples/: the end-to-end run and the hetero P2P pool
    "topology, RNGD/RNGD shm (examples/spec.yaml)": ("shm", RoleSpec("furiosa.RNGD", 1), RoleSpec("furiosa.RNGD", 1)),
    "topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml)": ("p2p", RoleSpec("furiosa.RNGD", 1),
                                                              RoleSpec("rebellions.ATOM", 2)),
}


def layouts_for(cards: List[Accelerator], m: mixes.Mix, slo: Dict[str, float],
                profiles: prof.Profiles) -> List[Tuple[Layout, Optional[float]]]:
    """(layout, the `optimal` model's goodput estimate for it) for every policy row."""
    p, d = Workload(kind="prefill", model="m", slo=slo), Workload(kind="decode", model="m", slo=slo)
    rows = []
    for name, (transport, ps, ds) in TOPOLOGY_SPECS.items():
        dp, dd = TopologyPlacement().place_pd(p, d, cards, kv_transport=transport, prefill_spec=ps, decode_spec=ds)
        lay = layout(name, dp.accelerator_ids, dd.accelerator_ids, transport, cards, profiles)
        rows.append((lay, estimate_layout(lay, m, slo, profiles)))
    multi = len({a.node for a in cards}) > 1
    variants = [("optimal, per card", "per_card", False), ("optimal, max goodput", "goodput", False)]
    cross = sorted(n for n, l in profiles.links.items() if l.scope == "cluster")
    planned = [n for n in cross if not profiles.links[n].implemented]
    if multi and planned:   # what a cross-node link that does not exist yet would buy
        variants.append((f"optimal, max goodput + planned {', '.join(planned)}", "goodput", True))
    for n in cross if multi else ():   # the best layout on each cross-node link, chosen or not
        if profiles.links[n].implemented:
            variants.append((f"optimal, max goodput, {n} only", "goodput", False, n))
    return rows + optimal_rows(cards, m, slo, profiles, variants)


def optimal_rows(cards: List[Accelerator], m: mixes.Mix, slo: Dict[str, float], profiles: prof.Profiles,
                 variants: Sequence[tuple]) -> List[Tuple[Layout, Optional[float]]]:
    """`optimal` rows (mixed roles on, the default), each followed by a "one type per role" row (mixed roles
    off, the policy before mixed roles) when that chooses a different layout."""
    p, d = Workload(kind="prefill", model="m", slo=slo), Workload(kind="decode", model="m", slo=slo)
    rows = []
    for name, objective, planned, *only in variants:   # (name, objective, planned links[, kv_transport])
        transport = only[0] if only else "auto"
        got = []
        for mixed in (True, False):
            o = OptimalPlacement(profiles=profiles, mix=m.with_rate(None), objective=objective,
                                 allow_planned_links=planned, mixed_roles=mixed)
            dp, dd = o.place_pd(p, d, cards, kv_transport=transport)
            lay = layout(name if mixed else f"{name}, one type per role", dp.accelerator_ids, dd.accelerator_ids,
                         dp.kv_transport or "shm", cards, profiles, o.last_plan)
            got.append((lay, o.last_plan.estimate.goodput_rps if o.last_plan else None))
        rows.append(got[0])
        if got[1][0].describe() != got[0][0].describe():
            rows.append(got[1])
    return rows


def compare(n: int = 3000, seed: int = 1, profiles: Optional[prof.Profiles] = None,
            traces: Sequence[str] = tuple(mixes.TRACES)) -> List[dict]:
    profiles = profiles or prof.load()
    out = []
    for set_name, cards in CARD_SETS.items():
        for trace in traces:
            m, slo = mixes.from_trace(trace), mixes.trace_slo(trace)
            for lay, est in layouts_for(cards, m, slo, profiles):
                g = max_rate(lay, m, slo, profiles, n=n, seed=seed)
                out.append({"cards": set_name, "trace": trace, "policy": lay.name, "layout": lay.describe(),
                            "used": lay.cards, "goodput_rps": round(g, 3),
                            "goodput_per_card": round(g / lay.cards, 4) if lay.cards else 0.0,
                            "estimate_rps": None if est is None else round(est, 3),
                            "ttft_p90_ms": slo.get("ttft_p90_ms"), "tpot_p90_ms": slo.get("tpot_p90_ms")})
    return out


def markdown(rows: List[dict], est_label: str = "Model est.") -> str:
    lines = []
    for set_name in dict.fromkeys(r["cards"] for r in rows):
        lines += [f"**{set_name}**", "",
                  f"| Trace (SLO TTFT/TPOT p90) | Policy | Layout | Cards | Goodput req/s | req/s per card | {est_label} |",
                  "|---|---|---|--:|--:|--:|--:|"]
        for r in rows:
            if r["cards"] != set_name:
                continue
            slo = f"{r['ttft_p90_ms'] / 1000:g} s / {r['tpot_p90_ms']:g} ms"
            est = "" if r["estimate_rps"] is None else f"{r['estimate_rps']:.3f}"
            lines.append(f"| {r['trace']} ({slo}) | {r['policy']} | {r['layout']} | {r['used']} | "
                         f"{r['goodput_rps']:.3f} | {r['goodput_per_card']:.3f} | {est} |")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rm_controller.sim", description=__doc__.split("\n")[0])
    ap.add_argument("--compare", action="store_true", help="topology vs optimal on the reference card sets")
    ap.add_argument("--episode", action="store_true", help="replay W5's rebalancer episode (old vs new rule)")
    ap.add_argument("--trace-dir", default=None, help="episode: trace CSVs (default $RM_BENCH_TRACES)")
    ap.add_argument("--prefill-scale", type=float, default=None,
                    help="episode: prefill time under load / profile (default: the live run's 1.5)")
    ap.add_argument("--trace", action="append", choices=sorted(mixes.TRACES), help="limit to these traces")
    ap.add_argument("--requests", type=int, default=3000, help="requests per simulated run")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--profiles", default=None, help="throughput profile table (default: packaged)")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    args = ap.parse_args(argv)
    if args.episode:
        from . import episode
        serving = episode.LIVE_SERVING
        if args.prefill_scale is not None:
            serving = episode.Serving(serving.max_inflight, args.prefill_scale, serving.random_prefill)
        res = episode.episodes(prof.load(args.profiles), serving=serving, trace_dir=args.trace_dir, seed=args.seed)
        print(json.dumps(res, indent=2) if args.format == "json" else episode.markdown(res))
        return 0
    if not args.compare:
        ap.print_help()
        return 2
    rows = compare(args.requests, args.seed, prof.load(args.profiles), args.trace or tuple(mixes.TRACES))
    print(json.dumps(rows, indent=2) if args.format == "json" else markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
