"""Rebalancer predictor: both roles' pressure after a move, the hold-if-worse rule, and the episode replay."""
from __future__ import annotations

import math

import pytest

from rm_controller import episode, mix, predict, profiles
from rm_controller import rebalance as rb

SLO = {"ttft_p90_ms": 2000, "tpot_p90_ms": 100}
RNGD = "furiosa.RNGD"
# rm-bench's replay windows of the W5 live run (episode.WINDOWS)
CODE = mix.Mix("code", mix.Lengths.from_quantiles(164, 399, 486), mix.Lengths.from_quantiles(14, 48, 124), 1.93, 1.98)
CONV = mix.Mix("conv", mix.Lengths.from_quantiles(373, 402, 417), mix.Lengths.from_quantiles(93, 203, 238), 2.33, 1.76)


@pytest.fixture(scope="module")
def perf():
    return profiles.load()


def model(perf, m=CODE):
    return predict.Model.build(perf, RNGD, RNGD, "shm", m, SLO)


def test_shm_admission_stalls_decode(perf):
    assert perf.links["shm"].admit_blocking and not perf.links["p2p"].admit_blocking
    md = model(perf)
    assert md.admit_ms == pytest.approx(41.9, abs=0.1)          # 64 MiB at 1.6 GB/s, whatever the prompt
    assert md.kv_ms_p90 == 0.0                                  # paid inside decode, not before it
    # one card admits at most 1 / 41.9 ms = 23.9 requests/s; queueing for lanes makes it less
    assert md.decode_pressure(1, 24.0) == math.inf
    assert md.capacity("decode", 1) < 1000.0 / md.admit_ms
    assert md.decode_pressure(2, 12.0) < md.decode_pressure(1, 12.0)
    free = predict.Model.build(perf, RNGD, RNGD, "p2p", CODE, SLO)
    assert free.admit_ms == 0.0 and free.decode_pressure(1, 8.0) < md.decode_pressure(1, 8.0)


def test_pressure_is_monotone_and_fit_inverts_it(perf):
    md = model(perf)
    for role, n in (("prefill", 1), ("prefill", 2), ("decode", 1), ("decode", 2)):
        cap = md.capacity(role, n)
        ps = [md.pressure(role, n, cap * f) for f in (0.0, 0.3, 0.6, 0.9, 0.99)]
        assert ps == sorted(ps) and ps[-1] < math.inf
        lam = md.fit(role, n, 2.0)
        assert 0 < lam < cap and md.pressure(role, n, lam) == pytest.approx(2.0, rel=1e-3)
    assert md.fit("prefill", 1, 0.01) == 0.0                    # below the no-load latency: nothing to fit


def test_code_phase_move_is_predicted_to_hurt(perf):
    # W5 live, code x3 on 1P+2D: TTFT p90 4,879 ms (P 2.44), TPOT p90 66 ms (D 0.66). The linear rule
    # predicted decode at 1.3 on one card and moved; it measured 3.1-3.8.
    for m in (CODE, CONV, mix.DEFAULT, mix.from_trace("azure-conv")):     # the right mix or a wrong one
        p = predict.predict(model(perf, m), (1, 2), 3, (1, 1), (2.44, 0.66))
        assert p.current.prefill == pytest.approx(2.44, rel=1e-3)        # the fit reproduces what was observed
        after = next(c for c in p.candidates if c.split == (2, 1))
        assert after.prefill < 1.0 and after.decode > 2.44              # prefill relieved, decode worse than now
        assert p.best.split == (1, 2)


def test_conversation_phase_move_is_predicted_to_help(perf):
    # W5 live, conversation x2 on 2P+1D: TTFT p90 326 ms, TPOT p90 557 ms (D 5.57)
    for m in (CONV, CODE, mix.DEFAULT):
        p = predict.predict(model(perf, m), (2, 1), 3, (1, 1), (0.16, 5.57))
        assert p.source == "decode fit" and p.best.split == (1, 2)
        assert p.best.worst < 1.0
    # and on 1P+2D (D 1.3 live) nothing beats it
    assert predict.predict(model(perf, CONV), (1, 2), 3, (1, 1), (0.22, 1.3)).best.split == (1, 2)


def test_more_prefill_lets_more_of_a_burst_reach_decode(perf):
    md = model(perf)
    p = predict.predict(md, (1, 2), 4, (1, 1), (2.44, None))     # no decode signal: decode gets what prefill passes
    by = {c.split: c for c in p.candidates}
    assert p.decode_now == pytest.approx(min(p.arrivals, md.capacity("prefill", 1)))
    assert by[(2, 2)].decode > by[(1, 3)].decode * 0 and by[(2, 2)].decode >= p.current.decode
    assert by[(2, 2)].prefill < by[(1, 3)].prefill


def test_known_rate_only_when_nothing_fits(perf):
    md = model(perf)
    p = predict.predict(md, (1, 2), 3, (1, 1), (None, None), known_rate=1.0, known_source="metrics")
    assert p.source == "metrics" and p.arrivals == pytest.approx(1.0 * CODE.peak_ratio)
    hot = predict.predict(md, (1, 2), 3, (1, 1), (2.44, None), known_rate=100.0)
    assert hot.source == "prefill fit" and hot.arrivals < md.capacity("prefill", 1)


