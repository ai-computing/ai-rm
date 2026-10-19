"""Optimal prefill/decode placement (entry point `airm.placements:optimal`).

Chooses, for one pool, which device type serves prefill and which serves decode, how many instances of
each, on which nodes, and over which KV link, so that SLO-feasible goodput per card is highest.

Inputs
    cards       free, healthy cards on schedulable nodes (AcceleratorProfiles), optional per-role type filter
    profiles    per device type: prefill tok/s, decode TPOT(batch), max batch, KV capacity, cards per
                instance (profiles.yaml, partly estimates); per link: bandwidth, latency, scope
    mix         mean/p90 prompt and answer lengths, mean arrival rate, 60 s peak/mean (mix.py)
    slo         ttft_p90_ms, tpot_p90_ms from the workload
    budget      most cards the pool may take

Model, per candidate (link L, prefill type P x nP instances, decode type D x nD instances)
    decode   batch b = largest batch with TPOT(b) <= tpot SLO and b x (mean in + out) <= KV capacity;
             nD x b slots, each busy mean out x TPOT(b); infeasible when fewer than `attainment` of
             prompts fit D's KV capacity
    prefill  nP servers, service time overhead + prompt / tok/s
    TTFT p90 ~ prefill(p90 prompt) + KV(L, p90 prompt) + TPOT + p90 wait for a prefill server + p90 wait
             for a decode slot, both M/G/c (Erlang C, Allen-Cunneen, exponential tail)
    goodput  the highest rate whose TTFT p90 is within the SLO, divided by peak_ratio: the mean rate whose
             60 s peak is still served

Constraints
    one device type per role (one Deployment per role); an instance's cards on one node;
    host-scope links (shm, p2p) keep the whole pool on one node, cluster-scope links may span nodes;
    nP, nD >= 1; nP x group(P) + nD x group(D) <= budget; a card serves one role

Objective
    rate unknown:  maximise goodput / cards, then goodput, then fewer cards
    rate known:    the fewest cards whose goodput covers the rate (then most headroom); if none can,
                   the most goodput
    objective="goodput": maximise goodput, then fewer cards

Search is exact enumeration: types are few and capacity depends on instance counts only, so the space is
links x nodes x types^2 x nP x nD (a few thousand candidates for 32 cards). Without a profile for any
candidate type, for a `loopback` transport, or when no candidate is SLO-feasible, the policy falls back to
`topology` with the spec's counts and says so in the reason; on a pool that leaves one choice (e.g. two
identical cards) it makes topology's choice.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from rm_core import Accelerator, PlacementDecision, Workload

from . import mix as mixes
from . import profiles as prof
from .policy import ACCEL_LABEL, ANY, RoleSpec, TopologyPlacement, healthy, kind_of

PREFILL_UTIL = 0.9          # share of capacity used when there is no TTFT SLO


def _index(a: Accelerator) -> int:
    m = re.search(r":(\d+)$", a.id)
    return int(m.group(1)) if m else 0


def erlang_c(c: int, a: float) -> float:
    """Probability of waiting in M/M/c with offered load a (Erlangs)."""
    if a <= 0:
        return 0.0
    if a >= c:
        return 1.0
    s = term = 1.0
    for k in range(1, c):
        term *= a / k
        s += term
    top = term * a / c * c / (c - a)
    return top / (s + top)


@dataclass(frozen=True)
class Estimate:
    goodput_rps: float = 0.0        # sustainable mean rate within SLO
    prefill_rps: float = 0.0
    decode_rps: float = 0.0
    ttft_p90_ms: float = 0.0
    tpot_ms: float = 0.0
    batch: int = 0
    kv_ms: float = 0.0
    why: str = ""                   # set when infeasible


def _wait_p90_ms(c: int, mu: float, lam: float, cs2: float) -> float:
    """p90 queueing delay of M/G/c (Erlang C with the Allen-Cunneen correction, exponential tail)."""
    if lam <= 0:
        return 0.0
    if lam >= c * mu:
        return math.inf
    pw = erlang_c(c, lam / mu)
    if pw <= 0.1:
        return 0.0
    return math.log(pw / 0.1) * (1 + cs2) / 2 / (c * mu - lam) * 1000.0


def estimate(pp: prof.DeviceProfile, n_p: int, dp: prof.DeviceProfile, n_d: int, kv_ms_p90: float,
             mix: mixes.Mix, slo: Dict[str, float], attainment: float = 0.9) -> Estimate:
    """Goodput of nP prefill instances of `pp` and nD decode instances of `dp` (see the module doc)."""
    ttft_slo, tpot_slo = slo.get("ttft_p90_ms"), slo.get("tpot_p90_ms")
    fit = mix.fits(dp.kv_tokens)
    if fit < attainment:
        return Estimate(kv_ms=kv_ms_p90, why=f"{dp.kind} decode: only {fit:.0%} of prompts fit its KV")
    b = min(dp.batch_for(tpot_slo), int(dp.kv_tokens // max(1.0, mix.mean_input + mix.mean_output)))
    if b < 1:
        return Estimate(kv_ms=kv_ms_p90, why=f"{dp.kind} decode: TPOT SLO or KV capacity allows no batch")
    tpot = dp.tpot_ms(b)
    # decode: n_d x b slots, each holding a request for mean_out x TPOT
    mu_d = 1000.0 / (tpot * mix.mean_output)
    slots = n_d * b
    # prefill: n_p servers, service time from the prompt length
    s = pp.prefill_ms(mix.mean_input)
    s90 = pp.prefill_ms(mix.input.quantile(0.9))
    cs2 = mix.input.cv2 * ((s - pp.prefill_overhead_ms) / s) ** 2
    mu_p = 1000.0 / s
    base = s90 + kv_ms_p90 + tpot
    cap = min(n_p * mu_p, slots * mu_d)

    def ttft90(lam: float) -> float:
        return base + _wait_p90_ms(n_p, mu_p, lam, cs2) + _wait_p90_ms(slots, mu_d, lam, mix.output.cv2)

    if ttft_slo is None:
        lam = cap * PREFILL_UTIL
    elif base > ttft_slo:
        return Estimate(ttft_p90_ms=base, tpot_ms=tpot, batch=b, kv_ms=kv_ms_p90,
                        why=f"{pp.kind} prefill: TTFT p90 {base:.0f} ms over SLO before any queueing")
    else:
        lo, hi = 0.0, cap
        for _ in range(50):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if ttft90(mid) <= ttft_slo else (lo, mid)
        lam = lo
    good = lam / max(mix.peak_ratio, 1.0)
    return Estimate(good, n_p * mu_p, slots * mu_d, ttft90(lam), tpot, b, kv_ms_p90)


@dataclass(frozen=True)
class Plan:
    transport: str
    prefill_kind: str
    decode_kind: str
    prefill: Tuple[Tuple[str, ...], ...]      # card ids per instance
    decode: Tuple[Tuple[str, ...], ...]
    estimate: Estimate = field(default_factory=Estimate)

    @property
    def cards(self) -> int:
        return sum(len(g) for g in self.prefill + self.decode)

    @property
    def prefill_ids(self) -> List[str]:
        return [i for g in self.prefill for i in g]

    @property
    def decode_ids(self) -> List[str]:
        return [i for g in self.decode for i in g]


class OptimalPlacement:
    name = "optimal"

    def __init__(self, unschedulable_nodes: Iterable[str] = (), profiles: Optional[prof.Profiles] = None,
                 mix: Optional[mixes.Mix] = None, objective: str = "per_card", attainment: float = 0.9,
                 allow_planned_links: bool = False):
        if objective not in ("per_card", "goodput"):
            raise ValueError("objective must be per_card or goodput")
        self.unschedulable = frozenset(unschedulable_nodes)
        self.profiles = profiles or prof.load()
        self.mix = mix or mixes.DEFAULT
        self.objective, self.attainment, self.allow_planned = objective, attainment, allow_planned_links
        self.topology = TopologyPlacement(self.unschedulable)
        self.last_plan: Optional[Plan] = None

    def usable(self, a: Accelerator) -> bool:
        return a.node not in self.unschedulable and healthy(a)

    # -- rm-core Placement contract: one workload ---------------------------------------------------

    def place(self, workload: Workload, pool: Sequence[Accelerator],
              metrics: Optional[Dict[str, float]] = None) -> PlacementDecision:
        """The best single instance for the role by profiled throughput per card; topology otherwise."""
        workload.validate()
        want = workload.labels.get(ACCEL_LABEL)
        cands = [a for a in pool if self.usable(a) and (not want or kind_of(a) == want)
                 and kind_of(a) in self.profiles.devices]

        def per_card(kind: str) -> float:
            d = self.profiles.devices[kind]
            rate = d.prefill_tok_s if workload.kind == "prefill" else d.max_batch / d.tpot_ms_bmax
            return rate / d.group

        for kind in sorted({kind_of(a) for a in cands}, key=lambda k: (-per_card(k), k)):
            g = self.profiles.devices[kind].group
            for node in sorted({a.node for a in cands}):
                cards = sorted((a for a in cands if a.node == node and kind_of(a) == kind), key=_index)
                if len(cards) >= g:
                    ids = [a.id for a in cards[:g]]
                    return PlacementDecision(ids, "", f"optimal: {workload.kind} -> {', '.join(ids)} "
                                                      f"({kind}, best profiled {workload.kind} throughput per card)")
        d = self.topology.place(workload, pool, metrics)
        return PlacementDecision(d.accelerator_ids, d.kv_transport, "optimal: no profiled card; " + d.reason)

    # -- prefill/decode pair --------------------------------------------------------------------------

    def _links(self, kv_transport: str) -> Tuple[List[prof.Link], str]:
        if kv_transport == "auto":
            links = [l for l in self.profiles.links.values()
                     if l.scope in ("host", "cluster") and (l.implemented or self.allow_planned)]
            return sorted(links, key=lambda l: l.name), "" if links else "no usable KV link in the profiles"
        link = self.profiles.links.get(kv_transport)
        if link is None:
            return [], f"no cost profile for KV transport {kv_transport!r}"
        if link.scope == "card":
            return [], f"{kv_transport} shares a card between prefill and decode"
        return [link], ""

    def solve(self, pool: Sequence[Accelerator], *, kv_transport: str, prefill_spec: RoleSpec = ANY,
              decode_spec: RoleSpec = ANY, used: Iterable[str] = (), mix: Optional[mixes.Mix] = None,
              slo: Optional[Dict[str, float]] = None, budget: Optional[int] = None,
              counts: Optional[Tuple[int, int]] = None) -> Tuple[Optional[Plan], str]:
        """The best plan, or None and why there is none. `counts` fixes (prefill, decode) instances."""
        mix, slo = mix or self.mix, dict(slo or {})
        taken = set(used)
        devices = self.profiles.devices
        free = [a for a in pool if a.id not in taken and self.usable(a)]
        known = [a for a in free if kind_of(a) in devices]
        if not known:
            unknown = sorted({kind_of(a) for a in free})
            return None, ("no free card" if not free else f"no throughput profile for {', '.join(unknown)}")
        links, why = self._links(kv_transport)
        if not links:
            return None, why
        cells: Dict[str, Dict[str, List[Accelerator]]] = {}
        for a in sorted(known, key=lambda a: (a.node, kind_of(a), _index(a))):
            cells.setdefault(a.node, {}).setdefault(kind_of(a), []).append(a)
        kinds = sorted({kind_of(a) for a in known})
        p_kinds = [k for k in kinds if not prefill_spec.accelerator or k == prefill_spec.accelerator]
        d_kinds = [k for k in kinds if not decode_spec.accelerator or k == decode_spec.accelerator]
        p90_in = mix.input.quantile(0.9)
        cache: Dict[tuple, Estimate] = {}
        best_key, best, last_why = None, None, "no candidate fits"
        for link in links:
            kv90 = self.profiles.kv_ms(link, p90_in)
            if link.scope == "host":   # prefer the node with more free cards, as topology does
                scopes = [[n] for n in sorted(cells, key=lambda n: (-sum(map(len, cells[n].values())), n))]
            else:
                scopes = [sorted(cells)]
            for rank, nodes in enumerate(scopes):
                for kp in p_kinds:
                    for kd in d_kinds:
                        if not link.serves(kp, kd):
                            last_why = f"{link.name} is not verified for {kp}->{kd}"
                            continue
                        gp, gd = devices[kp].group, devices[kd].group
                        slots_p = sum(len(cells[n].get(kp, [])) // gp for n in nodes)
                        slots_d = sum(len(cells[n].get(kd, [])) // gd for n in nodes)
                        for n_p in range(1, slots_p + 1):
                            max_d = slots_p - n_p if kp == kd else slots_d
                            for n_d in range(1, max_d + 1):
                                if counts and (n_p, n_d) != tuple(counts):
                                    continue
                                cards = n_p * gp + n_d * gd
                                if budget and cards > budget:
                                    break
                                ck = (link.name, kp, n_p, kd, n_d)
                                if ck not in cache:
                                    cache[ck] = estimate(devices[kp], n_p, devices[kd], n_d, kv90, mix, slo,
                                                         self.attainment)
                                est = cache[ck]
                                if est.goodput_rps <= 0:
                                    last_why = est.why or last_why
                                    continue
                                key = self._key(est, cards, mix) + (est.kv_ms, rank, link.name, kp, kd)
                                if best_key is None or key < best_key:
                                    best_key, best = key, (link, nodes, kp, n_p, kd, n_d, est)
        if best is None:
            return None, f"no SLO-feasible assignment for mix {mix.name} ({last_why})"
        link, nodes, kp, n_p, kd, n_d, est = best
        p_groups, d_groups = self._assign(cells, nodes, kp, devices[kp].group, n_p, kd, devices[kd].group, n_d)
        return Plan(link.name, kp, kd, p_groups, d_groups, est), ""

    def _key(self, est: Estimate, cards: int, mix: mixes.Mix) -> tuple:
        g = round(est.goodput_rps, 6)
        if self.objective == "goodput":
            return (-g, cards)
        if mix.rate_rps:
            return (0, cards, -g) if est.goodput_rps >= mix.rate_rps else (1, -g, cards)
        return (-round(est.goodput_rps / cards, 6), -g, cards)

    @staticmethod
    def _assign(cells, nodes, kp, gp, n_p, kd, gd, n_d):
        left = {n: {k: list(v) for k, v in cells[n].items()} for n in nodes}

        def take(kind, g, n):
            out = []
            for node in nodes:
                cards = left[node].get(kind, [])
                while len(out) < n and len(cards) >= g:
                    out.append(tuple(a.id for a in cards[:g]))
                    del cards[:g]
            return tuple(out)

        return take(kp, gp, n_p), take(kd, gd, n_d)

    def place_pd(self, prefill: Workload, decode: Workload, pool: Sequence[Accelerator], *,
                 kv_transport: str, prefill_spec: RoleSpec = ANY, decode_spec: RoleSpec = ANY,
                 used: Iterable[str] = (), mix: Optional[mixes.Mix] = None, budget: Optional[int] = None,
                 counts: Optional[Tuple[int, int]] = None) -> Tuple[PlacementDecision, PlacementDecision]:
        prefill.validate()
        decode.validate()
        used = list(used)
        mix = mix or self.mix
        slo = {**decode.slo, **prefill.slo}
        plan, why = self.solve(pool, kv_transport=kv_transport, prefill_spec=prefill_spec, decode_spec=decode_spec,
                               used=used, mix=mix, slo=slo, budget=budget, counts=counts)
        self.last_plan = plan
        if plan is None:
            transport = "shm" if kv_transport == "auto" else kv_transport
            p, d = self.topology.place_pd(prefill, decode, pool, kv_transport=transport, prefill_spec=prefill_spec,
                                          decode_spec=decode_spec, used=used)
            pre = f"optimal: {why}; fell back to topology: "
            return (PlacementDecision(p.accelerator_ids, p.kv_transport, pre + p.reason.removeprefix("topology: ")),
                    PlacementDecision(d.accelerator_ids, d.kv_transport, pre + d.reason.removeprefix("topology: ")))
        e = plan.estimate
        nodes = sorted({i.split("/", 1)[0] for i in plan.prefill_ids + plan.decode_ids})
        est = (f"est. {e.goodput_rps:.2f} req/s ({e.goodput_rps / plan.cards:.2f}/card over {plan.cards} cards), "
               f"TTFT p90 ~{e.ttft_p90_ms:.0f} ms, TPOT ~{e.tpot_ms:.0f} ms at batch {e.batch}, "
               f"{plan.transport} on {', '.join(nodes)}; mix {mix.name}; profiles "
               + ("partly estimated" if any(self.profiles.devices[k].estimated
                                            for k in (plan.prefill_kind, plan.decode_kind)) else "measured"))
        pr = f"optimal: prefill {len(plan.prefill)}x {plan.prefill_kind}; {est}"
        dr = f"optimal: decode {len(plan.decode)}x {plan.decode_kind}; {est}"
        return (PlacementDecision(plan.prefill_ids, plan.transport, pr),
                PlacementDecision(plan.decode_ids, plan.transport, dr))
