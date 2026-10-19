"""Topology placement on a pool shaped like the lab cluster, the document, and a dry run with fake cluster IO."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from rm_core import Accelerator, Workload
from rm_core.conformance import check_placement

from rm_controller import controller, document
from rm_controller.policy import ACCEL_LABEL, RoleSpec, TopologyPlacement

GB = 1 << 30


def rngd(node, i):
    return Accelerator(id=f"{node}/furiosa:{i}", node=node, vendor="furiosa", model="RNGD", memory_bytes=48 * GB,
                       memory_kind="hbm", peak_tflops={"bf16": 256.0, "fp8": 512.0}, peak_source="datasheet")


def atom(node, i):
    return Accelerator(id=f"{node}/rebellions:{i}", node=node, vendor="rebellions", model="ATOM",
                       memory_bytes=16 * GB, memory_kind="gddr", peak_tflops={"fp16": 32.0, "int8": 128.0},
                       peak_source="datasheet")


# npu-node-1: RNGD 0,1,3 + ATOM 0-3; esc8000: RNGD 0,1 (cordoned during the end-to-end run)
POOL = ([rngd("npu-node-1", i) for i in (0, 1, 3)] + [atom("npu-node-1", i) for i in range(4)]
        + [rngd("npu-node-2", i) for i in (0, 1)])
M = "meta-llama/Llama-3.1-8B-Instruct"
P, D = Workload(kind="prefill", model=M), Workload(kind="decode", model=M)


def test_conformance():
    check_placement(TopologyPlacement())
    check_placement(TopologyPlacement(), POOL)


def test_shm_pair_lands_on_one_node_distinct_cards():
    p, d = TopologyPlacement({"npu-node-2"}).place_pd(
        P, D, POOL, kv_transport="shm", prefill_spec=RoleSpec("furiosa.RNGD"), decode_spec=RoleSpec("furiosa.RNGD"))
    assert p.accelerator_ids == ["npu-node-1/furiosa:0"] and d.accelerator_ids == ["npu-node-1/furiosa:1"]
    assert p.kv_transport == d.kv_transport == "shm" and "on npu-node-1" in p.reason


def test_without_node_state_the_node_with_more_free_cards_wins():
    p, d = TopologyPlacement().place_pd(P, D, POOL, kv_transport="shm",
                                        prefill_spec=RoleSpec("furiosa.RNGD"), decode_spec=RoleSpec("furiosa.RNGD"))
    assert p.accelerator_ids[0].startswith("npu-node-1/") and d.accelerator_ids[0].startswith("npu-node-1/")


def test_greedy_reference_failure_is_avoided():
    # rm-core's greedy put prefill and decode on the same card of the cordoned node with loopback.
    p, d = TopologyPlacement({"npu-node-2"}).place_pd(P, D, POOL, kv_transport="shm")
    assert not set(p.accelerator_ids) & set(d.accelerator_ids)
    assert all(not i.startswith("npu-node-2/") for i in p.accelerator_ids + d.accelerator_ids)


def test_hetero_p2p_rngd_prefill_atom_decode_one_to_two():
    p, d = TopologyPlacement().place_pd(P, D, POOL, kv_transport="p2p", prefill_spec=RoleSpec("furiosa.RNGD"),
                                        decode_spec=RoleSpec("rebellions.ATOM", 2))
    assert p.accelerator_ids == ["npu-node-1/furiosa:0"]
    assert d.accelerator_ids == ["npu-node-1/rebellions:0", "npu-node-1/rebellions:1"]


def test_loopback_may_share_a_card():
    p, d = TopologyPlacement().place_pd(P, D, [rngd("n", 0)], kv_transport="loopback")
    assert p.accelerator_ids == d.accelerator_ids == ["n/furiosa:0"]


def test_used_cards_are_not_offered_again_and_empty_has_a_reason():
    pl = TopologyPlacement({"npu-node-2"})
    spec = dict(prefill_spec=RoleSpec("furiosa.RNGD"), decode_spec=RoleSpec("furiosa.RNGD", 2))
    p, d = pl.place_pd(P, D, POOL, kv_transport="shm", **spec)
    assert p.accelerator_ids == ["npu-node-1/furiosa:0"] and d.accelerator_ids == ["npu-node-1/furiosa:1", "npu-node-1/furiosa:3"]
    p2, d2 = pl.place_pd(P, D, POOL, kv_transport="shm", used=p.accelerator_ids + d.accelerator_ids, **spec)
    assert p2.accelerator_ids == d2.accelerator_ids == []
    assert "furiosa.RNGD" in p2.reason and "npu-node-2" in p2.reason and "already placed" in p2.reason


def test_place_single_respects_label_and_node_state():
    pl = TopologyPlacement({"npu-node-1"})
    d = pl.place(Workload(kind="decode", model=M, labels={ACCEL_LABEL: "rebellions.ATOM"}), POOL)
    assert d.accelerator_ids == [] and "skipped unschedulable npu-node-1" in d.reason
    d = TopologyPlacement().place(Workload(kind="prefill", model=M), POOL)
    assert d.accelerator_ids == ["npu-node-1/furiosa:0"]


def test_document_generation_moves_only_on_change():
    e = [document.decision_entry("pool", P, TopologyPlacement().place(P, POOL))]
    t = datetime(2026, 10, 19, tzinfo=timezone.utc)
    doc1, ch1 = document.build(e, document.parse(None), "topology", now=t)
    assert ch1 and doc1["generation"] == 1 and doc1["updatedAt"] == "2026-10-19T00:00:00Z"
    doc2, ch2 = document.build(e, doc1, "topology")
    assert not ch2 and doc2 is doc1
    cm = document.configmap(doc1, "llm-serving")
    assert document.parse(cm) == doc1 and cm["metadata"]["name"] == "airm-placement"


class FakeIO:
    def __init__(self, cm=None):
        self.cm, self.applied = cm, []

    def profiles(self):
        return POOL

    def unschedulable_nodes(self):
        return {"npu-node-2"}

    def placement_configmap(self, namespace):
        return self.cm

    def apply(self, obj):
        self.applied.append(obj)
        self.cm = obj


def _spec(tmp_path, decode_count=1):
    s = tmp_path / "spec.yaml"
    s.write_text(json.dumps({"namespace": "llm-serving", "pools": [
        {"pool": "llama8b-pd-pool", "model": M, "kv_transport": "shm",
         "prefill": {"accelerator": "furiosa.RNGD"}, "decode": {"accelerator": "furiosa.RNGD", "count": decode_count}}]}),
        encoding="utf-8")
    return str(s)


def test_run_once_writes_then_stays_quiet(tmp_path, capsys):
    io = FakeIO()
    spec = controller.load_spec(_spec(tmp_path))
    assert controller.run_once(spec, io, namespace="llm-serving", dry_run=False) == 0
    doc = document.parse(io.cm)
    assert doc["generation"] == 1 and [x["acceleratorIds"] for x in doc["decisions"]] == [
        ["npu-node-1/furiosa:0"], ["npu-node-1/furiosa:1"]]
    assert controller.run_once(spec, io, namespace="llm-serving", dry_run=False) == 0
    assert len(io.applied) == 1 and "unchanged" in capsys.readouterr().err


def test_dry_run_prints_and_unplaceable_exits_1(tmp_path, capsys):
    io = FakeIO()
    spec = controller.load_spec(_spec(tmp_path, decode_count=3))
    assert controller.run_once(spec, io, namespace="llm-serving", dry_run=True) == 1
    out = json.loads(capsys.readouterr().out)
    assert out["decisions"][0]["acceleratorIds"] == [] and io.applied == []


def test_spec_validation(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("pools: [{pool: x}]", encoding="utf-8")
    with pytest.raises(ValueError, match="missing"):
        controller.load_spec(str(bad))
