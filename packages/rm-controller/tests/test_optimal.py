"""The `optimal` policy: objective, constraints, fallbacks, and agreement with topology on trivial pools."""
from __future__ import annotations

from dataclasses import replace

import pytest
from rm_core import Accelerator, Workload
from rm_core.conformance import check_placement

from rm_controller import mix, profiles
from rm_controller.optimal import OptimalPlacement, erlang_c, estimate
from rm_controller.policy import RoleSpec, TopologyPlacement
from test_controller import GB, POOL, D, M, P, rngd

PERF = profiles.load()
RNGD, ATOM = PERF.devices["furiosa.RNGD"], PERF.devices["rebellions.ATOM"]
# ATOM as a two-card (TP-2) instance with a TPOT that meets 100 ms, to exercise card groups
TP2 = replace(PERF, devices={**PERF.devices, "rebellions.ATOM": replace(ATOM, group=2, tpot_ms_b1=40.0,
                                                                         tpot_ms_bmax=52.0, max_batch=8)})
SLO = {"ttft_p90_ms": 2000, "tpot_p90_ms": 100}
PS, DS = Workload(kind="prefill", model=M, slo=SLO), Workload(kind="decode", model=M, slo=SLO)


def test_conformance():
    check_placement(OptimalPlacement())
    check_placement(OptimalPlacement(), POOL)


def test_profile_table_loads_and_marks_estimates():
    assert RNGD.group == 1 and ATOM.group == 1 and ATOM.estimated and not RNGD.estimated
    assert RNGD.tpot_ms(1) == 30.0 and RNGD.tpot_ms(8) == 30.3 and RNGD.batch_for(20) < RNGD.max_batch
    assert ATOM.max_batch == 4 and ATOM.batch_for(100) == 0         # measured ATOM TPOT misses a 100 ms SLO
    assert PERF.links["shm"].transfer_ms(1) == pytest.approx(41.9, abs=0.5)     # the measured 67 MB load
    assert PERF.links["tcp"].implemented and PERF.links["tcp"].scope == "cluster"         # measured, cross-node
    assert PERF.links["tcp"].transfer_ms(1) > 800 and PERF.links["p2p"].serves("furiosa.RNGD", "rebellions.ATOM")
    assert not PERF.links["p2p"].serves("furiosa.RNGD", "furiosa.RNGD")


def test_erlang_c():
    assert erlang_c(1, 0.5) == pytest.approx(0.5)
    assert erlang_c(2, 1.0) == pytest.approx(1 / 3)
    assert erlang_c(4, 0) == 0 and erlang_c(2, 2.5) == 1


def test_estimate_grows_with_instances_and_rejects_what_does_not_fit():
    m = mix.from_trace("azure-conv")
    kv = PERF.kv_ms(PERF.links["shm"], m.input.quantile(0.9))
    one, two = estimate(RNGD, 1, RNGD, 1, kv, m, SLO), estimate(RNGD, 2, RNGD, 1, kv, m, SLO)
    assert 0 < one.goodput_rps < two.goodput_rps and one.batch == 8
    moon = mix.from_trace("mooncake-conv")
    e = estimate(RNGD, 1, ATOM, 1, kv, moon, mix.trace_slo("mooncake-conv"))
    assert e.goodput_rps == 0 and "fit" in e.why       # long prompts cannot live in ATOM's KV


def test_trivial_pool_matches_topology():
    pool = [rngd("n", 0), rngd("n", 1)]
    t = TopologyPlacement().place_pd(P, D, pool, kv_transport="shm")
    o = OptimalPlacement().place_pd(P, D, pool, kv_transport="shm")
    assert [d.accelerator_ids for d in o] == [d.accelerator_ids for d in t] == [["n/furiosa:0"], ["n/furiosa:1"]]
    assert o[0].kv_transport == "shm" and o[0].reason.startswith("optimal: prefill 1x furiosa.RNGD")


def test_lab_pool_picks_rngd_pair_and_skips_unschedulable_node():
    p, d = OptimalPlacement({"npu-node-2"}).place_pd(PS, DS, POOL, kv_transport="auto")
    ids = p.accelerator_ids + d.accelerator_ids
    assert p.accelerator_ids == ["npu-node-1/furiosa:0"] and all(i.startswith("npu-node-1/furiosa:") for i in ids)
    assert len(set(ids)) == len(ids) == 3  # decode-bound default mix (1 K in, 128 out): one prefill, two decode
    assert p.kv_transport == "shm"       # p2p is verified only for RNGD -> ATOM; tcp is not implemented
    assert "profiles measured" in p.reason


def test_role_filters_are_constraints_and_atom_groups_stay_whole():
    p, d = OptimalPlacement(profiles=TP2).place_pd(P, D, POOL, kv_transport="p2p", prefill_spec=RoleSpec("furiosa.RNGD"),
                                                   decode_spec=RoleSpec("rebellions.ATOM"))
    assert all("furiosa" in i for i in p.accelerator_ids)
    assert d.accelerator_ids and len(d.accelerator_ids) % 2 == 0 and all("rebellions" in i for i in d.accelerator_ids)
    assert {i.split("/")[0] for i in p.accelerator_ids + d.accelerator_ids} == {"npu-node-1"}   # p2p is host-local


