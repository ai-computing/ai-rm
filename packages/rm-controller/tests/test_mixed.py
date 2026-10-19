"""`optimal` with mixed roles: the estimate, the bounded search, KV-link rules, sim routing, spec and apply."""
from __future__ import annotations

import dataclasses
import itertools
import json

import pytest
from rm_core import Workload

from rm_controller import apply, baselines, controller, document, mix, optimal, profiles, sim
from rm_controller.optimal import OptimalPlacement, estimate, estimate_mixed

PERF = baselines.comparable(profiles.load())     # cuda-ipc counted as available, as in the baselines table
DEV = PERF.devices
A100, RNGD, ATOM = DEV["nvidia.A100"], DEV["furiosa.RNGD"], DEV["rebellions.ATOM"]
CONV, SLO = mix.from_trace("azure-conv"), mix.trace_slo("azure-conv")
MIXED = baselines.CARD_SETS["Mixed: 1 node, 2 A100 + 2 RNGD + 4 ATOM"]
P, D = Workload(kind="prefill", model="m", slo=SLO), Workload(kind="decode", model="m", slo=SLO)


def kv90(link="shm", m=CONV):
    return PERF.kv_ms(PERF.links[link], m.input.quantile(0.9))


def test_single_type_is_the_old_estimate_bit_for_bit():
    for (pp, n_p), (dp, n_d) in [((RNGD, 1), (RNGD, 1)), ((A100, 2), (RNGD, 1)), ((A100, 3), (A100, 1))]:
        assert estimate_mixed([(pp, n_p)], [(dp, n_d)], kv90(), CONV, SLO) == estimate(pp, n_p, dp, n_d, kv90(),
                                                                                         CONV, SLO)


def test_mixed_estimate_weights_follow_slo_feasible_capacity():
    e = estimate_mixed([(A100, 1), (RNGD, 2)], [(A100, 1)], kv90(), CONV, SLO)
    w = dict(e.prefill_weights)
    # two RNGD instances (measured) now take most of the traffic; per instance the A100 still takes more
    assert sum(w.values()) == pytest.approx(1.0, abs=1e-3) and w["nvidia.A100"] > w["furiosa.RNGD"] / 2 > 0
    assert e.decode_weights == (("nvidia.A100", 1.0),)
    assert e.ttft_p90_ms <= SLO["ttft_p90_ms"] + 1e-6
    alone = estimate(A100, 1, A100, 1, kv90(), CONV, SLO)
    assert e.goodput_rps > alone.goodput_rps          # RNGD prefill adds SLO-feasible capacity
    # ATOM prefill (p90 ~4.6 s) cannot meet a 2 s TTFT on its own: it gets no traffic and adds nothing
    slow = estimate_mixed([(A100, 1), (ATOM, 1)], [(A100, 1)], kv90(), CONV, SLO)
    assert dict(slow.prefill_weights)["rebellions.ATOM"] == 0
    assert slow.goodput_rps == pytest.approx(alone.goodput_rps, rel=0.02)


def test_mixed_decode_splits_by_capacity_and_respects_kv_fit():
    e = estimate_mixed([(A100, 1)], [(A100, 1), (RNGD, 1)], kv90(), CONV, SLO)
    w = dict(e.decode_weights)
    assert w["nvidia.A100"] > w["furiosa.RNGD"] > 0 and sum(w.values()) == pytest.approx(1.0, abs=1e-3)
    moon = mix.from_trace("mooncake-conv")
    bad = estimate_mixed([(A100, 2)], [(A100, 1), (ATOM, 1)], kv90("shm", moon), moon, mix.trace_slo("mooncake-conv"))
    assert bad.goodput_rps == 0 and "fit" in bad.why


def solve(objective="goodput", mixed=True, cards=MIXED, **kw):
    o = OptimalPlacement(profiles=PERF, mix=CONV.with_rate(None), objective=objective, mixed_roles=mixed)
    return o, o.place_pd(P, D, cards, kv_transport=kw.pop("kv_transport", "auto"), **kw)


