"""P:D rebalancer: metric parsing, the target split, hysteresis, and the controller mode."""
from __future__ import annotations

import json

import pytest

from rm_controller import controller, document, mix, profiles
from rm_controller import rebalance as rb
from test_controller import M, FakeIO

METRICS = """# HELP vllm:num_requests_waiting Requests waiting.
# TYPE vllm:num_requests_waiting gauge
vllm:num_requests_waiting{pod="p-0",role="prefill"} 6
vllm:num_requests_waiting{pod="d-0",role="decode"} 0
vllm:time_to_first_token_seconds_bucket{le="0.5",role="prefill"} 10
vllm:time_to_first_token_seconds_bucket{le="1.0",role="prefill"} 20
vllm:time_to_first_token_seconds_bucket{le="4.0",role="prefill"} 100
vllm:time_to_first_token_seconds_bucket{le="+Inf",role="prefill"} 100
vllm:time_per_output_token_seconds_bucket{le="0.025",role="decode"} 90
vllm:time_per_output_token_seconds_bucket{le="0.05",role="decode"} 100
vllm:time_per_output_token_seconds_bucket{le="+Inf",role="decode"} 100
"""


def test_parse_and_quantile():
    s = rb.parse_prometheus(METRICS)
    assert len(s) == 9 and s[0].name == "vllm:num_requests_waiting" and s[0].label("role") == "prefill"
    assert rb.histogram_quantile(0.5, [(1.0, 5), (2.0, 10), (float("inf"), 10)]) == pytest.approx(1.0)
    assert rb.histogram_quantile(0.9, []) is None


def test_observe_splits_roles_and_windows_histograms():
    o = rb.observe(rb.parse_prometheus(METRICS))
    assert o.prefill_waiting == 6 and o.decode_waiting == 0
    assert o.ttft_p90_ms == pytest.approx(3625.0) and o.tpot_p90_ms == pytest.approx(25.0)
    before = rb.parse_prometheus(METRICS.replace(' 100\n', ' 90\n').replace('le="0.5",role="prefill"} 10',
                                                                            'le="0.5",role="prefill"} 0'))
    # since `before`: 10 new fast requests below 0.5 s, 10 more in (1, 4] -> the window's p90 sits in (1, 4]
    w = rb.observe(rb.parse_prometheus(METRICS), previous=before)
    assert w.ttft_p90_ms < o.ttft_p90_ms
    forced = rb.observe(rb.parse_prometheus("vllm:num_requests_waiting 3\nairm_tpot_p90_ms 120\n"), role="decode")
    assert forced.decode_waiting == 3 and forced.tpot_p90_ms == 120


def test_target_moves_cards_to_the_role_under_pressure():
    obs = rb.observe(rb.parse_prometheus(METRICS))
    slo = {"ttft_p90_ms": 2000, "tpot_p90_ms": 100}
    assert rb.pressures(obs, (1, 1), slo) == pytest.approx((3.0, 0.25))
    assert rb.target((1, 1), 3, (1, 1), obs=obs, slo=slo) == (2, 1)
    assert rb.target((1, 2), 6, (1, 2), obs=obs, slo=slo) == (4, 1)        # ATOM decode in groups of two
    calm = rb.Observation(0, 0, 900, 30)
    assert rb.target((1, 1), 3, (1, 1), obs=calm, slo=slo) == (1, 1)       # SLOs met: nothing moves


def test_target_from_trace_statistics():
    perf = profiles.load()
    r, a = perf.devices["furiosa.RNGD"], perf.devices["furiosa.RNGD"]
    code = rb.need_from_mix(mix.from_trace("azure-code", 0.2), r, a, mix.trace_slo("azure-code"))
    conv = rb.need_from_mix(mix.from_trace("azure-conv", 0.2), r, a, mix.trace_slo("azure-conv"))
    assert code[0] / code[1] > conv[0] / conv[1]           # code is prefill-heavy, conversation less so
    assert rb.target((2, 2), 4, (1, 1), need=code) == (3, 1)
    with pytest.raises(ValueError, match="rate"):
        rb.need_from_mix(mix.DEFAULT, r, a, {})


def test_hysteresis_band_hold_and_cooldown():
    t = [0.0]
    h = rb.Rebalancer(band=0.2, hold=3, cooldown_s=100, clock=lambda: t[0])
    assert [h.propose("p", (2, 2), (3, 1)) for _ in range(3)] == [None, None, (3, 1)]
    assert h.propose("p", (3, 1), (2, 2)) is None and h.propose("p", (3, 1), (2, 2)) is None
    assert h.propose("p", (3, 1), (2, 2)) is None            # held 3 times but inside the cooldown
    t[0] = 200
    assert h.propose("p", (3, 1), (2, 2)) == (2, 2)
    assert h.propose("q", (5, 5), (5, 5)) is None             # no change wanted
    small = rb.Rebalancer(band=0.3, hold=1, cooldown_s=0)
    assert small.propose("p", (10, 8), (10, 8)) is None and small.propose("p", (9, 9), (10, 8)) is None


def _spec(tmp_path, metrics):
    m = tmp_path / "metrics.txt"
    m.write_text(metrics, encoding="utf-8")
    s = tmp_path / "spec.yaml"
    s.write_text(json.dumps({"namespace": "llm-serving", "pools": [
        {"pool": "llama8b-pd-pool", "model": M, "kv_transport": "shm", "budget": 3,
         "slo": {"ttft_p90_ms": 2000, "tpot_p90_ms": 100},
         "prefill": {"accelerator": "furiosa.RNGD"}, "decode": {"accelerator": "furiosa.RNGD"},
         "rebalance": {"metrics": str(m)}}]}), encoding="utf-8")
    return controller.load_spec(str(s)), m


def test_controller_rebalances_once_then_holds(tmp_path):
    spec, m = _spec(tmp_path, METRICS)
    io = FakeIO()
    perf = profiles.load()
    assert controller.run_once(spec, io, namespace="llm-serving", dry_run=False, perf=perf) == 0
    first = document.parse(io.cm)
    assert [len(d.accelerator_ids) for d in first.decisions] == [1, 1]
    run = lambda: controller.run_once(spec, io, namespace="llm-serving", dry_run=False, perf=perf,  # noqa: E731
                                      rebalancing=controller.Rebalancing(spec, perf, once=True))
    assert run() == 0
    second = document.parse(io.cm)
    assert second.generation == 2 and [len(d.accelerator_ids) for d in second.decisions] == [2, 1]
    assert run() == 0 and document.parse(io.cm).generation == 2       # same pressure, already 2:1
    m.write_text("vllm:num_requests_waiting{role=\"prefill\"} 0\n", encoding="utf-8")
    assert run() == 0 and document.parse(io.cm).generation == 2       # calm: no move back either


def test_unreadable_metrics_hold_the_split_and_still_place(tmp_path, capsys):
    spec, m = _spec(tmp_path, METRICS)
    m.unlink()                                       # the gateway is not up yet
    io = FakeIO()
    perf = profiles.load()
    rebal = controller.Rebalancing(spec, perf, once=True)
    assert controller.run_once(spec, io, namespace="llm-serving", dry_run=False, perf=perf,
                               rebalancing=rebal) == 0
    doc = document.parse(io.cm)
    assert [len(d.accelerator_ids) for d in doc.decisions] == [1, 1]   # placed, split unchanged
    assert "unreadable" in capsys.readouterr().err
