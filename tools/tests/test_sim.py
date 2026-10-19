"""The simulated-cluster pieces that need no kind: the fake PD pool, the placement and bench checks,
and e2e-sim --no-cluster (when rm-controller and rm-bench are installed)."""
import copy
import json
import os
import sys
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import airm_sim  # noqa: E402
import fake_openai  # noqa: E402


@pytest.fixture
def server():
    srv = fake_openai.serve(model="m", token_delay_s=0)
    yield "http://127.0.0.1:%d" % srv.server_address[1]
    srv.shutdown()


def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return urllib.request.urlopen(req, timeout=10)


def test_models(server):
    data = json.load(urllib.request.urlopen(server + "/v1/models", timeout=10))
    assert [m["id"] for m in data["data"]] == ["m"]


def test_streaming_chat(server):
    with post(server + "/v1/chat/completions",
              {"model": "m", "stream": True, "max_tokens": 3, "messages": [{"role": "user", "content": "hi"}]}) as r:
        assert r.headers["Content-Type"] == "text/event-stream"
        events = [line[len("data: "):] for line in r.read().decode().splitlines() if line.startswith("data: ")]
    assert events[-1] == "[DONE]"
    chunks = [json.loads(e) for e in events[:-1]]
    text = "".join(c["choices"][0]["delta"]["content"] for c in chunks if c["choices"])
    assert text == "t0 t1 t2 "
    assert chunks[-1]["usage"]["completion_tokens"] == 3


def test_plain_chat_and_completions(server):
    with post(server + "/v1/chat/completions", {"model": "m", "max_tokens": 2, "messages": []}) as r:
        assert json.load(r)["choices"][0]["message"]["content"] == "t0 t1 "
    with post(server + "/v1/completions", {"model": "m", "max_tokens": 4, "prompt": "x"}) as r:
        body = json.load(r)
    assert body["usage"]["completion_tokens"] == 4 and body["pd"]["wall_ms"] >= body["pd"]["ttft_ms"] >= 0


def test_unknown_model_and_route(server):
    for path, body in (("/v1/chat/completions", {"model": "other"}), ("/v1/embeddings", {"model": "m"})):
        with pytest.raises(urllib.error.HTTPError) as e:
            post(server + path, body)
        assert e.value.code == 404


POOLS = [
    {"pool": "a", "kv_transport": "shm", "prefill": {"accelerator": "furiosa.RNGD", "count": 1},
     "decode": {"accelerator": "rebellions.ATOM", "count": 1}},
    {"pool": "b", "kv_transport": "p2p", "prefill": {"accelerator": "furiosa.RNGD", "count": 1},
     "decode": {"accelerator": "rebellions.ATOM", "count": 1}},
]
DEVICES = {f"{n}/furiosa:0": (n, "furiosa.RNGD") for n in ("n1", "n2")}
DEVICES.update({f"{n}/rebellions:0": (n, "rebellions.ATOM") for n in ("n1", "n2")})


def decision(pool, kind, ids, kv):
    return {"pool": pool, "workload": {"kind": kind}, "acceleratorIds": ids, "kvTransport": kv, "reason": ""}


GOOD = {"protocol": "0.1", "generation": 1, "placement": "topology", "decisions": [
    decision("a", "prefill", ["n1/furiosa:0"], "shm"), decision("a", "decode", ["n1/rebellions:0"], "shm"),
    decision("b", "prefill", ["n2/furiosa:0"], "p2p"), decision("b", "decode", ["n2/rebellions:0"], "p2p")]}


def test_check_placement_accepts_expected_document():
    assert airm_sim.check_placement(GOOD, POOLS, DEVICES, min_nodes=2) == []


@pytest.mark.parametrize("mutate, expect", [
    (lambda d: d.update(generation=0), "not written by rm-controller"),
    (lambda d: d["decisions"].pop(), "roles ['prefill']"),
    (lambda d: d["decisions"][1].update(acceleratorIds=[]), "0 card(s)"),
    (lambda d: d["decisions"][1].update(acceleratorIds=["n1/furiosa:0"]), "is furiosa.RNGD, expected rebellions.ATOM"),
    (lambda d: d["decisions"][1].update(acceleratorIds=["n2/rebellions:0"]), "shm needs one node"),
    (lambda d: d["decisions"][3].update(acceleratorIds=["n1/rebellions:0"]), "already placed"),
    (lambda d: d["decisions"][0].update(kvTransport="loopback"), "kvTransport loopback"),
    (lambda d: d["decisions"][0].update(acceleratorIds=["n9/furiosa:0"]), "not an AcceleratorProfile"),
])
def test_check_placement_reports(mutate, expect):
    doc = copy.deepcopy(GOOD)
    mutate(doc)
    errs = airm_sim.check_placement(doc, POOLS, DEVICES, min_nodes=1)
    assert any(expect in e for e in errs), errs


def test_check_placement_spread():
    doc = copy.deepcopy(GOOD)
    doc["decisions"] = doc["decisions"][:2]
    assert any("expected at least 2" in e for e in airm_sim.check_placement(doc, POOLS[:1], DEVICES, min_nodes=2))


def test_check_bench():
    ok = [{"name": "slo_attainment_pct", "value": 100.0}, {"name": "tok_s", "value": 50.0}]
    assert airm_sim.check_bench(ok, 0) == []
    assert airm_sim.check_bench(ok, 1) == ["rm-bench exited 1"]
    bad = [{"name": "slo_attainment_pct", "value": 96.875}, {"name": "tok_s", "value": 50.0}]
    assert "expected 100" in airm_sim.check_bench(bad, 1)[1]


def test_sim_values_pools_match_the_checks():
    pools = airm_sim.sim_pools()
    assert len(pools) == 2 and {p["kv_transport"] for p in pools} <= set(airm_sim.HOST_LOCAL)


@pytest.mark.skipif(not all(__import__("importlib").util.find_spec(m) for m in ("rm_controller", "rm_bench")),
                    reason="needs pip install -e packages/rm-controller packages/rm-bench")
def test_e2e_sim_no_cluster(tmp_path):
    class Args:
        no_cluster = True
        out = str(tmp_path / "sim.json")
    assert airm_sim.cmd_e2e(Args) == 0
    names = {m["name"] for m in json.load(open(Args.out))}
    assert {"slo_attainment_pct", "tok_s", "ttft_p90_ms"} <= names
