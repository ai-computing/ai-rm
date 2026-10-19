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

Mixed roles (mixed_roles=True)
    a role may hold instances of several device types: prefill groups P1..Pk, decode groups D1..Dm, one
    group per type. Arrivals are split over the prefill groups by routing weight, each group is its own
    M/G/c; a decode group's weight is its share of decode capacity (equal utilisation). At total rate lam
    the decode side adds max_D(TPOT + p90 slot wait) to every TTFT, and prefill group P takes the highest
    rate lam_P whose p90 TTFT (prefill(p90) + KV + that decode term + its own p90 wait) meets the SLO; lam is
    feasible when sum(lam_P) >= lam. Prefill weights are lam_P / sum(lam_P) at the chosen lam, i.e.
    proportional to each group's SLO-feasible capacity, so every group meets the TTFT p90 on its own (the
    mixture then does too). Every prefill->decode type pair must be served by the plan's one KV link.
    With one type per role this is the model above (the code calls the same function).

Constraints
    one device type per role unless mixed_roles; an instance's cards on one node;
    host-scope links (shm, p2p) keep the whole pool on one node, cluster-scope links may span nodes;
    nP, nD >= 1; nP x group(P) + nD x group(D) <= budget; a card serves one role

Objective
    rate unknown:  maximise goodput / cards, then goodput, then fewer cards
    rate known:    the fewest cards whose goodput covers the rate (then most headroom); if none can,
                   the most goodput
    objective="goodput": maximise goodput, then fewer cards

Search is exact enumeration: types are few and capacity depends on instance counts only, so the space is
links x nodes x types^2 x nP x nD (a few thousand candidates for 32 cards). Mixed roles add, per link and
node scope, every pair of type-count vectors (p_t, d_t) with p_t + d_t <= instances of t and cards <= budget,
after dropping types that cannot meet the TTFT (prefill) or KV/TPOT (decode) rules on their own. Pairs are
visited by an upper bound (min(prefill, decode capacity) / peak) and the walk stops when the bound cannot
beat the best plan found; above MAX_MIXED_PAIRS pairs a scope keeps one type per role and the reason says so.
Without a profile for any candidate type, for a `loopback` transport, or when no candidate is SLO-feasible,
the policy falls back to `topology` with the spec's counts and says so in the reason; on a pool that leaves
one choice (e.g. two identical cards) it makes topology's choice.
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
MIXED_ROLES = True          # default of mixed_roles: it changes no per-card result in the comparison tables
MAX_MIXED_PAIRS = 200000    # type-count vector pairs per link and node scope before mixed roles are skipped


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
    prefill_weights: Tuple[Tuple[str, float], ...] = ()   # mixed roles: routing weight per type
    decode_weights: Tuple[Tuple[str, float], ...] = ()


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


Groups = Sequence[Tuple[prof.DeviceProfile, int]]     # (device type, instances), one entry per type


