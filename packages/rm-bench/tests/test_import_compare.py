"""rm-bench import (GuideLLM, MLPerf LoadGen) and compare, on fixture files in their real formats."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from rm_core.metrics import METRICS

from rm_bench import cli
from rm_bench.results import Measurement, meta_path, read_run, write_run

FIX = Path(__file__).parent / "fixtures"


def _by_run(measurements):
    out: dict[str, dict[str, float]] = {}
    for m in measurements:
        assert m.name in METRICS
        out.setdefault(m.tags["run_id"], {})[m.name] = m.value
    return out


def test_import_guidellm_sweep(tmp_path, capsys):
    out = tmp_path / "gl.json"
    rc = cli.main(["import", "guidellm", str(FIX / "guidellm-benchmarks.json"), "--out", str(out),
                   "--deployment", "vendor-pd", "--cards", "2", "--slo", "ttft_p90_ms=1000"])
    assert rc == 0
    measurements, runs = read_run(str(out))
    by = _by_run(measurements)
    assert list(by) == ["guidellm-benchmarks-0-constant-2rps", "guidellm-benchmarks-1-constant-8rps"]
    low, high = by.values()
    assert low["ttft_p90_ms"] == 240 and low["tpot_p99_ms"] == 33 and low["ttft_p50_ms"] == 170
    assert low["tok_s"] == pytest.approx(120 * 128 / 60.0)       # output tokens over the measured window
    assert low["req_s"] == pytest.approx(2.0)
    assert low["e2e_p90_ms"] == pytest.approx(1900.0)            # request_latency is in seconds
    assert low["slo_attainment_pct"] == pytest.approx(99.0) and low["accelerators"] == 2
    m0 = next(m for m in measurements if m.name == "tok_s")
    assert m0.tags["model"] == "meta-llama/Llama-3.1-8B-Instruct"
    assert m0.tags["workload"] == "guidellm-constant-2rps"
    r0, r1 = runs.values()
    assert r0["passed"] and not r1["passed"]                     # 1900 ms TTFT p90 at 8 rps
    assert r0["goodput_req_s"] == pytest.approx(1.98) and r0["deployment"] == "vendor-pd"
    assert r0["itl_p90_ms"] == pytest.approx(26 * 1.01)
    assert "FAIL  ttft_p90_ms" in capsys.readouterr().out


def test_import_guidellm_old_layout(tmp_path):
    # GuideLLM < 0.4: no p50 in percentiles (median only), timing under run_stats, args.strategy
    report = json.loads((FIX / "guidellm-benchmarks.json").read_text())
    b = report["benchmarks"][0]
    sm = b.pop("scheduler_metrics")
    b["run_stats"] = {"start_time": sm["measure_start_time"], "end_time": sm["measure_end_time"]}
    b["args"] = {"strategy": b.pop("config")["strategy"]}
    for d in b["metrics"]["time_to_first_token_ms"].values():
        d["percentiles"].pop("p50")
    report["benchmarks"] = [b]
    src = tmp_path / "old.json"
    src.write_text(json.dumps(report))
    out = tmp_path / "old-out.json"
    assert cli.main(["import", "guidellm", str(src), "--out", str(out)]) == 0
    (vals,) = _by_run(read_run(str(out))[0]).values()
    assert vals["ttft_p50_ms"] == 170 and vals["tok_s"] == pytest.approx(256.0)


@pytest.mark.parametrize("name", ["mlperf_log_summary.txt", "mlperf_log_detail.txt"])
def test_import_mlperf(tmp_path, name):
    out = tmp_path / "mlperf.json"
    rc = cli.main(["import", "mlperf", str(FIX / name), "--out", str(out),
                   "--model", "meta-llama/Llama-3.1-8B-Instruct", "--deployment", "replication"])
    assert rc == 0
    measurements, runs = read_run(str(out))
    (vals,) = _by_run(measurements).values()
    assert vals["tok_s"] == pytest.approx(1262.41) and vals["req_s"] == pytest.approx(9.87)
    assert vals["ttft_p99_ms"] == pytest.approx(1456.789012) and vals["ttft_p50_ms"] == pytest.approx(256.789012)
    assert vals["tpot_p99_ms"] == pytest.approx(52.345678) and vals["tpot_p90_ms"] == pytest.approx(24.56789)
    assert vals["e2e_p90_ms"] == pytest.approx(3456.789012)
    assert "slo_attainment_pct" not in vals          # LoadGen reports no per-request SLO share
    (rec,) = runs.values()
    assert rec["scenario"] == "Server" and rec["passed"]
    assert rec["checks"]["ttft_p99_ms"]["target"] == 2000.0 and rec["checks"]["tpot_p99_ms"]["target"] == 100.0
    assert rec["checks"]["mlperf_valid"]["ok"]


def test_import_mlperf_invalid_fails_verdict(tmp_path):
    text = (FIX / "mlperf_log_summary.txt").read_text().replace("Result is : VALID", "Result is : INVALID")
    src = tmp_path / "mlperf_log_summary.txt"
    src.write_text(text)
    out = tmp_path / "inv.json"
    assert cli.main(["import", "mlperf", str(src), "--out", str(out)]) == 0
    (rec,) = read_run(str(out))[1].values()
    assert not rec["passed"] and not rec["checks"]["mlperf_valid"]["ok"]


def test_import_rejects_other_files(tmp_path):
    bad = tmp_path / "x.json"
    bad.write_text("{}")
    assert cli.main(["import", "guidellm", str(bad), "--out", str(tmp_path / "o.json")]) == 2
    assert cli.main(["import", "mlperf", str(bad), "--out", str(tmp_path / "o.json")]) == 2
    assert cli.main(["import", "mlperf", str(FIX / "mlperf_log_summary.txt"), "--slo", "bogus=1"]) == 2


def test_compare_table(tmp_path, capsys):
    tags = {"component": "rm-bench", "workload": "pd-smoke", "run_id": "e2e-1"}
    e2e = tmp_path / "e2e.json"
    write_run(str(e2e), [Measurement("slo_attainment_pct", 97.5, tags), Measurement("tok_s", 400.0, tags),
                         Measurement("req_s", 4.0, tags), Measurement("ttft_p90_ms", 180.0, tags),
                         Measurement("tpot_p90_ms", 20.0, tags),
                         Measurement("power_w", 500.0, dict(tags, scope="card"))],
              {"e2e-1": {"source": "rm-bench e2e", "deployment": "same-vendor-pd", "cards": 2, "passed": True,
                         "goodput_req_s": 3.9, "power": {"tok_per_j": 0.8, "power_peak_w": 610.0}}})
    gl = tmp_path / "gl.json"
    assert cli.main(["import", "guidellm", str(FIX / "guidellm-benchmarks.json"), "--out", str(gl),
                     "--cards", "4"]) == 0
    plain = tmp_path / "loadgen.json"           # a loadgen/ output: Measurements only, no run record
    plain.write_text(json.dumps([{"name": "tok_s", "value": 100.0, "tags": {"component": "rm-bench", "run_id": "lg"}},
                                 {"name": "power_w", "value": 250.0,
                                  "tags": {"component": "rm-bench", "run_id": "lg", "scope": "node"}}]))
    assert not Path(meta_path(str(plain))).exists()
    md = tmp_path / "cmp.md"
    capsys.readouterr()
    # a shell glob also passes the .meta.json records: they map to their result file once
    assert cli.main(["compare", str(e2e), meta_path(str(e2e)), f"vendor-pd={gl}", f"replication={plain}",
                     "--out", str(md)]) == 0
    text = md.read_text(encoding="utf-8")
    assert text == capsys.readouterr().out
    lines = text.splitlines()
    assert lines[0].startswith("| Deployment | Run | Source | SLO |") and len(lines) == 2 + 4
    row = lines[2]
    assert row.startswith("| same-vendor-pd | `e2e-1` | rm-bench e2e | 97.5 % PASS |")
    assert "| 3.90 | 1.95 | 500.0 (610.0) | 0.80 |" in row      # goodput, per card, power (peak), tok/J
    gl_row = lines[3]
    assert gl_row.startswith("| vendor-pd | `guidellm-benchmarks-0-constant-2rps` | guidellm | 99.0 % |")
    assert "| 1.98 | 0.49 |" in gl_row
    assert lines[5].startswith("| replication | `lg` | — | — |") and lines[5].endswith("| 250.0 | 0.40 |")
