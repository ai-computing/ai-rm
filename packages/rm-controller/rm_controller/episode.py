"""Replay of a rebalancer episode: alternating load on a fixed card budget, the rebalancer in the loop.

    python -m rm_controller.sim --episode                 # W5's live run: code x3 / conversation x2, 3 RNGD
    python -m rm_controller.sim --episode --format json

What it replays (docs/baselines.md, "W5: the P:D rebalancer, live"): one pool of `budget` identical cards
behind the rngd-pd gateway, prefill and decode instances one card each, KV over `shm`. The load is a list
of phases, each a number of back-to-back replays of a trace window (Azure code at x3, Azure conversation at
x2, requests with prompt + answer <= 511 tokens, as rm-bench ran them). With the Azure 2023 CSVs under
$RM_BENCH_TRACES (`rm-bench traces fetch azure-2023-code azure-2023-conv`) the real arrival times are
replayed, sub-second bursts included; without them the windows' statistics drive mix.py's on/off burst
model, which has no sub-minute bursts (and the replay then says so).

Serving, sim.py's model plus what the live run had:
- client: at most `max_inflight` requests open (rm-bench's concurrency 64); the rest wait in the client, and
  a request still waiting when its replay's 300 s are up is never sent (a miss);
- prefill: the profile's prefill time x `prefill_scale`, from one FCFS queue, or, with `random_prefill`,
  from a queue per card that requests reach at random (several pods behind a Kubernetes Service);
- decode: continuous batching up to the TPOT-SLO batch; with a link marked `admit_blocking` (shm) each
  admission loads the request's KV inside the decode loop and stalls every active stream for the transfer;
- the views, as rngd-pd and rm-bench report them for non-streaming completions: the gateway's TTFT runs from
  the request reaching it to the end of prefill, the client's from the scheduled arrival (client wait
  included); TPOT = (finish - end of prefill) / (tokens - 1) in both, so a wait for a decode lane lands in TPOT.
A request meets the SLO when the client's TTFT and TPOT are within the thresholds; one unanswered after 300 s
(the client timeout) or in flight on a card that changes role is a miss.

Control loop, as the live run: every `interval_s` the rebalancer reads the gateway gauges over the last 512
finished requests (TTFT p90, TPOT p90, output tok/s) and proposes a split; hysteresis (band, hold, cooldown)
as configured. A change takes a card out of its role at once (what it holds is lost, as when a pod is
deleted) and the card serves its new role `startup_s` later (the live pods took about two minutes).
`old` is the linear rule (rebalance.target), `new` the predictive one (rebalance.decide), `none` a fixed split.
"""
from __future__ import annotations

import csv
import heapq
import math
import os
import random
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import mix as mixes
from . import predict as pred
from . import profiles as prof
from . import rebalance as rb
from .sim import requests as synthetic

TIMEOUT_S = 300.0
GAUGE_WINDOW = 512


@dataclass(frozen=True)
class Phase:
    name: str                       # e.g. "code x3"
    trace: str                      # azure-code | azure-conv
    speedup: float
    replays: int = 3
    duration_s: float = 300.0


# W5's live run: code x3 and conversation x2, three 300 s replays per phase
LIVE = (Phase("code x3", "azure-code", 3.0), Phase("conversation x2", "azure-conv", 2.0),
        Phase("code x3", "azure-code", 3.0), Phase("conversation x2", "azure-conv", 2.0))
FILES = {"azure-code": "azure-2023/AzureLLMInferenceTrace_code.csv",
         "azure-conv": "azure-2023/AzureLLMInferenceTrace_conv.csv"}


def trace_window(trace: str, speedup: float, duration_s: float, trace_dir: Optional[str],
                 max_total: int = 511, seed: int = 1) -> Tuple[List[Tuple[float, int, int]], str]:
    """(arrival s, prompt, answer) of one replay, and where it came from."""
    root = trace_dir or os.environ.get("RM_BENCH_TRACES") or str(Path.home() / ".cache/rm-bench/traces")
    path = Path(root) / FILES[trace]
    if path.exists():
        out, t0 = [], None
        with open(path, encoding="utf-8", newline="") as f:
            rows = csv.reader(f)
            next(rows)
            for ts, ctx, gen in rows:
                t = datetime.fromisoformat(ts[:26]).timestamp()
                t0 = t if t0 is None else t0
                s = (t - t0) / speedup
                if s > duration_s:
                    break
                if int(ctx) + int(gen) <= max_total:
                    out.append((s, int(ctx), int(gen)))
        return out, "trace"
    # no CSV: the clipped window's statistics (measured on 2026-10-20 from the same CSVs)
    stats = WINDOWS[(trace, speedup)]
    m = mixes.Mix(trace, mixes.Lengths.from_quantiles(*stats["input"]), mixes.Lengths.from_quantiles(*stats["output"]),
                  stats["rate_rps"], stats["peak_ratio"])
    n = int(stats["rate_rps"] * duration_s)
    reqs = synthetic(m, m.rate_rps, n, seed)
    return [(a, min(p, max_total - 1), max(1, min(o, max_total - p))) for a, p, o in reqs], "statistics"