def test_decide_holds_if_no_split_is_better(perf):
    obs = rb.Observation(ttft_p90_ms=4879, tpot_p90_ms=66)
    d = rb.decide((1, 2), 3, (1, 1), obs, SLO, model(perf, mix.DEFAULT))
    assert d.want == (1, 2) and d.why.startswith("hold") and d.prediction is not None
    old = rb.target((1, 2), 3, (1, 1), obs=obs, slo=SLO)
    assert old == (2, 1)                                        # the linear rule makes the move that hurt
    conv = rb.decide((2, 1), 3, (1, 1), rb.Observation(ttft_p90_ms=326, tpot_p90_ms=557), SLO, model(perf, mix.DEFAULT))
    assert conv.want == (1, 2) and conv.why.startswith("predicted 2:1")
    assert rb.decide((1, 2), 3, (1, 1), rb.Observation(ttft_p90_ms=900, tpot_p90_ms=40), SLO,
                     model(perf)).why == "SLOs met"
    lin = rb.decide((1, 1), 3, (1, 1), obs, SLO, None)
    assert lin.why.startswith("linear") and lin.want == (2, 1)


def test_decide_margin(perf):
    md = model(perf)
    obs = rb.Observation(ttft_p90_ms=3000, tpot_p90_ms=36)       # 1P+3D, prefill over its SLO
    p = predict.predict(md, (1, 3), 4, (1, 1), rb.pressures(obs, (1, 3), SLO, floor=None))
    gain = 1 - p.best.worst / p.current.worst
    assert p.best.split == (2, 2) and 0.3 < gain < 0.8
    held = rb.decide((1, 3), 4, (1, 1), obs, SLO, md, margin=gain + 0.05)
    assert held.want == (1, 3) and "better than now 1:3" in held.why
    assert rb.decide((1, 3), 4, (1, 1), obs, SLO, md, margin=gain - 0.05).want == (2, 2)


def test_observe_rate_and_lengths():
    before = rb.parse_prometheus("vllm:request_success_total 100\nvllm:request_prompt_tokens_sum 30000\n"
                                 "vllm:request_prompt_tokens_count 100\nvllm:request_generation_tokens_sum 5000\n"
                                 "vllm:request_generation_tokens_count 100\n")
    now = rb.parse_prometheus("vllm:request_success_total 220\nvllm:request_prompt_tokens_sum 54000\n"
                              "vllm:request_prompt_tokens_count 220\nvllm:request_generation_tokens_sum 8600\n"
                              "vllm:request_generation_tokens_count 220\n")
    o = rb.observe(now, previous=before, elapsed_s=60)
    assert o.rate_rps == pytest.approx(2.0)
    assert o.mean_input == pytest.approx(200) and o.mean_output == pytest.approx(30)
    g = rb.observe(rb.parse_prometheus("airm_req_s 2.5\nairm_tok_s 50\nairm_ttft_p90_ms 900\n"))
    assert g.rate_rps == 2.5 and g.mean_output == pytest.approx(20) and g.ttft_p90_ms == 900
    m, rate, src = rb.observed_mix(o, mix.from_trace("azure-conv"))
    assert src == "metrics" and rate == pytest.approx(2.0)
    assert m.mean_input == pytest.approx(200, rel=0.02) and m.mean_output == pytest.approx(30, rel=0.02)
    m, rate, src = rb.observed_mix(rb.Observation(tok_s=100.0), mix.DEFAULT)
    assert rate == pytest.approx(100.0 / 128) and src.startswith("metrics")
    assert rb.observed_mix(None, mix.DEFAULT)[1:] == (None, "no known rate")
    assert rb.merge(o, g).rate_rps == 2.5


def test_episode_replay_old_moves_on_code_new_does_not(perf, tmp_path):
    code = episode.Phase("code x3", "azure-code", 3.0, replays=2)
    conv = episode.Phase("conv", "azure-conv", 2.0, replays=2)
    sv = episode.Serving(prefill_scale=2.0, random_prefill=True)   # statistics only (no CSVs in tmp_path)
    kw = dict(serving=sv, trace_dir=str(tmp_path))
    new = episode.run([conv, code], (2, 1), episode.Controller("new"), perf, **kw)
    assert new["source"] == "statistics"
    moved = [r for r in new["rounds"] if r["moved"]]
    assert [(r["split"], r["target"]) for r in moved] == [("2:1", "1:2")]     # the conversation move, only
    assert moved[0]["t"] < 600
    phases = episode.per_phase(new)
    assert phases[0]["splits"][0] == "2P+1D" and phases[1]["splits"] == ["1P+2D"]
    fixed = episode.run([conv], (2, 1), episode.Controller("none"), perf, **kw)
    assert episode.per_phase(new)[0]["attainment"] > episode.per_phase(fixed)[0]["attainment"]
    md = episode.markdown([dict(new, order="conv / code")])
    assert "new rule from 2:1" in md and "Moves: t=" in md
