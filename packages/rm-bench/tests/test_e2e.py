"""rm-bench e2e against a fake OpenAI-compatible server started inside the test."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from rm_core import Workload, registry
from rm_core.errors import ContractError
from rm_core.metrics import METRICS, TAG_KEYS

from rm_bench import cli
from rm_bench.e2e import E2E_METRICS
from rm_bench.results import from_json

MODEL = "fake-model"


class FakeOpenAI(BaseHTTPRequestHandler):
    """Streams one content chunk per requested token, then a usage chunk and [DONE].

    Uses HTTP/1.1 chunked transfer like vLLM/llm-d, so clients see each event as it is sent.
    """
    protocol_version = "HTTP/1.1"
    fail = False
    junk_events = False   # send non-object / malformed events a real gateway might emit
    token_delay_s = 0.002

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        body = json.dumps({"object": "list", "data": [{"id": MODEL, "object": "model"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/v1/chat/completions" or self.fail:
            self.send_error(503)
            return
        assert req["stream"] is True and req["model"] == MODEL
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

        def send(obj):
            data = obj if isinstance(obj, str) else json.dumps(obj)
            event = f"data: {data}\n\n".encode()
            self.wfile.write(b"%x\r\n%s\r\n" % (len(event), event))
            self.wfile.flush()

        n = req["max_tokens"]
        if self.junk_events:
            send("keepalive-not-json")
            send('"just a string"')
            send({"choices": ["not-an-object"], "usage": None})
        for i in range(n):
            time.sleep(self.token_delay_s)
            send({"choices": [{"index": 0, "delta": {"content": f"t{i} "}}]})
        send({"choices": [], "usage": {"prompt_tokens": 1, "completion_tokens": n}})
        send("[DONE]")
        self.wfile.write(b"0\r\n\r\n")


@pytest.fixture
def gateway():
    handler = type("Handler", (FakeOpenAI,), {})
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", handler
    srv.shutdown()
    srv.server_close()


def _check_file(path):
    items = json.loads(path.read_text())
    assert isinstance(items, list) and items
    for it in items:
        assert set(it) == {"name", "value", "tags"}
        assert it["name"] in METRICS and set(it["tags"]) <= set(TAG_KEYS)
    from_json(items)  # validate() every entry
    return {it["name"]: it for it in items}


def test_pd_smoke_writes_valid_measurements(gateway, tmp_path, capsys):
    url, _ = gateway
    out = tmp_path / "run.json"
    rc = cli.main(["e2e", "--gateway", url, "--scenario", "pd-smoke", "--out", str(out)])
    assert rc == 0, capsys.readouterr().out
    by_name = _check_file(out)
    assert set(by_name) == set(E2E_METRICS)
    assert by_name["slo_attainment_pct"]["value"] == 100.0
    assert by_name["tok_s"]["value"] > 0
    assert by_name["tpot_p90_ms"]["value"] > 0  # tokens were timed as they streamed
    tags = by_name["tok_s"]["tags"]
    assert tags["component"] == "rm-bench" and tags["workload"] == "pd-smoke" and tags["model"] == MODEL
    assert "SLO PASS" in capsys.readouterr().out


def test_gateway_from_env(gateway, tmp_path, monkeypatch):
    url, _ = gateway
    monkeypatch.setenv("LLMD_GATEWAY_URL", url)
    out = tmp_path / "env.json"
    assert cli.main(["e2e", "--scenario", "pd-smoke", "--out", str(out)]) == 0
    _check_file(out)


def test_failing_gateway_fails_slo(gateway, tmp_path):
    url, handler = gateway
    handler.fail = True
    out = tmp_path / "fail.json"
    assert cli.main(["e2e", "--gateway", url, "--scenario", "pd-smoke", "--out", str(out)]) == 1
    by_name = _check_file(out)
    assert by_name["slo_attainment_pct"]["value"] == 0.0
    assert "ttft_p90_ms" not in by_name  # no samples -> omitted, never reported as 0


def test_missing_gateway_is_usage_error(monkeypatch):
    monkeypatch.delenv("LLMD_GATEWAY_URL", raising=False)
    assert cli.main(["e2e", "--scenario", "pd-smoke"]) == 2


def test_workload_entry_point(gateway, tmp_path):
    url, _ = gateway
    runner = registry.load("airm.workloads", "rm-bench")
    out = tmp_path / "wl.json"
    res = runner(Workload(kind="serve", model=MODEL, slo={"ttft_p90_ms": 60000}),
                 scenario="pd-smoke", gateway=url, out=str(out), kv_transport="loopback")
    assert res.passed and set(res.slo) == {"ttft_p90_ms"}
    by_name = _check_file(out)
    assert by_name["tok_s"]["tags"]["kv_transport"] == "loopback"
    with pytest.raises(ContractError):
        runner(Workload(kind="train", model=MODEL), scenario="pd-smoke", gateway=url, out=None)


def test_malformed_events_do_not_abort_run(gateway, tmp_path):
    url, handler = gateway
    handler.junk_events = True
    out = tmp_path / "junk.json"
    assert cli.main(["e2e", "--gateway", url, "--scenario", "pd-smoke", "--out", str(out)]) == 0
    assert _check_file(out)["slo_attainment_pct"]["value"] == 100.0


def test_unreachable_gateway_is_setup_error():
    # nothing listens on port 9 (discard); model discovery fails -> exit 2, not "SLO failed"
    assert cli.main(["e2e", "--gateway", "http://127.0.0.1:9", "--scenario", "pd-smoke"]) == 2


def test_no_slo_reports_success_rate(gateway, tmp_path):
    url, _ = gateway
    sc = tmp_path / "noslo.yaml"
    sc.write_text("name: noslo\nrequests: {count: 4, max_tokens: 'const:4'}\nconcurrency: 2\n")
    out = tmp_path / "noslo.json"
    assert cli.main(["e2e", "--gateway", url, "--scenario", str(sc), "--out", str(out)]) == 0
    assert _check_file(out)["slo_attainment_pct"]["value"] == 100.0