# rm-bench's replay windows (first duration x speedup seconds of the trace, prompt + answer <= 511 tokens):
# rate, 60 s peak/mean, prompt and answer p50/p90/p99. Code x3: 579 requests, busiest second 24;
# conversation x2: 698 requests, busiest second 9.
WINDOWS = {
    ("azure-code", 3.0): {"rate_rps": 1.93, "peak_ratio": 1.98, "input": (164, 399, 486), "output": (14, 48, 124)},
    ("azure-conv", 2.0): {"rate_rps": 2.33, "peak_ratio": 1.76, "input": (373, 402, 417), "output": (93, 203, 238)},
}


@dataclass
class _Req:
    arrival: float
    prompt: int
    output: int
    replay: int
    start: Optional[float] = None       # sent by the client (it keeps at most `max_inflight` open)
    pdone: Optional[float] = None
    done: Optional[float] = None
    lost: bool = False


@dataclass
class _Card:
    role: Optional[str]
    epoch: int = 0
    next: Optional[str] = None                              # role it starts serving when ready
    prefill: Optional[int] = None                           # request in prefill
    active: Dict[int, float] = field(default_factory=dict)  # decode: request -> tokens left
    queue: deque = field(default_factory=deque)
    kv_used: int = 0
    last: float = 0.0
    ps: float = 0.0                                         # admission stall interval [ps, pe)
    pe: float = 0.0
    version: int = 0


@dataclass(frozen=True)
class Controller:
    rule: str                          # old | new | none (fixed split)
    band: float = 0.2
    hold: int = 3
    cooldown_s: float = 300.0
    interval_s: float = 60.0
    startup_s: float = 120.0
    margin: float = 0.2
    workload: Optional[dict] = None    # the pool's `workload:` (None: as the live spec, no trace stats)


@dataclass(frozen=True)
class Serving:
    """How the live system differed from the profiles' idle numbers (neutral by default)."""
    max_inflight: int = 64             # rm-bench --concurrency: requests open at once; the rest wait in the client
    prefill_scale: float = 1.0         # prefill time under load / the profile's (idle probe) time
    random_prefill: bool = False       # spread over prefill cards at random (a Service), not one shared queue


# The live run's serving: prefill under code x3's bursts took longer than the idle probe the profile comes from
# (client TTFT p90 5.0-5.8 s on one prefill card; the idle profile replays to 1.2 s, x1.5 to 3.2 s, x2 to 5.6 s,
# but x2 also makes 2P+1D the better split for code, which the live run contradicts), and several prefill pods
# were reached through a Kubernetes Service. x1.5 is the setting that keeps the live run's ordering
# (code: 1P+2D better than 2P+1D; conversation: 1P+2D far better) and still puts code's TTFT over the 2 s SLO.
LIVE_SERVING = Serving(max_inflight=64, prefill_scale=1.5, random_prefill=True)


