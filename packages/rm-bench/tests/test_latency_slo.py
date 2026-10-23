"""Unknown token timing must not count as measured latency or SLO attainment."""
import pytest

from rm_bench.client import _from_json_body
from rm_bench.e2e import _meets, judge
from rm_bench.results import RequestRecord, summarize


def test_json_without_server_timing_keeps_token_latency_unknown():
    record = _from_json_body({"choices": [{"text": "one two three"}],
                              "usage": {"completion_tokens": 3}}, 300.0)
    assert record.ok and record.out_tokens == 3 and record.e2e_ms == 300.0
    assert record.ttft_ms is None and record.tpot_ms is None
    assert {m.name for m in summarize([record], 1.0, {})} == {"tok_s", "req_s", "e2e_p90_ms"}


@pytest.mark.parametrize("ttft,wall", [
    (float("nan"), 100), (40, float("nan")),
    (float("inf"), 100), (40, float("inf")),
    (-1, 100), (40, -1), (True, 100), (0, False), (101, 100),
])
def test_invalid_server_timing_stays_unknown(ttft, wall):
    record = _from_json_body({"choices": [{"text": "one two three"}],
                              "usage": {"completion_tokens": 3},
                              "pd": {"ttft_ms": ttft, "wall_ms": wall}}, 300.0)
    assert record.ok and record.ttft_ms is None and record.tpot_ms is None
    assert not _meets(record, {"tpot_p90_ms": 100})
    assert not judge([record], 1.0, {"tpot_p90_ms": 100}, 0)["tpot_p90_ms"]["ok"]


@pytest.mark.parametrize("tokens", [True, False, -1, 0, float("nan"), float("inf"), "3", None])
def test_invalid_completion_token_count_uses_text_estimate(tokens):
    record = _from_json_body({"choices": [{"text": "one two three"}],
                              "usage": {"completion_tokens": tokens}}, 300.0)
    assert record.ok and type(record.out_tokens) is int and record.out_tokens == 3
    assert not _meets(record, {"tpot_p90_ms": 100})
    assert {m.name for m in summarize([record], 1.0, {})} == {"tok_s", "req_s", "e2e_p90_ms"}


@pytest.mark.parametrize("tokens,text", [(0, ""), (1, "one two three")])
def test_zero_without_output_and_single_token_count_remain_valid(tokens, text):
    record = _from_json_body({"choices": [{"text": text}],
                              "usage": {"completion_tokens": tokens}}, 300.0)
    assert record.ok and record.out_tokens == tokens and record.tpot_ms is None
    assert _meets(record, {"tpot_p90_ms": 100})
    assert judge([record], 1.0, {"tpot_p90_ms": 100}, 0)["tpot_p90_ms"]["ok"]


@pytest.mark.parametrize("metric,records,expected", [
    ("ttft_p90_ms", [RequestRecord(True, 300, None, None, 3)], False),
    ("tpot_p90_ms", [RequestRecord(True, 300, None, None, 3)], False),
    ("tpot_p90_ms", [RequestRecord(True, 300, 50, None, 3)], False),
    ("ttft_p90_ms", [RequestRecord(True, 300, 50, 10, 3), RequestRecord(True, 300, None, None, 3)], False),
    ("tpot_p90_ms", [RequestRecord(True, 300, 50, 10, 3), RequestRecord(True, 300, 50, None, 3)], False),
    ("tpot_p90_ms", [RequestRecord(True, 300, 50, None, 1)], True),
    ("tpot_p90_ms", [RequestRecord(True, 300, 50, None, 0)], True),
    ("tpot_p90_ms", [RequestRecord(True, 300, 50, 10, 3), RequestRecord(True, 300, 50, None, 1)], True),
    ("tpot_p90_ms", [], False),
])
def test_missing_timing_cannot_pass_latency_slo(metric, records, expected):
    slo = {metric: 100.0}
    assert all(_meets(r, slo) for r in records) == (expected or not records)
    check = judge(records, 1.0, slo, max_error_pct=0)[metric]
    assert check["ok"] is expected
    if not expected:
        assert check["measured"] is None
