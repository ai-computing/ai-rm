"""DistServe- and HexGen-2-style baselines, the A100 profile, and the burst windows they are compared under."""
from __future__ import annotations

import pytest

from rm_controller import baselines, mix, profiles, sim

PERF = baselines.comparable(profiles.load())
CONV, SLO = mix.from_trace("azure-conv"), mix.trace_slo("azure-conv")
GPU = baselines.CARD_SETS["GPU only: 1 node, 4 A100"]
NPU = baselines.CARD_SETS["NPU only: 1 node, 2 RNGD + 4 ATOM"]
MIXED = baselines.CARD_SETS["Mixed: 1 node, 2 A100 + 2 RNGD + 4 ATOM"]


def test_a100_profile_and_gpu_link():
    raw = profiles.load()
    a100 = raw.devices["nvidia.A100"]
    assert a100.group == 1 and a100.estimated and a100.source["tpot_ms_bmax"] == "derived"
    assert a100.tpot_ms(1) < raw.devices["furiosa.RNGD"].tpot_ms(1) and a100.kv_tokens > 250000
    link = raw.links["cuda-ipc"]
    assert not link.implemented and link.serves("nvidia.A100", "nvidia.A100")
    assert not link.serves("furiosa.RNGD", "furiosa.RNGD")
    assert PERF.links["cuda-ipc"].implemented and PERF.links["tcp"].implemented      # tcp is measured now
    assert sim.card("n", "nvidia.A100", 0).model == "A100"


def test_instances_follow_groups():
    insts = baselines.instances(MIXED, PERF)
    # measured: one ATOM card per decode instance (the fp16 artifact fits one card)
    assert insts.count(("nvidia.A100", "node-m")) == 2 and insts.count(("rebellions.ATOM", "node-m")) == 4


def test_max_flow():
    # s=0 -> 1 (3), s -> 2 (2), 1 -> t=3 (2), 2 -> t (3), 1 -> 2 (1): 1 sends 2 to t and 1 through 2
    flow, through = baselines.max_flow(4, [(0, 1, 3), (0, 2, 2), (1, 3, 2), (2, 3, 3), (1, 2, 1)], 0, 3)
    assert flow == pytest.approx(5.0) and through[1] == pytest.approx(3.0)
    assert baselines.max_flow(3, [(0, 1, 4), (1, 2, 1.5)], 0, 2)[0] == pytest.approx(1.5)
    assert baselines.max_flow(3, [(0, 1, 4)], 0, 2)[0] == 0


def test_distserve_is_homogeneous_and_node_local():
    for cards in (GPU, NPU, MIXED):
        lay, est = baselines.distserve(cards, CONV, SLO, PERF)
        assert est > 0 and len({k for k, _ in lay.prefill + lay.decode}) == 1
        assert len({n for _, n in lay.prefill + lay.decode}) == 1 and PERF.links[lay.transport].scope == "host"
    assert baselines.distserve(GPU, CONV, SLO, PERF)[0].transport == "cuda-ipc"
    assert baselines.distserve(NPU, CONV, SLO, PERF)[0].prefill[0][0] == "furiosa.RNGD"


def test_distserve_prefill_rate_falls_with_a_tighter_slo():
    rngd, shm = PERF.devices["furiosa.RNGD"], PERF.links["shm"]
    loose = baselines.distserve_prefill_rate(rngd, shm, CONV, {"ttft_p90_ms": 4000}, PERF)
    tight = baselines.distserve_prefill_rate(rngd, shm, CONV, {"ttft_p90_ms": 2000}, PERF)
    assert loose > tight > 0
    assert baselines.distserve_prefill_rate(rngd, shm, CONV, {"ttft_p90_ms": 100}, PERF) == 0


def test_hexgen2_mixes_types_per_role_and_beats_any_single_split():
    lay, est = baselines.hexgen2(MIXED, CONV, SLO, PERF)
    assert len({k for k, _ in lay.prefill}) > 1 or len({k for k, _ in lay.decode}) > 1
    assert est * CONV.peak_ratio >= baselines.distserve(MIXED, CONV, SLO, PERF)[1] * CONV.peak_ratio * 0.99
    rates = [PERF.devices[k].prefill_ms(CONV.mean_input) for k, _ in lay.prefill]
    assert rates == sorted(rates)                      # fastest prefill first: the simulator's dispatch order
    assert lay.cards <= sum(1 for _ in MIXED)


def test_hexgen2_drops_instances_without_flow_and_reports_infeasible():
    lay, _ = baselines.hexgen2(GPU, CONV, SLO, PERF)
    assert lay.cards <= 4 and lay.prefill and lay.decode
    moon = mix.from_trace("mooncake-conv")
    tight = {"ttft_p90_ms": 1000, "tpot_p90_ms": 100}   # p90 prompt 27 K tokens cannot prefill within 1 s on RNGD
    empty, est = baselines.hexgen2(NPU, moon, tight, PERF)
    assert est == 0 and empty.cards == 0 and sim.max_rate(empty, moon, {}, PERF) == 0


def test_compare_rows_and_optimal_not_worse_per_card_on_gpu():
    rows = baselines.compare(n=600, traces=("azure-conv",), card_sets={"gpu": GPU})
    got = {r["policy"]: r for r in rows}
    assert set(got) == {"topology (shm)", "optimal, per card", "optimal, max goodput", "distserve", "hexgen2"}
    best = max(r["goodput_per_card"] for r in rows)
    assert got["optimal, per card"]["goodput_per_card"] >= 0.9 * best
    assert got["optimal, max goodput"]["goodput_rps"] >= 0.9 * max(r["goodput_rps"] for r in rows)


def test_every_run_meets_a_burst():
    burst = mix.from_trace("burstgpt")                 # 60 s peak/mean 69: one peak window in 138
    r = sim.requests(burst, 10.0, 3000, seed=2)
    first = sum(1 for t, _, _ in r if t < sim.WINDOW_S)
    assert first == len(r)                             # 3000 requests at 690 req/s all fall in the first window
    slow = sim.requests(burst, 0.05, 3000, seed=2)
    assert 3000 / slow[-1][0] == pytest.approx(0.05, rel=0.25)