def test_known_rate_takes_the_fewest_cards_that_cover_it():
    low = OptimalPlacement(mix=mix.DEFAULT.with_rate(0.5)).place_pd(P, D, POOL, kv_transport="shm")
    high = OptimalPlacement(mix=mix.DEFAULT.with_rate(2.0)).place_pd(P, D, POOL, kv_transport="shm")
    assert len(low[0].accelerator_ids) + len(low[1].accelerator_ids) == 2
    assert len(high[0].accelerator_ids) + len(high[1].accelerator_ids) == 3


def test_budget_and_fixed_counts():
    o = OptimalPlacement(objective="goodput")
    p, d = o.place_pd(P, D, POOL, kv_transport="shm", budget=2)
    assert len(p.accelerator_ids) + len(d.accelerator_ids) == 2
    p, d = o.place_pd(P, D, POOL, kv_transport="shm", counts=(1, 2))
    assert len(p.accelerator_ids) == 1 and len(d.accelerator_ids) == 2


def test_used_and_unhealthy_cards_are_not_offered():
    sick = Accelerator(id="npu-node-1/furiosa:0", node="npu-node-1", vendor="furiosa", model="RNGD", memory_bytes=48 * GB,
                       memory_kind="hbm", peak_tflops={"bf16": 256.0}, peak_source="datasheet",
                       extra={"health": "Unhealthy"})
    pool = [sick] + [a for a in POOL if a.id != sick.id]
    p, d = OptimalPlacement({"npu-node-2"}).place_pd(P, D, pool, kv_transport="shm",
                                                           used=["npu-node-1/furiosa:1"])
    assert p.accelerator_ids + d.accelerator_ids and "npu-node-1/furiosa:0" not in p.accelerator_ids + d.accelerator_ids
    assert "npu-node-1/furiosa:1" not in p.accelerator_ids + d.accelerator_ids


def test_cluster_link_may_span_nodes_only_when_implemented_or_planned_links_are_allowed():
    pool = [rngd("a", 0), rngd("a", 1), rngd("b", 0), rngd("b", 1)]
    nodes = lambda d: {i.split("/")[0] for i in d[0].accelerator_ids + d[1].accelerator_ids}   # noqa: E731
    # tcp is measured and implemented: max goodput spans both nodes over it
    wide = OptimalPlacement(objective="goodput").place_pd(PS, DS, pool, kv_transport="auto")
    assert wide[0].kv_transport == "tcp" and nodes(wide) == {"a", "b"}
    # the same link marked planned is used only when planned links are allowed
    planned = replace(PERF, links={**PERF.links, "tcp": replace(PERF.links["tcp"], implemented=False)})
    plain = OptimalPlacement(profiles=planned, objective="goodput").place_pd(PS, DS, pool, kv_transport="auto")
    assert nodes(plain) == {"a"}
    what_if = OptimalPlacement(profiles=planned, objective="goodput", allow_planned_links=True).place_pd(
        PS, DS, pool, kv_transport="auto")
    assert what_if[0].kv_transport == "tcp" and nodes(what_if) == {"a", "b"}


@pytest.mark.parametrize("transport, cards, needle", [
    ("loopback", [rngd("n", 0)], "shares a card"),
    ("shm", [Accelerator(id=f"n/nvidia:{i}", node="n", vendor="nvidia", model="L40S", memory_bytes=48 * GB,
                         memory_kind="gddr") for i in range(2)], "no throughput profile"),
    ("nixl", [rngd("n", 0), rngd("n", 1)], "no cost profile"),
])
def test_falls_back_to_topology_with_a_reason(transport, cards, needle):
    p, d = OptimalPlacement().place_pd(P, D, cards, kv_transport=transport)
    assert needle in p.reason and "fell back to topology" in p.reason
    t = TopologyPlacement().place_pd(P, D, cards, kv_transport=transport)
    assert p.accelerator_ids == t[0].accelerator_ids and d.accelerator_ids == t[1].accelerator_ids


def test_infeasible_mix_falls_back_with_the_why():
    moon = mix.from_trace("mooncake-conv")
    slo = {"ttft_p90_ms": 500, "tpot_p90_ms": 100}
    p, _ = OptimalPlacement(mix=moon).place_pd(Workload(kind="prefill", model=M, slo=slo),
                                               Workload(kind="decode", model=M, slo=slo), POOL, kv_transport="shm")
    assert "no SLO-feasible" in p.reason and "fell back" in p.reason


def test_place_single_by_profiled_throughput():
    o = OptimalPlacement(profiles=TP2)
    assert o.place(Workload(kind="decode", model=M, labels={"airm.ai-computing.io/accelerator": "rebellions.ATOM"}),
                   POOL).accelerator_ids == ["npu-node-1/rebellions:0", "npu-node-1/rebellions:1"]
    assert o.place(Workload(kind="prefill", model=M), POOL).accelerator_ids == ["npu-node-1/furiosa:0"]
