"""Simulator: arrivals, the serving model, and topology vs optimal on the reference card set."""
from __future__ import annotations

import pytest

from rm_controller import mix, profiles, sim

PERF = profiles.load()
CONV, SLO = mix.from_trace("azure-conv"), mix.trace_slo("azure-conv")
CARDS = sim.CARD_SETS["1 node: 2 RNGD + 4 ATOM"]


def test_arrivals_keep_the_mean_rate_and_are_reproducible():
    r = sim.requests(CONV, 2.0, 4000, seed=3)
    assert r == sim.requests(CONV, 2.0, 4000, seed=3)
    assert 4000 / r[-1][0] == pytest.approx(2.0, rel=0.15)
    lengths = [x[1:] for x in r]
    assert lengths == [x[1:] for x in sim.requests(CONV, 0.5, 4000, seed=3)]     # common random numbers


def test_layout_groups_atom_cards():
    lay = sim.layout("x", ["node-a/furiosa:0"], ["node-a/rebellions:0", "node-a/rebellions:1",
                                                 "node-a/rebellions:2", "node-a/rebellions:3"], "p2p", CARDS, PERF)
    assert lay.prefill == (("furiosa.RNGD", "node-a"),) and len(lay.decode) == 2 and lay.cards == 5
    assert lay.describe() == "P 1x RNGD / D 2x ATOM, p2p"


def test_attainment_falls_with_load():
    lay = sim.layout("t", ["node-a/furiosa:0"], ["node-a/furiosa:1"], "shm", CARDS, PERF)
    light = sim.simulate(lay, CONV, SLO, 0.05, PERF, n=600)
    heavy = sim.simulate(lay, CONV, SLO, 5.0, PERF, n=600)
    assert light.attainment > 0.9 > heavy.attainment and light.served == light.measured


def test_optimal_is_at_least_topology_per_card_and_model_agrees_roughly():
    rows = sim.layouts_for(CARDS, CONV, SLO, PERF)
    got = {lay.name: (sim.max_rate(lay, CONV, SLO, PERF, n=800, steps=8) / lay.cards, est) for lay, est in rows}
    opt = got["optimal, per card"][0]
    assert all(opt >= v * 0.95 for v, _ in got.values())
    assert opt > 3 * got["topology, RNGD/ATOM x2 p2p (examples/hetero-p2p.yaml)"][0]
    lay, est = rows[2]
    simulated = sim.max_rate(lay, CONV, SLO, PERF, n=800, steps=8)
    assert simulated / 2 <= est <= simulated * 2           # the analytical model is within 2x of the simulation


def test_markdown_table():
    rows = [{"cards": "c", "trace": "azure-conv", "policy": "p", "layout": "l", "used": 2, "goodput_rps": 0.5,
             "goodput_per_card": 0.25, "estimate_rps": None, "ttft_p90_ms": 2000, "tpot_p90_ms": 100}]
    assert "| azure-conv (2 s / 100 ms) | p | l | 2 | 0.500 | 0.250 |  |" in sim.markdown(rows)
