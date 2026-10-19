"""tools/kv_tier_curve.py: stack distances, prefix hits and the two-tier split on a tiny Mooncake-format trace."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location("kv_tier_curve", Path(__file__).parents[1] / "tools" / "kv_tier_curve.py")
kv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(kv)

# request = (prompt tokens, block hashes); block 0 is a shared system prompt
REQS = [(1024, (0, 1)), (1024, (0, 2)), (1024, (0, 1)), (600, (3, 1))]


def test_stack_distances():
    d = kv.distances(REQS)
    assert d[0] == [(None, None), (None, None)]
    assert d[1][0] == (1, 1)                           # block 0: one other block (1) used since
    assert d[2] == [(1, 1), (2, 2)]                    # 0 after {2}; 1 after {0, 2}
    assert d[3][0] == (None, None) and d[3][1] == (1, None)   # 1 is cached but its prefix (3) is new


def test_curve_counts_prefix_hits_only_up_to_the_first_miss():
    d = kv.distances(REQS)
    big, small = kv.curve(REQS, d, [100, 2])
    assert big["block_hit_pct"] == pytest.approx(100 * 4 / 8, abs=0.1)
    assert big["prefix_hit_pct"] == pytest.approx(100 * 3 / 8, abs=0.1)
    assert big["tokens_saved_pct"] == pytest.approx(100 * 3 * 512 / (3 * 1024 + 600), abs=0.1)
    assert small["block_hit_pct"] == pytest.approx(100 * 3 / 8, abs=0.1)   # the distance-2 reuse misses with 2 blocks


def test_tiers_split_hbm_and_dram_and_reload_beats_recompute_only_when_fast():
    d = kv.distances(REQS)
    t = kv.tiers(REQS, d, 2, 100)
    assert t["hbm_tokens_pct"] + t["dram_tokens_pct"] == pytest.approx(100 * 3 * 512 / (3 * 1024 + 600), abs=0.2)
    assert t["dram_tokens_pct"] > 0
    none = kv.tiers(REQS, d, 0, 0)
    for key, s in t["prefill_s"].items():
        if key.startswith("RNGD"):                     # 2,500 tok/s makes KV at 0.33 GB/s: any listed path wins
            assert s < none["prefill_s"][key]
    a100 = {k: v for k, v in t["prefill_s"].items() if k.startswith("A100")}
    assert a100["A100, host-staged 0.6 GB/s"] > a100["A100, PCIe DMA 16 GB/s"]


def test_main_reads_a_trace_dir(tmp_path, capsys):
    path = tmp_path / "mooncake" / "toolagent_trace.jsonl"
    path.parent.mkdir()
    path.write_text("\n".join(json.dumps({"timestamp": i, "input_length": p, "output_length": 10, "hash_ids": list(h)})
                              for i, (p, h) in enumerate(REQS)), encoding="utf-8")
    assert kv.main([str(tmp_path)]) == 0
    res = json.loads(capsys.readouterr().out)
    assert res["mooncake-toolagent"]["requests"] == 4 and res["mooncake-toolagent"]["distinct_blocks"] == 4
    assert kv.main([str(tmp_path / "missing")]) == 1