def run(phases: Sequence[Phase], start: Tuple[int, int], ctl: Controller, profiles: prof.Profiles, *,
        serving: Serving = Serving(), kind: str = "furiosa.RNGD", link_name: str = "shm",
        slo: Optional[Dict[str, float]] = None, trace_dir: Optional[str] = None, seed: int = 1) -> dict:
    slo = dict(slo or {"ttft_p90_ms": 2000, "tpot_p90_ms": 100})
    dev, link = profiles.devices[kind], profiles.links[link_name]
    blocking = link.admit_blocking
    cap = max(1, dev.batch_for(slo.get("tpot_p90_ms")))
    budget = start[0] + start[1]
    # the load: replays back to back
    reqs: List[_Req] = []
    replays: List[dict] = []
    t0, source = 0.0, "trace"
    for no, ph in enumerate(phases):
        win, source = trace_window(ph.trace, ph.speedup, ph.duration_s, trace_dir, seed=seed)
        for _ in range(ph.replays):
            replays.append({"phase": ph.name, "no": no, "start": t0, "end": t0 + ph.duration_s})
            reqs += [_Req(t0 + a, p, o, len(replays) - 1) for a, p, o in win]
            t0 += ph.duration_s
    end = t0
    cards = [_Card("prefill") for _ in range(start[0])] + [_Card("decode") for _ in range(start[1])]
    split = tuple(start)                  # what the controller believes (its last decision)
    hyst = rb.Rebalancer(ctl.band, ctl.hold, ctl.cooldown_s, clock=lambda: now[0])
    now = [0.0]
    base_mix = mixes.from_spec(ctl.workload)
    pre_q: deque = deque()
    client: deque = deque()               # arrived, not sent yet (client concurrency)
    open_ = [0]
    parked: deque = deque()               # prefilled, no decode card serving
    finished: deque = deque(maxlen=GAUGE_WINDOW)
    log: List[dict] = []
    spans: List[Tuple[float, Tuple[int, int]]] = [(0.0, split)]
    ev: list = []
    seq = [0]

    def push(t, what, *args):
        seq[0] += 1
        heapq.heappush(ev, (t, seq[0], what, args))

    for i, r in enumerate(reqs):
        push(r.arrival, "arrive", i)
    if ctl.rule != "none":
        t = ctl.interval_s
        while t < end + ctl.interval_s:
            push(t, "round")
            t += ctl.interval_s

    def tau(c: _Card) -> float:
        return dev.tpot_ms(len(c.active)) / 1000.0

    def advance(c: _Card, t: float):
        if c.active:
            eff = (t - c.last) - max(0.0, min(t, c.pe) - max(c.last, c.ps))
            step = max(0.0, eff) / tau(c)
            for i in c.active:
                c.active[i] -= step
        c.last = t

    def admit(c: _Card, t: float):
        while c.queue and len(c.active) < cap:
            i = c.queue[0]
            need = reqs[i].prompt + reqs[i].output
            if c.kv_used + need > dev.kv_tokens:
                break
            c.queue.popleft()
            c.active[i] = float(reqs[i].output)
            c.kv_used += need
            if blocking:
                stall = profiles.kv_ms(link, reqs[i].prompt) / 1000.0
                if c.pe <= t:
                    c.ps, c.pe = t, t + stall
                else:
                    c.pe += stall

    def schedule(k: int, t: float):
        c = cards[k]
        c.version += 1
        if c.active:
            push(max(t, c.pe) + max(0.0, min(c.active.values())) * tau(c), "dstep", k, c.version, c.epoch)

    def start_prefill(t: float):
        for k, c in enumerate(cards):
            q = c.queue if serving.random_prefill else pre_q
            if c.role == "prefill" and c.prefill is None and q:
                i = q.popleft()
                c.prefill = i
                push(t + serving.prefill_scale * dev.prefill_ms(reqs[i].prompt) / 1000.0, "pdone", k, i, c.epoch)

    def to_decode(i: int, t: float):
        r = reqs[i]
        fits = [k for k, c in enumerate(cards) if c.role == "decode" and dev.kv_tokens >= r.prompt + r.output]
        if not fits:
            parked.append(i)
            return
        k = min(fits, key=lambda k: ((len(cards[k].active) + len(cards[k].queue)) / cap, k))
        push(t + (0.0 if blocking else profiles.kv_ms(link, r.prompt) / 1000.0), "darrive", k, i, cards[k].epoch)

    rng = random.Random(seed)

    def send(t: float):
        while client and open_[0] < serving.max_inflight:
            i = client.popleft()
            if t >= replays[reqs[i].replay]["end"]:
                continue                  # still queued when its run's time was up: unserved
            reqs[i].start = t
            open_[0] += 1
            pre = [k for k, c in enumerate(cards) if c.role == "prefill"]
            if serving.random_prefill and pre:
                cards[rng.choice(pre)].queue.append(i)
            else:
                pre_q.append(i)
        start_prefill(t)

    def close(i: int, t: float):
        open_[0] -= 1
        send(t)

    def gauges() -> rb.Observation:
        rs = [reqs[i] for i in finished]
        if not rs:
            return rb.Observation()
        ttft = [(r.pdone - r.start) * 1000.0 for r in rs]
        tpot = [(r.done - r.pdone) * 1000.0 / (r.output - 1) for r in rs if r.output > 1]
        span = max(r.done for r in rs) - min(r.arrival for r in rs)
        return rb.Observation(ttft_p90_ms=_pct(ttft, 90), tpot_p90_ms=_pct(tpot, 90) if tpot else None,
                              tok_s=sum(r.output for r in rs) / span if span > 0 else None)

    def move(t: float, want: Tuple[int, int]):
        cur_p = sum(1 for c in cards if (c.role or c.next) == "prefill")
        donor, taker = ("decode", "prefill") if want[0] > cur_p else ("prefill", "decode")
        for _ in range(abs(want[0] - cur_p)):
            k = max(k for k, c in enumerate(cards) if c.role == donor)
            c = cards[k]
            dropped = list(c.active) + list(c.queue) + ([c.prefill] if c.prefill is not None else [])
            cards[k] = _Card(None, epoch=c.epoch + 1, next=taker)
            for i in dropped:
                reqs[i].lost = True
                close(i, t)
            push(t + ctl.startup_s, "ready", k, cards[k].epoch)
        spans.append((t, tuple(sum(1 for x in cards if x.role == r) for r in ("prefill", "decode"))))

    while ev:
        t, _, what, args = heapq.heappop(ev)
        now[0] = t
        if what == "arrive":
            client.append(args[0])
            send(t)
        elif what == "pdone":
            k, i, epoch = args
            if cards[k].epoch != epoch:
                continue
            cards[k].prefill = None
            reqs[i].pdone = t
            start_prefill(t)
            to_decode(i, t)
        elif what == "darrive":
            k, i, epoch = args
            c = cards[k]
            if c.epoch != epoch or c.role != "decode":
                to_decode(i, t)
                continue
            advance(c, t)
            c.queue.append(i)
            admit(c, t)
            schedule(k, t)
        elif what == "dstep":
            k, version, epoch = args
            c = cards[k]
            if c.epoch != epoch or version != c.version:
                continue
            advance(c, t)
            for i in [i for i, left in c.active.items() if left <= 1e-6]:
                del c.active[i]
                c.kv_used -= reqs[i].prompt + reqs[i].output
                reqs[i].done = t
                finished.append(i)
                close(i, t)
            admit(c, t)
            schedule(k, t)
        elif what == "ready":
            k, epoch = args
            c = cards[k]
            if c.epoch != epoch:
                continue
            c.role, c.last = c.next, t
            spans.append((t, tuple(sum(1 for x in cards if x.role == r) for r in ("prefill", "decode"))))
            start_prefill(t)
            while parked:
                to_decode(parked.popleft(), t)
        elif what == "round":
            if t > end:
                continue
            obs = gauges()
            pp, pd = rb.pressures(obs, split, slo)
            if ctl.rule == "old":
                want, why = rb.target(split, budget, (1, 1), obs=obs, slo=slo), "linear"
            else:
                m, rate, src = rb.observed_mix(obs, base_mix)
                model = pred.Model.build(profiles, kind, kind, link_name, m, slo)
                d = rb.decide(split, budget, (1, 1), obs, slo, model, known_rate=rate, known_source=src,
                              margin=ctl.margin)
                want, why = d.want, d.why
            got = hyst.propose("pool", split, want)
            log.append({"t": round(t), "ttft_p90_ms": _r(obs.ttft_p90_ms), "tpot_p90_ms": _r(obs.tpot_p90_ms),
                        "pressure": [round(pp, 2), round(pd, 2)], "split": f"{split[0]}:{split[1]}",
                        "target": f"{want[0]}:{want[1]}", "moved": bool(got), "why": why})
            if got:
                move(t, got)
                split = got

    rows = []
    for n, rp in enumerate(replays):
        mine = [r for r in reqs if r.replay == n]
        ok, ttft, tpot = 0, [], []
        for r in mine:
            if r.lost or r.done is None or r.done - r.arrival > TIMEOUT_S:
                continue
            a = (r.pdone - r.arrival) * 1000.0
            b = (r.done - r.pdone) * 1000.0 / (r.output - 1) if r.output > 1 else 0.0
            ttft.append(a)
            tpot.append(b)
            ok += a <= slo["ttft_p90_ms"] and b <= slo["tpot_p90_ms"]
        layouts = [s for tt, s in spans if rp["start"] <= tt < rp["end"]]
        before = [s for tt, s in spans if tt < rp["start"]]
        shown = ([before[-1]] if before else []) + layouts
        rows.append({"replay": n + 1, "phase": rp["phase"], "phase_no": rp["no"],
                     "split": " → ".join(f"{p}P+{d}D" for p, d in shown),
                     "attainment": round(ok / max(1, len(mine)), 4), "requests": len(mine),
                     "ttft_p90_ms": _r(_pct(ttft, 90)), "tpot_p90_ms": _r(_pct(tpot, 90)),
                     "lost": sum(r.lost for r in mine)})
    return {"rule": ctl.rule, "start": f"{start[0]}:{start[1]}", "source": source, "replays": rows, "rounds": log}