def decode_batch(dp: prof.DeviceProfile, mix: mixes.Mix, slo: Dict[str, float]) -> int:
    """Decode batch of one instance: TPOT SLO and KV room for a mean request (0 = none)."""
    return min(dp.batch_for(slo.get("tpot_p90_ms")), int(dp.kv_tokens // max(1.0, mix.mean_input + mix.mean_output)))


def _rate_within(n: int, mu: float, cs2: float, slack_ms: float) -> float:
    """Highest arrival rate n servers of rate mu take with a p90 M/G/c wait <= slack_ms."""
    if slack_ms < 0:
        return 0.0
    lo, hi = 0.0, n * mu
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _wait_p90_ms(n, mu, mid, cs2) <= slack_ms else (lo, mid)
    return lo


def estimate_mixed(prefill: Groups, decode: Groups, kv_ms_p90: float, mix: mixes.Mix, slo: Dict[str, float],
                   attainment: float = 0.9) -> Estimate:
    """Goodput of prefill and decode roles that may mix device types (module doc, "Mixed roles").

    With one type per role this is `estimate` itself, so single-type plans keep their numbers bit for bit."""
    if len(prefill) == 1 and len(decode) == 1:
        (pp, n_p), (dp, n_d) = prefill[0], decode[0]
        return estimate(pp, n_p, dp, n_d, kv_ms_p90, mix, slo, attainment)
    ttft_slo = slo.get("ttft_p90_ms")
    dec = []                                   # (kind, slots, mu per slot, tpot, batch)
    for dp, n in decode:
        fit = mix.fits(dp.kv_tokens)
        if fit < attainment:
            return Estimate(kv_ms=kv_ms_p90, why=f"{dp.kind} decode: only {fit:.0%} of prompts fit its KV")
        b = decode_batch(dp, mix, slo)
        if b < 1:
            return Estimate(kv_ms=kv_ms_p90, why=f"{dp.kind} decode: TPOT SLO or KV capacity allows no batch")
        tpot = dp.tpot_ms(b)
        dec.append((dp.kind, n * b, 1000.0 / (tpot * mix.mean_output), tpot, b))
    pre = []                                   # (kind, servers, mu, cs2, p90 service ms)
    for pp, n in prefill:
        s = pp.prefill_ms(mix.mean_input)
        cs2 = mix.input.cv2 * ((s - pp.prefill_overhead_ms) / s) ** 2
        pre.append((pp.kind, n, 1000.0 / s, cs2, pp.prefill_ms(mix.input.quantile(0.9))))
    cap_p = sum(n * mu for _, n, mu, _, _ in pre)
    cap_d = sum(c * mu for _, c, mu, _, _ in dec)
    w_d = [c * mu / cap_d for _, c, mu, _, _ in dec]

    def dwait(lam: float) -> float:            # TPOT plus p90 wait for a decode slot, worst decode group
        return max(tpot + _wait_p90_ms(c, mu, lam * w, mix.output.cv2) for (_, c, mu, tpot, _), w in zip(dec, w_d))

    def shares(lam: float) -> List[float]:     # SLO-feasible rate of each prefill group at total rate lam
        d = dwait(lam)
        return [_rate_within(n, mu, cs2, ttft_slo - s90 - kv_ms_p90 - d) for _, n, mu, cs2, s90 in pre]

    if ttft_slo is None:
        lam = min(cap_p, cap_d) * PREFILL_UTIL
        rates = [n * mu for _, n, mu, _, _ in pre]
    else:
        if all(s90 + kv_ms_p90 + dwait(0.0) > ttft_slo for *_, s90 in pre):
            base = min(s90 for *_, s90 in pre) + kv_ms_p90 + dwait(0.0)
            return Estimate(ttft_p90_ms=base, kv_ms=kv_ms_p90,
                            why=f"mixed prefill: TTFT p90 {base:.0f} ms over SLO before any queueing")
        lo, hi = 0.0, min(cap_p, cap_d)
        for _ in range(50):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if sum(shares(mid)) >= mid else (lo, mid)
        lam = lo
        rates = shares(lam)
    total = sum(rates)
    if lam <= 0 or total <= 0:
        return Estimate(kv_ms=kv_ms_p90, why="mixed roles: no SLO-feasible rate")
    w_p = [r / total for r in rates]
    d = dwait(lam)
    ttft = max(s90 + kv_ms_p90 + d + _wait_p90_ms(n, mu, lam * w, cs2)
               for (_, n, mu, cs2, s90), w in zip(pre, w_p) if w > 0)
    main = max(range(len(dec)), key=lambda i: w_d[i])
    return Estimate(lam / max(mix.peak_ratio, 1.0), cap_p, cap_d, ttft, max(t for *_, t, _ in dec), dec[main][4],
                    kv_ms_p90, "", tuple((k, round(w, 4)) for (k, *_), w in zip(pre, w_p)),
                    tuple((k, round(w, 4)) for (k, *_), w in zip(dec, w_d)))


@dataclass(frozen=True)
class Plan:
    transport: str
    prefill_kind: str                         # "a+b" when the role mixes types
    decode_kind: str
    prefill: Tuple[Tuple[str, ...], ...]      # card ids per instance
    decode: Tuple[Tuple[str, ...], ...]
    estimate: Estimate = field(default_factory=Estimate)
    prefill_counts: Tuple[Tuple[str, int], ...] = ()    # instances per type
    decode_counts: Tuple[Tuple[str, int], ...] = ()

    @property
    def kinds(self) -> List[str]:
        return [k for k, _ in self.prefill_counts + self.decode_counts]

    @property
    def mixed(self) -> bool:
        return len(self.prefill_counts) > 1 or len(self.decode_counts) > 1

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
                 allow_planned_links: bool = False, mixed_roles: bool = MIXED_ROLES):
        if objective not in ("per_card", "goodput"):
            raise ValueError("objective must be per_card or goodput")
        self.unschedulable = frozenset(unschedulable_nodes)
        self.profiles = profiles or prof.load()
        self.mix = mix or mixes.DEFAULT
        self.objective, self.attainment, self.allow_planned = objective, attainment, allow_planned_links
        self.mixed_roles = bool(mixed_roles)
        self._skipped = 0
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
        self._skipped = 0
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
                                key = self._key(est, cards, mix) + (2, est.kv_ms, rank, link.name, kp, kd)
                                if best_key is None or key < best_key:
                                    best_key, best = key, (link, nodes, ((kp, n_p),), ((kd, n_d),), est)
                if self.mixed_roles:
                    best_key, best = self._mixed(link, kv90, rank, nodes, cells, p_kinds, d_kinds, mix, slo,
                                                 budget, counts, best_key, best)
        if best is None:
            return None, f"no SLO-feasible assignment for mix {mix.name} ({last_why})"
        link, nodes, pc, dc, est = best
        groups = {k: devices[k].group for k, _ in pc + dc}
        p_groups, d_groups = self._assign(cells, nodes, pc, dc, groups)
        return Plan(link.name, "+".join(k for k, _ in pc), "+".join(k for k, _ in dc), p_groups, d_groups, est,
                    pc, dc), ""

    def _mixed(self, link, kv90, rank, nodes, cells, p_kinds, d_kinds, mix, slo, budget, counts, best_key, best):
        """Plans with several device types in a role, for one link and node scope (module doc, "Search")."""
        devices = self.profiles.devices
        ttft = slo.get("ttft_p90_ms")
        slots = {k: sum(len(cells[n].get(k, [])) // devices[k].group for n in nodes) for k in set(p_kinds + d_kinds)}
        d_ok = [k for k in d_kinds if slots[k] and mix.fits(devices[k].kv_tokens) >= self.attainment
                and decode_batch(devices[k], mix, slo) >= 1]
        if not d_ok:
            return best_key, best
        tpot_min = min(devices[k].tpot_ms(decode_batch(devices[k], mix, slo)) for k in d_ok)
        p_ok = [k for k in p_kinds if slots[k] and (ttft is None or devices[k].prefill_ms(mix.input.quantile(0.9))
                                                      + kv90 + tpot_min <= ttft)]
        if len(p_ok) + len(d_ok) < 3:
            return best_key, best              # at most one type per role: the main loop had it
        cap_p = {k: 1000.0 / devices[k].prefill_ms(mix.mean_input) for k in p_ok}
        cap_d = {}
        for k in d_ok:
            b = decode_batch(devices[k], mix, slo)
            cap_d[k] = b * 1000.0 / (devices[k].tpot_ms(b) * mix.mean_output)

        def vectors(kinds):
            out = [()]
            for k in kinds:
                out = [v + ((k, c),) for v in out for c in range(slots[k] + 1)]
            return [tuple((k, c) for k, c in v if c) for v in out if any(c for _, c in v)]

        pv, dv = vectors(p_ok), vectors(d_ok)
        if len(pv) * len(dv) > MAX_MIXED_PAIRS:
            self._skipped = max(self._skipped, len(pv) * len(dv))
            return best_key, best
        peak = max(mix.peak_ratio, 1.0)
        util = PREFILL_UTIL if ttft is None else 1.0
        cands = []
        for p in pv:
            for d in dv:
                if len(p) == 1 and len(d) == 1:
                    continue                   # one type per role: the main loop
                used = dict(p)
                if any(used.get(k, 0) + c > slots[k] for k, c in d):
                    continue
                if counts and (sum(c for _, c in p), sum(c for _, c in d)) != tuple(counts):
                    continue
                if not all(link.serves(a, b) for a, _ in p for b, _ in d):
                    continue
                cards = sum(c * devices[k].group for k, c in p + d)
                if budget and cards > budget:
                    continue
                ub = min(sum(c * cap_p[k] for k, c in p), sum(c * cap_d[k] for k, c in d)) * util / peak
                cands.append((self._key(Estimate(ub), cards, mix), p, d, cards))
        cands.sort(key=lambda c: c[0])
        for head, p, d, cards in cands:
            if best_key is not None and head > best_key[:len(head)]:
                break                          # no remaining pair beats the best plan, even at its bound
            est = estimate_mixed([(devices[k], c) for k, c in p], [(devices[k], c) for k, c in d], kv90, mix, slo,
                                 self.attainment)
            if est.goodput_rps <= 0:
                continue
            key = self._key(est, cards, mix) + (len(p) + len(d), est.kv_ms, rank, link.name,
                                                "+".join(k for k, _ in p), "+".join(k for k, _ in d), p, d)
            if best_key is None or key < best_key:
                best_key, best = key, (link, nodes, p, d, est)
        return best_key, best

    def _key(self, est: Estimate, cards: int, mix: mixes.Mix) -> tuple:
        g = round(est.goodput_rps, 6)
        if self.objective == "goodput":
            return (-g, cards)
        if mix.rate_rps:
            return (0, cards, -g) if est.goodput_rps >= mix.rate_rps else (1, -g, cards)
        return (-round(est.goodput_rps / cards, 6), -g, cards)

    @staticmethod
    def _assign(cells, nodes, prefill_counts, decode_counts, groups):
        left = {n: {k: list(v) for k, v in cells[n].items()} for n in nodes}

        def take(kind, g, n):
            out = []
            for node in nodes:
                cards = left[node].get(kind, [])
                while len(out) < n and len(cards) >= g:
                    out.append(tuple(a.id for a in cards[:g]))
                    del cards[:g]
            return tuple(out)

        p = tuple(i for k, n in prefill_counts for i in take(k, groups[k], n))
        return p, tuple(i for k, n in decode_counts for i in take(k, groups[k], n))

    def place_serve(self, workload: Workload, pool: Sequence[Accelerator], *, spec: RoleSpec = ANY,
                    used: Iterable[str] = ()) -> PlacementDecision:
        """Aggregated pools are placed by count, as topology does: the profiles describe the
        prefill/decode serving path, not single-card serving of another model."""
        return self.topology.place_serve(workload, pool, spec=spec, used=used)

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
               + ("partly estimated" if any(self.profiles.devices[k].estimated for k in plan.kinds) else "measured"))
        if self._skipped:
            est += f"; mixed roles not searched ({self._skipped} combinations)"
        if plan.mixed:
            def role(counts, weights):
                w = dict(weights)
                return (" + ".join(f"{n}x {k}" for k, n in counts)
                        + (" (routing weights " + "/".join(f"{w[k]:.2f}" for k, _ in counts) + ")"
                           if len(counts) > 1 else ""))
            pr = f"optimal: prefill {role(plan.prefill_counts, e.prefill_weights)}; {est}"
            dr = f"optimal: decode {role(plan.decode_counts, e.decode_weights)}; {est}"
        else:
            pr = f"optimal: prefill {len(plan.prefill)}x {plan.prefill_kind}; {est}"
            dr = f"optimal: decode {len(plan.decode)}x {plan.decode_kind}; {est}"
        return (PlacementDecision(plan.prefill_ids, plan.transport, pr),
                PlacementDecision(plan.decode_ids, plan.transport, dr))
