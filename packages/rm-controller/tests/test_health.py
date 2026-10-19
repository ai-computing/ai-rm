"""Health-aware placement: node pressure, unhealthy cards, and re-placing only the role that lost a card."""
from __future__ import annotations

import dataclasses
import json

from rm_core import k8s

from rm_controller import controller, document, kube
from rm_controller.policy import TopologyPlacement
from test_controller import POOL, D, FakeIO, M, P, rngd


def node(name, *, cordoned=False, ready=True, **conds):
    c = [{"type": "Ready", "status": "True" if ready else "False"}]
    c += [{"type": k, "status": "True" if v else "False"} for k, v in conds.items()]
    return {"metadata": {"name": name}, "spec": {"unschedulable": cordoned}, "status": {"conditions": c}}


def test_unschedulable_includes_pressure():
    nodes = [node("ok", DiskPressure=False), node("disk", DiskPressure=True), node("mem", MemoryPressure=True),
             node("cordon", cordoned=True), node("down", ready=False)]
    assert kube._unschedulable(nodes) == {"disk", "mem", "cordon", "down"}


def test_profile_status_marks_card_unhealthy():
    obj = k8s.accelerator_profile(rngd("n", 0))
    assert kube.profile(obj).extra.get("health") is None
    obj["status"] = {"conditions": [{"type": "Healthy", "status": "False"}]}
    assert kube.profile(obj).extra["health"] == "unhealthy"
    obj["status"] = {"health": "Failed"}
    assert kube.profile(obj).extra["health"] == "unhealthy"


def sick(a):
    return dataclasses.replace(a, extra={**a.extra, "health": "unhealthy"})


def test_topology_skips_unhealthy_cards_and_says_so():
    pool = [sick(rngd("n", 0)), rngd("n", 1), rngd("n", 2)]
    p, d = TopologyPlacement().place_pd(P, D, pool, kv_transport="shm")
    assert p.accelerator_ids == ["n/furiosa:1"] and d.accelerator_ids == ["n/furiosa:2"]
    p, _ = TopologyPlacement().place_pd(P, D, pool[:2], kv_transport="shm")
    assert p.accelerator_ids == [] and "skipped unhealthy n/furiosa:0" in p.reason


class LiveIO(FakeIO):
    def __init__(self, cards, unschedulable=("npu-node-2",)):
        super().__init__()
        self.cards, self.unsched = list(cards), set(unschedulable)

    def profiles(self):
        return self.cards

    def unschedulable_nodes(self):
        return self.unsched


def _spec(tmp_path):
    s = tmp_path / "spec.yaml"
    s.write_text(json.dumps({"pools": [{"pool": "pd", "model": M, "kv_transport": "shm",
                                        "prefill": {"accelerator": "furiosa.RNGD"},
                                        "decode": {"accelerator": "furiosa.RNGD"}}]}), encoding="utf-8")
    return controller.load_spec(str(s))


def _ids(io):
    return [d.accelerator_ids for d in document.parse(io.cm).decisions]


def run(spec, io):
    return controller.run_once(spec, io, namespace="llm-serving", dry_run=False)


def test_lost_decode_card_re_places_decode_only(tmp_path):
    spec, io = _spec(tmp_path), LiveIO(POOL)
    run(spec, io)
    assert _ids(io) == [["npu-node-1/furiosa:0"], ["npu-node-1/furiosa:1"]]
    io.cards = [a for a in POOL if a.id != "npu-node-1/furiosa:1"]          # the decode card disappears
    run(spec, io)
    doc = document.parse(io.cm)
    assert doc.generation == 2 and _ids(io) == [["npu-node-1/furiosa:0"], ["npu-node-1/furiosa:3"]]
    assert "re-placed decode (npu-node-1/furiosa:1 gone)" in doc.decisions[1].reason
    run(spec, io)
    assert document.parse(io.cm).generation == 2                            # stable afterwards


def test_unhealthy_prefill_card_re_places_prefill_only(tmp_path):
    spec, io = _spec(tmp_path), LiveIO(POOL)
    run(spec, io)
    io.cards = [sick(a) if a.id == "npu-node-1/furiosa:0" else a for a in POOL]
    run(spec, io)
    doc = document.parse(io.cm)
    assert doc.generation == 2 and _ids(io) == [["npu-node-1/furiosa:3"], ["npu-node-1/furiosa:1"]]
    assert "unhealthy" in doc.decisions[0].reason and "decode kept" in doc.decisions[0].reason


def test_node_lost_re_places_both_and_a_recovered_node_does_not_cause_churn(tmp_path):
    spec, io = _spec(tmp_path), LiveIO(POOL)
    run(spec, io)
    io.unsched = {"npu-node-1"}
    io.cards = POOL
    run(spec, io)
    assert _ids(io) == [["npu-node-2/furiosa:0"], ["npu-node-2/furiosa:1"]]
    assert "node npu-node-1 unschedulable" in document.parse(io.cm).decisions[0].reason
    io.unsched = set()                                                      # npu-node-1 is back
    run(spec, io)
    assert document.parse(io.cm).generation == 2 and _ids(io)[0] == ["npu-node-2/furiosa:0"]


def test_spec_change_is_placed_fresh(tmp_path):
    spec, io = _spec(tmp_path), LiveIO(POOL)
    run(spec, io)
    spec["pools"][0]["decode"]["count"] = 2
    run(spec, io)
    assert _ids(io) == [["npu-node-1/furiosa:0"], ["npu-node-1/furiosa:1", "npu-node-1/furiosa:3"]]