def _pct(xs: List[float], q: float) -> Optional[float]:
    """numpy's default (linear) percentile, as rngd-pd's gateway computes its gauges."""
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q / 100.0
    f = math.floor(k)
    return s[f] if f + 1 >= len(s) else s[f] + (s[f + 1] - s[f]) * (k - f)


def _r(v: Optional[float]) -> Optional[float]:
    return None if v is None else round(v, 1)


def per_phase(result: dict) -> List[dict]:
    """Attainment over each phase (all its replays), and the splits it ran on."""
    out: Dict[int, dict] = {}
    for row in result["replays"]:
        p = out.setdefault(row["phase_no"], {"phase": row["phase"], "met": 0.0, "n": 0, "splits": []})
        p["met"] += row["attainment"] * row["requests"]
        p["n"] += row["requests"]
        for s in row["split"].split(" → "):
            if not p["splits"] or p["splits"][-1] != s:
                p["splits"].append(s)
    out = list(out.values())
    return [{"phase": p["phase"], "attainment": round(p["met"] / max(1, p["n"]), 4), "splits": p["splits"]}
            for p in out]


def episodes(profiles: prof.Profiles, *, serving: Serving = LIVE_SERVING, trace_dir: Optional[str] = None,
             workload: Optional[dict] = None, seed: int = 1) -> List[dict]:
    """The comparison `--episode` prints: W5's order (code first, from 1P+2D, as the live run) and the reverse
    (conversation first, from 2P+1D: the move the rebalancer must still make), each with the fixed splits,
    the old rule and the new one."""
    out = []
    for start, phases in (((1, 2), LIVE), ((2, 1), tuple(LIVE[1:]) + tuple(LIVE[:1]))):
        for rule, s in (("none", (1, 2)), ("none", (2, 1)), ("old", start), ("new", start)):
            r = run(phases, s, Controller(rule, workload=workload), profiles, serving=serving, trace_dir=trace_dir,
                    seed=seed)
            r["order"] = " / ".join(p.name for p in phases)
            out.append(r)
    return out


