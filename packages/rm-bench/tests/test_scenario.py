import pytest
from rm_core.errors import ContractError

from rm_bench.scenario import Scenario, load_scenario


def test_pd_smoke_definition():
    sc = load_scenario("pd-smoke")
    sched = sc.schedule()
    assert sc.name == "pd-smoke" and len(sched) == sc.requests["count"]
    assert sched == sc.schedule()  # seeded, reproducible
    assert all(b >= a for (a, _, _), (b, _, _) in zip(sched, sched[1:]))


def test_trace_source(tmp_path):
    csv = tmp_path / "trace.csv"
    csv.write_text("TIMESTAMP,ContextTokens,GeneratedTokens\n"
                   "2024-05-12 00:00:00.000000+00:00,100,10\n"
                   "2024-05-12 00:00:02.000000+00:00,200,20\n"
                   "2024-05-12 00:00:04.000000+00:00,300,30\n")
    sc = Scenario(name="t", requests={"source": "trace", "count": 2,
                                      "trace": {"csv": str(csv), "speedup": 2}}).validate()
    assert sc.schedule() == [(0.0, 100, 10), (1.0, 200, 20)]


def test_unknown_slo_key_rejected():
    with pytest.raises(ContractError):
        Scenario(name="x", requests={"count": 1}, slo={"latency_ms": 1}).validate()


def test_trace_stops_at_duration(tmp_path):
    csv = tmp_path / "trace.csv"
    rows = "".join(f"2024-05-12 00:00:{i:02d}.000000+00:00,10,5\n" for i in range(30))
    csv.write_text("TIMESTAMP,ContextTokens,GeneratedTokens\n" + rows)
    sc = Scenario(name="t", duration_s=5, requests={"source": "trace", "trace": {"csv": str(csv)}}).validate()
    assert [r[0] for r in sc.schedule()] == [0.0, 1.0, 2.0, 3.0, 4.0]


def test_bad_field_type_rejected():
    with pytest.raises(TypeError):
        Scenario(name="x", requests={"count": 1}, concurrency="8").validate()
