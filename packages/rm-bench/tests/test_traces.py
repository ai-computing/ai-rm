"""Real trace readers, filters, prompts, statistics and fetch (no network)."""
from __future__ import annotations

import io
import json

import pytest

from rm_bench import cli, traces
from rm_bench.scenario import Scenario

AZURE = """TIMESTAMP,ContextTokens,GeneratedTokens
2023-11-16 18:15:46.6805900,374,44
2023-11-16 18:15:50.9951690,396,109
2023-11-16 18:15:51.2224670,879,55
2023-11-16 18:16:52.0000000,120,20
"""
BURSTGPT = """Timestamp,Model,Request tokens,Response tokens,Total tokens,Log Type
5,ChatGPT,472,18,490,Conversation log
45,ChatGPT,1087,230,1317,Conversation log
118,GPT-4,417,276,693,Conversation log
120,ChatGPT,300,0,300,API log
"""
MOONCAKE = "\n".join(json.dumps(r) for r in [
    {"timestamp": 0, "input_length": 1000, "output_length": 50, "hash_ids": [0, 1]},
    {"timestamp": 500, "input_length": 1500, "output_length": 60, "hash_ids": [0, 1, 2]},
    {"timestamp": 2000, "input_length": 600, "output_length": 40, "hash_ids": [3, 4]},
]) + "\n"


@pytest.fixture
def files(tmp_path):
    out = {}
    for name, body, ext in (("azure", AZURE, "csv"), ("burstgpt", BURSTGPT, "csv"), ("mooncake", MOONCAKE, "jsonl")):
        p = tmp_path / f"{name}.{ext}"
        p.write_text(body)
        out[name] = p
    return out


def test_formats_are_inferred(files):
    for fmt, path in files.items():
        assert traces.infer_format(path) == fmt


def test_azure_offsets_keep_real_gaps_and_scale(files):
    w = traces.load({"path": str(files["azure"]), "speedup": 2})
    offs = [r[0] for r in w.requests]
    assert offs[0] == 0.0
    assert offs[1] == pytest.approx((50.9951690 - 46.6805900) / 2, abs=1e-6)
    assert [r[1:] for r in w.requests][:2] == [(374, 44), (396, 109)]


def test_burstgpt_drops_failures_and_filters_models(files):
    w = traces.load({"path": str(files["burstgpt"])})
    assert [(r[1], r[2]) for r in w.requests] == [(472, 18), (1087, 230), (417, 276)]
    w = traces.load({"path": str(files["burstgpt"]), "models": ["GPT-4"]})
    assert [r[0] for r in w.requests] == [0.0] and w.requests[0][1] == 417


def test_limits_skip_or_clip(files):
    spec = {"path": str(files["azure"]), "max_total_tokens": 500}
    w = traces.load(spec)
    assert [(r[1], r[2]) for r in w.requests] == [(374, 44), (120, 20)] and w.skipped == 2
    w = traces.load({**spec, "policy": "clip", "max_output_tokens": 64})
    assert len(w.requests) == 4 and w.clipped == 2
    assert all(r[1] + r[2] <= 500 and r[2] <= 64 for r in w.requests)


def test_start_count_and_duration(files):
    w = traces.load({"path": str(files["azure"]), "start_s": 4.0})
    assert w.requests[0][1] == 396 and w.requests[0][0] == 0.0
    assert len(traces.load({"path": str(files["azure"])}, count=2).requests) == 2
    assert len(traces.load({"path": str(files["azure"])}, duration_s=10).requests) == 3


def test_mooncake_prefixes_are_shared_where_the_trace_shared_them(files):
    w = traces.load({"path": str(files["mooncake"])})
    a, b, c = w.requests
    assert a[3] == (0, 1) and b[3] == (0, 1, 2)
    pa = traces.prompt_for(a[1], blocks=a[3], block_tokens=512)
    pb = traces.prompt_for(b[1], blocks=b[3], block_tokens=512)
    pc = traces.prompt_for(c[1], blocks=c[3], block_tokens=512)
    assert len(pa.split()) == 1000 and len(pb.split()) == 1500
    assert pb.split()[:1000] == pa.split()          # same two leading blocks
    assert pc.split()[:10] != pa.split()[:10]       # different first block
    s = traces.stats(w)
    assert s["prefix_block_reuse_pct"] == pytest.approx(100 * 2 / 7, abs=0.1)


def test_salted_prompts_do_not_share_a_prefix():
    a = traces.prompt_for(50, salt=0)
    b = traces.prompt_for(50, salt=1)
    assert len(a.split()) == 50 and a != b and a.split()[:5] != b.split()[:5]
    assert traces.prompt_for(3) == "word word word"


def test_stats_reports_rate_lengths_and_fit(files):
    s = traces.stats(traces.load({"path": str(files["azure"])}), limits={"max_total_tokens": 500})
    assert s["requests"] == 4 and s["fits_limits_pct"] == 50.0
    assert s["prompt_tokens"]["p50"] == pytest.approx(385.0)
    assert s["peak_rps_60s"] == pytest.approx(3 / 60, abs=1e-3)


def test_scenario_trace_source_and_env_path(files, monkeypatch):
    monkeypatch.setenv("RM_BENCH_TRACES", str(files["azure"].parent))
    sc = Scenario(name="t", duration_s=120,
                  requests={"source": "trace", "trace": {"path": "${RM_BENCH_TRACES}/azure.csv"}}).validate()
    assert len(sc.schedule()) == 4
    sc.duration_s = 60   # the 4th request arrives 65 s in
    assert len(sc.schedule()) == 3


def test_missing_trace_points_to_fetch(tmp_path):
    with pytest.raises(FileNotFoundError, match="traces fetch"):
        traces.load({"path": str(tmp_path / "nope.csv")})


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        return iter(lambda: self.read(n), b"")


def test_fetch_writes_manifest_attribution_and_skips_unchanged(tmp_path):
    calls = []

    def get(url):
        calls.append(url)
        return _Resp(AZURE.encode())

    paths = traces.fetch(["azure-2023-conv"], tmp_path, get=get)
    assert paths[0].read_text(encoding="utf-8") == AZURE
    m = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))["azure-2023-conv"]
    assert m["license"] == "CC-BY-4.0" and m["bytes"] == len(AZURE)
    assert "Splitwise" in (tmp_path / "ATTRIBUTION.md").read_text(encoding="utf-8")
    traces.fetch(["azure-2023-conv"], tmp_path, get=get)
    assert len(calls) == 1
    with pytest.raises(ValueError, match="unknown traces"):
        traces.fetch(["nope"], tmp_path, get=get)


def test_cli_stats(files, capsys):
    assert cli.main(["traces", "stats", str(files["azure"]), "--max-total-tokens", "500", "--no-filter"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["requests"] == 4 and out["fits_limits_pct"] == 50.0
    assert cli.main(["traces", "stats", str(files["azure"]), "--max-total-tokens", "500"]) == 0
    assert json.loads(capsys.readouterr().out)["requests"] == 2
