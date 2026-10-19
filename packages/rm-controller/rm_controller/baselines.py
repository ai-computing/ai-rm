"""Published placement algorithms, simplified, as baselines for `optimal` in the simulator (roadmap W6).

    python -m rm_controller.baselines --compare               # GPU-only, NPU-only and mixed card sets
    python -m rm_controller.baselines --compare --format json

Both read the same profiles and workload mix as `optimal` and produce a sim.Layout, so the simulator scores
every policy with one serving model. They are faithful in spirit, not reimplementations:

distserve   DistServe (Zhong et al., OSDI'24, Algorithm 1, "high node-affinity" placement): a homogeneous
            search. For each device type and node it sizes the two phases separately -- prefill goodput per
            instance from an M/D/1 queue whose p90 TTFT must meet the SLO, decode goodput per instance from
            the largest TPOT-SLO batch -- then picks the instance counts that maximise goodput per card, and
            the type with the best per-card goodput. Prefill and decode share a type and a node (DistServe
            keeps the KV handoff on NVLink). Left out: its intra-/inter-op parallelism search (a profile
            has one `group`), and the simulator it uses for attainment (closed-form queues here).
hexgen2     HexGen-2 (Jiang et al., ICLR'25): graph partition + max-flow over heterogeneous devices. Cards
            become instances (the partition: one instance = `group` cards of one type on one node; HexGen-2
            partitions by spectral clustering on link bandwidth and chooses the parallelism per group). Each
            instance takes a role; the flow network is source -> prefill instance (prefill req/s) -> decode
            instance (KV link req/s, where the link reaches) -> sink (decode req/s), and the max flow is the
            throughput. Roles start from a split by prefill/decode affinity and are refined by single flips
            and P/D swaps while the flow grows (HexGen-2's iterative refinement). Instances that carry no
            flow are dropped. Objective: throughput, then fewer cards. Left out: per-edge link choice (one
            transport per layout, as the simulator serves one), flow-proportional routing (the simulator
            dispatches to the least-loaded decode instance), and the parallelism search.

Helix (Mei et al., ASPLOS'25) also uses max-flow, with a MILP, but over layer-level pipeline placement; our
engines run whole-model instances, so its search space does not exist here and it is not modelled.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import math
import sys
from collections import deque
from typing import Dict, List, Optional, Sequence, Tuple

from rm_core import Accelerator, Workload

from . import mix as mixes
from . import profiles as prof
from . import sim
from .optimal import OptimalPlacement
from .policy import RoleSpec, TopologyPlacement, kind_of

ATTAINMENT = 0.9            # share of prompts a decode instance's KV must fit (as in `optimal`)
DECODE_UTIL = 0.9           # decode slots kept below saturation in the closed-form models

Instance = Tuple[str, str]   # (kind, node)


def instances(cards: Sequence[Accelerator], profiles: prof.Profiles) -> List[Instance]:
    """The partition: `group` cards of one profiled type on one node per instance."""
    count: Dict[Instance, int] = {}
    for a in cards:
        if kind_of(a) in profiles.devices:
            count[(kind_of(a), a.node)] = count.get((kind_of(a), a.node), 0) + 1
    out = []
    for (k, n), c in sorted(count.items()):
        out += [(k, n)] * (c // profiles.devices[k].group)
    return out


def _cards(insts: Sequence[Instance], profiles: prof.Profiles) -> int:
    return sum(profiles.devices[k].group for k, _ in insts)


def _links(profiles: prof.Profiles, planned: bool) -> List[prof.Link]:
    return sorted((l for l in profiles.links.values()
                   if l.scope in ("host", "cluster") and (l.implemented or planned)), key=lambda l: l.name)


def decode_capacity(d: prof.DeviceProfile, m: mixes.Mix, slo: Dict[str, float]) -> Tuple[int, float]:
    """(batch, requests/s) one decode instance sustains; (0, 0) when its KV or the TPOT SLO rule it out."""
    if m.fits(d.kv_tokens) < ATTAINMENT:
        return 0, 0.0
    b = min(d.batch_for(slo.get("tpot_p90_ms")), int(d.kv_tokens // max(1.0, m.mean_input + m.mean_output)))
    if b < 1:
        return 0, 0.0
    return b, DECODE_UTIL * b * 1000.0 / (d.tpot_ms(b) * m.mean_output)


def prefill_base_ms(p: prof.DeviceProfile, link: prof.Link, m: mixes.Mix, profiles: prof.Profiles) -> float:
    """p90 TTFT with no queueing: p90 prompt prefill + its KV handoff."""
    p90 = m.input.quantile(0.9)
    return p.prefill_ms(p90) + profiles.kv_ms(link, p90)


# -- DistServe-style ------------------------------------------------------------------------------

def distserve_prefill_rate(p: prof.DeviceProfile, link: prof.Link, m: mixes.Mix, slo: Dict[str, float],
                           profiles: prof.Profiles) -> float:
    """Highest req/s one prefill instance takes with p90 TTFT ~ base + M/D/1 mean wait within the SLO."""
    d = p.prefill_ms(m.mean_input) / 1000.0
    base = prefill_base_ms(p, link, m, profiles)
    ttft = slo.get("ttft_p90_ms")
    if ttft is None:
        return 0.9 / d
    if base > ttft:
        return 0.0
    lo, hi = 0.0, 1.0 / d
    for _ in range(50):
        lam = (lo + hi) / 2
        wait = lam * d * d / (2 * (1 - lam * d)) * 1000.0
        lo, hi = (lam, hi) if base + wait <= ttft else (lo, lam)
    return lo


def distserve(cards: Sequence[Accelerator], m: mixes.Mix, slo: Dict[str, float], profiles: prof.Profiles,
              planned: bool = False) -> Tuple[sim.Layout, float]:
    best_key, best = None, None
    insts = instances(cards, profiles)
    for link in _links(profiles, planned):
        if link.scope != "host":                       # high node-affinity: the KV handoff stays on the node
            continue
        for kind, node in sorted(set(insts)):
            if not link.serves(kind, kind):
                continue
            dev = profiles.devices[kind]
            n = sum(1 for i in insts if i == (kind, node))
            lp = distserve_prefill_rate(dev, link, m, slo, profiles)
            _, ld = decode_capacity(dev, m, slo)
            if lp <= 0 or ld <= 0:
                continue
            for n_p in range(1, n):
                n_d = n - n_p
                for nd in range(1, n_d + 1):
                    good = min(n_p * lp, nd * ld) / max(m.peak_ratio, 1.0)
                    used = (n_p + nd) * dev.group
                    key = (-round(good / used, 6), -round(good, 6), used, link.name, kind, node)
                    if best_key is None or key < best_key:
                        best_key, best = key, (link, kind, node, n_p, nd, good)
    if best is None:
        return sim.Layout("distserve", (), (), "shm", 0), 0.0
    link, kind, node, n_p, n_d, good = best
    g = profiles.devices[kind].group
    return sim.Layout("distserve", ((kind, node),) * n_p, ((kind, node),) * n_d, link.name, (n_p + n_d) * g), good


# -- HexGen-2-style -------------------------------------------------------------------------------

def max_flow(n: int, edges: Sequence[Tuple[int, int, float]], s: int, t: int) -> Tuple[float, List[float]]:
    """Edmonds-Karp on a small graph; returns (flow value, flow through each node)."""
    cap = [[0.0] * n for _ in range(n)]
    for u, v, c in edges:
        cap[u][v] += c
    flow = [[0.0] * n for _ in range(n)]
    total = 0.0
    while True:
        prev = [-1] * n
        prev[s] = s
        q = deque([s])
        while q and prev[t] < 0:
            u = q.popleft()
            for v in range(n):
                if prev[v] < 0 and cap[u][v] - flow[u][v] > 1e-12:
                    prev[v] = u
                    q.append(v)
        if prev[t] < 0:
            break
        push, v = math.inf, t
        while v != s:
            push = min(push, cap[prev[v]][v] - flow[prev[v]][v])
            v = prev[v]
        v = t
        while v != s:
            flow[prev[v]][v] += push
            flow[v][prev[v]] -= push
            v = prev[v]
        total += push
    through = [sum(max(0.0, flow[u][v]) for v in range(n)) for u in range(n)]
    return total, through


class _Net:
    """Per-instance capacities for one link; `solve(roles)` gives the max flow of a role assignment."""

    def __init__(self, insts: List[Instance], link: prof.Link, m: mixes.Mix, slo: Dict[str, float],
                 profiles: prof.Profiles):
        self.insts, self.link = insts, link
        ttft = slo.get("ttft_p90_ms")
        kv_bytes = max(m.mean_input * profiles.kv_bytes_per_token, link.min_bytes)
        self.link_rps = math.inf if link.gb_s <= 0 else link.gb_s * 1e9 / kv_bytes
        self.pre, self.dec = [], []
        for k, _ in insts:
            dev = profiles.devices[k]
            ok = ttft is None or prefill_base_ms(dev, link, m, profiles) <= ttft
            self.pre.append(1000.0 / dev.prefill_ms(m.mean_input) if ok else 0.0)
            self.dec.append(decode_capacity(dev, m, slo)[1])

    def reaches(self, i: int, j: int) -> bool:
        (ki, ni), (kj, nj) = self.insts[i], self.insts[j]
        return self.link.serves(ki, kj) and (self.link.scope == "cluster" or ni == nj)

    def solve(self, roles: Sequence[str]) -> Tuple[float, List[float]]:
        n = len(self.insts)
        s, t = n, n + 1
        edges = []
        for i, r in enumerate(roles):
            if r == "P":
                edges.append((s, i, self.pre[i]))
                edges += [(i, j, self.link_rps) for j, rj in enumerate(roles) if rj == "D" and self.reaches(i, j)]
            elif r == "D":
                edges.append((i, t, self.dec[i]))
        return max_flow(n + 2, edges, s, t)


def _refine(net: _Net, roles: List[str]) -> Tuple[float, List[str]]:
    """Single-instance flips and P/D swaps while the flow grows by more than 0.1 %."""
    best, _ = net.solve(roles)
    improved = True
    while improved:
        improved = False
        moves = [[i] for i in range(len(roles))] + [[i, j] for i in range(len(roles)) for j in range(i + 1, len(roles))
                                                    if roles[i] != roles[j]]
        for mv in moves:
            cand = list(roles)
            for i in mv:
                cand[i] = "D" if cand[i] == "P" else "P"
            f, _ = net.solve(cand)
            if f > best * 1.001 + 1e-9:
                best, roles, improved = f, cand, True
                break
    return best, roles


def hexgen2(cards: Sequence[Accelerator], m: mixes.Mix, slo: Dict[str, float], profiles: prof.Profiles,
            planned: bool = False) -> Tuple[sim.Layout, float]:
    insts = instances(cards, profiles)
    best_key, best = None, None
    for link in _links(profiles, planned):
        net = _Net(insts, link, m, slo, profiles)
        # initial partition: most prefill-leaning instances (prefill rate / decode rate) first
        order = sorted(range(len(insts)), key=lambda i: -(net.pre[i] / net.dec[i] if net.dec[i] else math.inf))
        start, start_flow = None, -1.0
        for k in range(1, len(insts)):
            roles = ["D"] * len(insts)
            for i in order[:k]:
                roles[i] = "P"
            f, _ = net.solve(roles)
            if f > start_flow:
                start, start_flow = roles, f
        if start is None:
            continue
        flow, roles = _refine(net, start)
        if flow <= 0:
            continue
        _, through = net.solve(roles)
        keep = [i for i in range(len(insts)) if through[i] > 1e-9]
        used = _cards([insts[i] for i in keep], profiles)
        key = (-round(flow, 6), used, link.name)
        if best_key is None or key < best_key:
            # prefill instances fastest first: the simulator dispatches to the lowest free index
            pre = sorted((i for i in keep if roles[i] == "P"), key=lambda i: -net.pre[i])
            dec = [i for i in keep if roles[i] == "D"]
            best_key = key
            best = (sim.Layout("hexgen2", tuple(insts[i] for i in pre), tuple(insts[i] for i in dec), link.name, used),
                    flow / max(m.peak_ratio, 1.0))
    if best is None:
        return sim.Layout("hexgen2", (), (), "shm", 0), 0.0
    return best


# -- comparison -----------------------------------------------------------------------------------

CARD_SETS = {
    "GPU only: 1 node, 4 A100": sim.node_cards("node-g", 0, 0, a100=4),
    "NPU only: 1 node, 2 RNGD + 4 ATOM": sim.node_cards("node-a", 2, 4),
    "Mixed: 1 node, 2 A100 + 2 RNGD + 4 ATOM": sim.node_cards("node-m", 2, 4, a100=2),
}
# topology's spec per set: no type filter (prefill takes the highest peak, decode the most memory), the KV path
# the hardware has (cuda-ipc between GPUs, the measured shm otherwise)
TOPOLOGY_TRANSPORT = {"GPU only: 1 node, 4 A100": "cuda-ipc"}


def comparable(profiles: prof.Profiles) -> prof.Profiles:
    """Profiles with GPU links counted as available: upstream vLLM has them, ai-rm has no plugin."""
    links = {n: (dataclasses.replace(l, implemented=True) if any(p.startswith("nvidia.") for p in l.pairs) else l)
             for n, l in profiles.links.items()}
    return dataclasses.replace(profiles, links=links)


def layouts_for(set_name: str, cards: List[Accelerator], m: mixes.Mix, slo: Dict[str, float],
                profiles: prof.Profiles) -> List[Tuple[sim.Layout, Optional[float]]]:
    """(layout, the policy's own goodput estimate) for topology, optimal and the two baselines."""
    p, d = Workload(kind="prefill", model="m", slo=slo), Workload(kind="decode", model="m", slo=slo)
    transport = TOPOLOGY_TRANSPORT.get(set_name, "shm")
    tp, td = TopologyPlacement().place_pd(p, d, cards, kv_transport=transport)
    rows = [(sim.layout(f"topology ({transport})", tp.accelerator_ids, td.accelerator_ids, transport, cards, profiles),
             None)]
    rows[0] = (rows[0][0], sim.estimate_layout(rows[0][0], m, slo, profiles) if rows[0][0].cards else None)
    for name, objective in (("optimal, per card", "per_card"), ("optimal, max goodput", "goodput")):
        o = OptimalPlacement(profiles=profiles, mix=m.with_rate(None), objective=objective)
        dp, dd = o.place_pd(p, d, cards, kv_transport="auto")
        lay = sim.layout(name, dp.accelerator_ids, dd.accelerator_ids, dp.kv_transport or "shm", cards, profiles)
        rows.append((lay, o.last_plan.estimate.goodput_rps if o.last_plan else None))
    rows.append(distserve(cards, m, slo, profiles))
    rows.append(hexgen2(cards, m, slo, profiles))
    return rows


def compare(n: int = 3000, seed: int = 1, profiles: Optional[prof.Profiles] = None,
            traces: Sequence[str] = tuple(mixes.TRACES), card_sets: Optional[Dict[str, List[Accelerator]]] = None
            ) -> List[dict]:
    profiles = comparable(profiles or prof.load())
    out = []
    for set_name, cards in (card_sets or CARD_SETS).items():
        for trace in traces:
            m, slo = mixes.from_trace(trace), mixes.trace_slo(trace)
            for lay, est in layouts_for(set_name, cards, m, slo, profiles):
                g = sim.max_rate(lay, m, slo, profiles, n=n, seed=seed)
                out.append({"cards": set_name, "trace": trace, "policy": lay.name,
                            "layout": lay.describe() if lay.cards else "none feasible", "used": lay.cards,
                            "goodput_rps": round(g, 3), "goodput_per_card": round(g / lay.cards, 4) if lay.cards else 0.0,
                            "estimate_rps": None if est is None else round(est, 3),
                            "ttft_p90_ms": slo.get("ttft_p90_ms"), "tpot_p90_ms": slo.get("tpot_p90_ms")})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rm_controller.baselines", description=__doc__.split("\n")[0])
    ap.add_argument("--compare", action="store_true", help="all policies on the GPU, NPU and mixed card sets")
    ap.add_argument("--trace", action="append", choices=sorted(mixes.TRACES), help="limit to these traces")
    ap.add_argument("--requests", type=int, default=3000, help="requests per simulated run")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--profiles", default=None, help="throughput profile table (default: packaged)")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    args = ap.parse_args(argv)
    if not args.compare:
        ap.print_help()
        return 2
    rows = compare(args.requests, args.seed, prof.load(args.profiles), args.trace or tuple(mixes.TRACES))
    print(json.dumps(rows, indent=2) if args.format == "json" else sim.markdown(rows, "Own est."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