def test_max_goodput_mixes_prefill_types_on_the_mixed_node():
    o, (p, d) = solve()
    plan = o.last_plan
    assert plan.mixed and dict(plan.prefill_counts) == {"nvidia.A100": 1, "furiosa.RNGD": 2}
    assert plan.transport == "shm"                    # cuda-ipc serves A100->A100 only, shm every pair
    assert "routing weights" in p.reason and set(p.accelerator_ids).isdisjoint(d.accelerator_ids)
    assert len(p.accelerator_ids) == 3 and d.accelerator_ids == ["node-m/nvidia:1"]
    one, _ = solve(mixed=False)
    assert plan.estimate.goodput_rps > one.last_plan.estimate.goodput_rps and not one.last_plan.mixed


def test_search_matches_brute_force_over_all_type_count_vectors():
    o, _ = solve()
    slots = {"nvidia.A100": 2, "furiosa.RNGD": 2, "rebellions.ATOM": 2}
    best = 0.0
    for link in ("shm", "cuda-ipc"):
        L = PERF.links[link]
        for pv in itertools.product(range(3), repeat=3):
            for dv in itertools.product(range(3), repeat=3):
                if not any(pv) or not any(dv) or any(a + b > 2 for a, b in zip(pv, dv)):
                    continue
                pg = [(DEV[k], c) for k, c in zip(slots, pv) if c]
                dg = [(DEV[k], c) for k, c in zip(slots, dv) if c]
                if all(L.serves(a.kind, b.kind) for a, _ in pg for b, _ in dg):
                    best = max(best, estimate_mixed(pg, dg, kv90(link), CONV, SLO).goodput_rps)
    assert o.last_plan.estimate.goodput_rps == pytest.approx(best, rel=1e-6)


def test_per_card_objective_with_mixed_roles_is_never_worse():
    # Unchanged wherever one type per role is best; on the mixed node the measured RNGD prefill now joins A100
    # prefill and raises goodput per card, so there the layouts may differ but never lose per card.
    for name, cards in list(baselines.CARD_SETS.items()) + list(sim.CARD_SETS.items()):
        for trace in ("azure-conv", "azure-code", "burstgpt"):
            m, slo = mix.from_trace(trace), mix.trace_slo(trace)
            got, per_card = [], []
            for mixed in (True, False):
                o = OptimalPlacement(profiles=PERF, mix=m.with_rate(None), mixed_roles=mixed)
                ids = [x.accelerator_ids for x in o.place_pd(Workload(kind="prefill", model="m", slo=slo),
                                                             Workload(kind="decode", model="m", slo=slo),
                                                             cards, kv_transport="auto")]
                got.append(ids)
                per_card.append(o.last_plan.estimate.goodput_rps / len(ids[0] + ids[1]))
            assert per_card[0] >= per_card[1] * (1 - 1e-9)
            if not name.startswith("Mixed"):
                assert got[0] == got[1]


def test_every_prefill_decode_type_pair_needs_the_link():
    o, _ = solve(kv_transport="cuda-ipc")           # A100->A100 only: no type to mix in
    assert not o.last_plan.mixed and o.last_plan.kinds == ["nvidia.A100", "nvidia.A100"]
    # measured ATOM decode (108 ms/token, 4 x 512 tokens of KV) needs a looser TPOT and S=512-sized requests
    loose = {"ttft_p90_ms": 2000, "tpot_p90_ms": 200}
    short = mix.from_spec({"mean_input_tokens": 300, "mean_output_tokens": 100})
    o = OptimalPlacement(profiles=PERF, mix=short, objective="goodput")
    o.place_pd(Workload(kind="prefill", model="m", slo=loose), Workload(kind="decode", model="m", slo=loose), MIXED,
               kv_transport="p2p")                    # RNGD->ATOM only
    assert o.last_plan.prefill_kind == "furiosa.RNGD" and o.last_plan.decode_kind == "rebellions.ATOM"


def test_budget_and_counts_bound_mixed_plans():
    o, (p, d) = solve(budget=3)
    assert len(p.accelerator_ids) + len(d.accelerator_ids) <= 3
    o, (p, d) = solve(counts=(3, 1))
    assert len(o.last_plan.prefill) == 3 and len(o.last_plan.decode) == 1


