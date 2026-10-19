"""Power samplers with fakes: a stdlib Prometheus API, a command printing watts, and an e2e run."""
from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from rm_bench import cli, power
from rm_bench.results import read_run


def test_summarize_trapezoid_and_energy():
    s = power.summarize([(0.0, 100.0), (1.0, 200.0), (3.0, 200.0)], window_s=10.0, source="x",
                        scope="card", out_tokens=5000)
    # (1 x 150 + 2 x 200) / 3 s
    assert s.mean_w == pytest.approx(550.0 / 3)
    assert s.peak_w == 200.0 and s.samples == 3
    assert s.energy_j == pytest.approx(s.mean_w * 10.0)
    assert s.tok_per_j == pytest.approx(5000 / s.energy_j)
    assert power.summarize([], 1.0, source="x", scope="card") is None
    one = power.summarize([(0.5, 80.0)], 2.0, source="x", scope="node")
    assert one.mean_w == 80.0 and one.energy_j == 160.0


def test_command_regex_sums_matches():
    smi = ("+------+--------+---------+\n| NPU  | Temp   | Power   |\n"
           "| npu0 | 40.1C  | 41.25 W |\n| npu1 | 39.8C  | 38.75 W |\n")
    cp = power.CommandPower(command="unused")
    assert cp.parse(smi) == pytest.approx(80.0)
    assert cp.parse("no numbers") is None
    # draw / cap columns: match only the draw
    capped = power.CommandPower(command="unused", regex=r"(\d+(?:\.\d+)?)W\s*/")
    assert capped.parse("rbln0  55.0W / 150.0W\nrbln1  45.0W / 150.0W") == pytest.approx(100.0)


def test_command_sampler_runs_a_command():
    cmd = f'"{sys.executable}" -c "print(\'Power: 150.5 W\')"'
    s = power.make_sampler("cmd", command=cmd, interval_s=0.05)
    s.start()
    threading.Event().wait(0.3)
    summary = s.stop(window_s=2.0, out_tokens=301)
    assert summary.source == "cmd" and summary.samples >= 2 and s.errors == 0
    assert summary.mean_w == pytest.approx(150.5) and summary.peak_w == pytest.approx(150.5)
    assert summary.energy_j == pytest.approx(301.0) and summary.tok_per_j == pytest.approx(1.0)


class FakeProm(BaseHTTPRequestHandler):
    queries: list = []
    watts = (300.0, 250.0)       # one series per GPU

    def log_message(self, *args):
        pass

    def do_GET(self):
        u = urlparse(self.path)
        assert u.path == "/api/v1/query"
        self.queries.append(parse_qs(u.query)["query"][0])
        result = [{"metric": {"gpu": str(i)}, "value": [1760000000.0, str(w)]} for i, w in enumerate(self.watts)]
        body = json.dumps({"status": "success", "data": {"resultType": "vector", "result": result}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def prom():
    handler = type("P", (FakeProm,), {"queries": []})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}", handler
    srv.shutdown()
    srv.server_close()


def test_prometheus_sampler_sums_series(prom):
    url, h = prom
    s = power.make_sampler("prom", url=url, interval_s=0.05)
    assert s.read_w() == pytest.approx(550.0)
    assert h.queries[-1] == power.DEFAULT_PROM_QUERY
    npu = power.make_sampler("prom", url=url, query='sum(airm_power_w{scope="card"})')
    npu.read_w()
    assert h.queries[-1] == 'sum(airm_power_w{scope="card"})'


def test_unreachable_source_loses_samples_not_the_run():
    s = power.make_sampler("prom", url="http://127.0.0.1:9", interval_s=0.05)
    s.start()
    assert s.stop(window_s=1.0) is None and s.errors >= 2


def test_bad_config():
    with pytest.raises(ValueError):
        power.make_sampler("prom")              # no URL
    with pytest.raises(ValueError):
        power.make_sampler("cmd")               # no command
    with pytest.raises(ValueError):
        power.make_sampler("cmd", command="x", scope="rack")
    assert power.make_sampler("none") is None


def test_e2e_records_power_and_tok_per_j(prom, tmp_path, monkeypatch):
    from test_e2e import FakeOpenAI   # noqa: PLC0415 -- reuse the streaming fake gateway

    gw = ThreadingHTTPServer(("127.0.0.1", 0), type("G", (FakeOpenAI,), {}))
    threading.Thread(target=gw.serve_forever, daemon=True).start()
    url, _ = prom
    monkeypatch.setenv("PROMETHEUS_URL", url)
    out = tmp_path / "pw.json"
    sc = tmp_path / "small.yaml"
    sc.write_text("name: small\nrequests: {count: 6, max_tokens: 'const:8'}\nconcurrency: 3\n"
                  "slo: {ttft_p90_ms: 60000}\n")
    try:
        rc = cli.main(["e2e", "--gateway", f"http://127.0.0.1:{gw.server_port}", "--scenario", str(sc),
                       "--out", str(out), "--power", "prom", "--power-interval", "0.05",
                       "--deployment", "same-vendor-pd", "--cards", "2"])
    finally:
        gw.shutdown()
        gw.server_close()
    assert rc == 0
    measurements, runs = read_run(str(out))
    by = {m.name: m for m in measurements}
    assert by["power_w"].value == pytest.approx(550.0) and by["power_w"].tags["scope"] == "card"
    assert by["energy_j"].value > 0 and by["accelerators"].value == 2.0
    (rec,) = runs.values()
    assert rec["deployment"] == "same-vendor-pd" and rec["cards"] == 2 and rec["passed"]
    assert rec["power"]["power_peak_w"] == pytest.approx(550.0)
    assert rec["power"]["tok_per_j"] == pytest.approx(48 / by["energy_j"].value)
    assert rec["goodput_req_s"] > 0 and rec["itl_p90_ms"] >= 0