def markdown(results: Sequence[dict]) -> str:
    """Per-phase attainment of each run in an order, then each rebalancer's replays and moves."""
    lines = []
    for order in dict.fromkeys(r["order"] for r in results):
        runs = [r for r in results if r["order"] == order]
        phases = [p["phase"] for p in per_phase(runs[0])]
        lines += [f"**{order}** (arrivals from the {runs[0]['source']}): SLO attainment per phase", "",
                  "| Run | " + " | ".join(f"{k + 1}. {p}" for k, p in enumerate(phases)) + " | Moves |",
                  "|---|" + "--:|" * len(phases) + "--:|"]
        for r in runs:
            name = f"fixed {r['start']}" if r["rule"] == "none" else f"{r['rule']} rule from {r['start']}"
            cells = [f"{p['attainment']:.1%} ({' → '.join(p['splits'])})" if r["rule"] != "none"
                     else f"{p['attainment']:.1%}" for p in per_phase(r)]
            moves = sum(x["moved"] for x in r["rounds"])
            lines.append(f"| {name} | " + " | ".join(cells) + f" | {moves if r['rule'] != 'none' else '-'} |")
        lines.append("")
        for r in runs:
            if r["rule"] == "none":
                continue
            lines += [f"*{r['rule']} rule from {r['start']}*, per replay:", "",
                      "| Replay | Load | Split | SLO attainment | TTFT p90 | TPOT p90 | Lost |",
                      "|--:|---|---|--:|--:|--:|--:|"]
            for x in r["replays"]:
                lines.append(f"| {x['replay']} | {x['phase']} | {x['split']} | {x['attainment']:.1%} | "
                             f"{_fmt(x['ttft_p90_ms'])} | {_fmt(x['tpot_p90_ms'])} | {x['lost']} |")
            moves = [x for x in r["rounds"] if x["moved"]]
            holds = [x for x in r["rounds"] if x["why"].startswith("hold")]
            lines += ["", "Moves: " + ("; ".join(f"t={x['t']} s {x['split']} → {x['target']} ({x['why']})"
                                                for x in moves) if moves else "none")]
            if holds:
                h = holds[0]
                lines.append(f"First hold: t={h['t']} s, gauges TTFT {_fmt(h['ttft_p90_ms'])} / TPOT "
                             f"{_fmt(h['tpot_p90_ms'])}: {h['why']}")
            lines.append("")
    return "\n".join(lines)


def _fmt(v: Optional[float]) -> str:
    return "-" if v is None else f"{v:,.0f} ms"