def test_too_many_combinations_keep_one_type_per_role(monkeypatch):
    monkeypatch.setattr(optimal, "MAX_MIXED_PAIRS", 1)
    o, (p, _) = solve()
    assert not o.last_plan.mixed and "mixed roles not searched" in p.reason


def test_weighted_round_robin_follows_weights():
    rr = sim._WRR([0.75, 0.25, 0.0])
    picks = [rr.pick([0, 1, 2]) for _ in range(400)]
    assert picks.count(0) == 300 and picks.count(1) == 100 and picks.count(2) == 0
    assert rr.pick([2]) == 2                          # only a zero-weight group is eligible: it still serves


def test_sim_routes_by_weights_and_single_type_weights_change_nothing():
    lay = sim.Layout("x", (("furiosa.RNGD", "n"), ("furiosa.RNGD", "n"), ("nvidia.A100", "n")),
                     (("nvidia.A100", "n"),), "shm", 4)
    weighted = dataclasses.replace(lay, prefill_weights=(("furiosa.RNGD", 0.3), ("nvidia.A100", 0.7)),
                                   decode_weights=(("nvidia.A100", 1.0),))
    a, b = (sim.simulate(x, CONV, SLO, 4.0, PERF, n=600) for x in (lay, weighted))
    assert a != b and b.served == b.measured
    one = sim.Layout("y", (("furiosa.RNGD", "n"),), (("furiosa.RNGD", "n"),), "shm", 2)
    tagged = dataclasses.replace(one, prefill_weights=(("furiosa.RNGD", 1.0),), decode_weights=(("furiosa.RNGD", 1.0),))
    assert sim.simulate(one, CONV, SLO, 0.3, PERF, n=600) == sim.simulate(tagged, CONV, SLO, 0.3, PERF, n=600)


def test_layout_carries_the_plans_weights():
    o, (p, d) = solve()
    lay = sim.layout("o", p.accelerator_ids, d.accelerator_ids, p.kv_transport, MIXED, PERF, o.last_plan)
    assert lay.prefill_weights == o.last_plan.estimate.prefill_weights and lay.describe().startswith("P 2x RNGD+1x A100")


def test_spec_option_and_apply_per_type_deployments(tmp_path):
    spec = {"placement": "optimal", "objective": "goodput", "pools": [
        {"pool": "pd", "model": "m", "kv_transport": "auto", "slo": SLO, "prefill": {}, "decode": {},
         "workload": {"trace": "azure-conv"}}]}
    path = tmp_path / "s.yaml"
    path.write_text(json.dumps({**spec, "mixed_roles": "yes"}), encoding="utf-8")
    with pytest.raises(ValueError, match="mixed_roles"):
        controller.load_spec(str(path))
    assert not controller.make_policy({**spec, "mixed_roles": False}, set()).mixed_roles
    entries, unplaced = controller.plan(spec, MIXED, set(), perf=PERF)
    assert not unplaced
    doc, _ = document.build(entries, document.parse(None), "optimal")

    def dep(name, role, kind=None, **s):
        ann = {apply.POOL_ANNOTATION: "pd", apply.ROLE_ANNOTATION: role, **({apply.ACCEL_ANNOTATION: kind} if kind else {})}
        return {"metadata": {"name": name, "annotations": ann}, "spec": s}

    deps = [dep("pre-a100", "prefill", "nvidia.A100"), dep("pre-rngd", "prefill", "furiosa.RNGD"),
            dep("pre-atom", "prefill", "rebellions.ATOM", replicas=1), dep("dec", "decode")]
    out = {x["name"]: x for x in apply.patches(doc, deps, MIXED, {k: v.group for k, v in DEV.items()})}
    assert out["pre-a100"]["patch"]["spec"]["replicas"] == 1 and out["pre-rngd"]["patch"]["spec"]["replicas"] == 2
    ids = out["pre-rngd"]["patch"]["spec"]["template"]["metadata"]["annotations"][apply.IDS_ANNOTATION]
    assert ids == "node-m/furiosa:0,node-m/furiosa:1"
    assert out["pre-atom"]["patch"] == {"metadata": {"annotations": {apply.GENERATION_ANNOTATION: "1"}},
                                        "spec": {"replicas": 0}}
    assert out["dec"]["patch"]["spec"]["replicas"] == 1
