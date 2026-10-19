"""Real request traces: catalog and download, readers, filters and statistics.

Formats (selected by `format`, else by file name):

    azure     Azure LLM inference trace CSV   TIMESTAMP, ContextTokens, GeneratedTokens
    burstgpt  BurstGPT CSV                    Timestamp (s), Model, Request tokens, Response tokens, ..., Log Type
    mooncake  Mooncake (Kimi) JSONL           {"timestamp": ms, "input_length", "output_length", "hash_ids"}

A scenario selects a window and the requests the target can serve:

    requests:
      source: trace
      count: 500                     # optional cap
      trace:
        path: ${RM_BENCH_TRACES}/azure-2023/AzureLLMInferenceTrace_conv.csv   (`csv` is an alias)
        format: azure                # optional, inferred from the file
        start_s: 0                   # skip this much trace time first
        speedup: 1                   # >1 compresses time, <1 stretches it; burst shape is kept
        max_prompt_tokens: 448       # limits the target can serve (e.g. a graph compiled for S=512)
        max_output_tokens: 64
        max_total_tokens: 512
        policy: skip                 # skip | clip requests over a limit
        models: [ChatGPT]            # burstgpt only
        log_types: [Conversation log]  # burstgpt only
        block_tokens: 512            # mooncake hash block size

A Mooncake request carries its `hash_ids`; prompts built from them share text exactly where the
original requests shared a prefix, so prefix caching sees the trace's real reuse.

The data is never stored in this repository. `rm-bench traces fetch` downloads it into
$RM_BENCH_TRACES (default ~/.cache/rm-bench/traces) with a manifest and the attribution its license
asks for.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

FORMATS = ("azure", "burstgpt", "mooncake")
POLICIES = ("skip", "clip")

# name -> (relative path, url, source, license, citation)
CATALOG = {
    "azure-2023-conv": (
        "azure-2023/AzureLLMInferenceTrace_conv.csv",
        "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/AzureLLMInferenceTrace_conv.csv",
        "https://github.com/Azure/AzurePublicDataset", "CC-BY-4.0",
        "Patel et al., Splitwise: Efficient generative LLM inference using phase splitting, ISCA 2024"),
    "azure-2023-code": (
        "azure-2023/AzureLLMInferenceTrace_code.csv",
        "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/AzureLLMInferenceTrace_code.csv",
        "https://github.com/Azure/AzurePublicDataset", "CC-BY-4.0",
        "Patel et al., Splitwise: Efficient generative LLM inference using phase splitting, ISCA 2024"),
    "burstgpt-1": (
        "burstgpt/BurstGPT_without_fails_1.csv",
        "https://github.com/HPMLL/BurstGPT/releases/download/v2.0/BurstGPT_without_fails_1.csv",
        "https://github.com/HPMLL/BurstGPT", "CC-BY-4.0",
        "Wang et al., BurstGPT: A Real-world Workload Dataset to Optimize LLM Serving Systems"),
    "mooncake-conversation": (
        "mooncake/conversation_trace.jsonl",
        "https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/FAST25-release/traces/conversation_trace.jsonl",
        "https://github.com/kvcache-ai/Mooncake", "Apache-2.0",
        "Qin et al., Mooncake: A KVCache-centric Disaggregated Architecture for LLM Serving, FAST 2025"),
    "mooncake-toolagent": (
        "mooncake/toolagent_trace.jsonl",
        "https://raw.githubusercontent.com/kvcache-ai/Mooncake/main/FAST25-release/traces/toolagent_trace.jsonl",
        "https://github.com/kvcache-ai/Mooncake", "Apache-2.0",
        "Qin et al., Mooncake: A KVCache-centric Disaggregated Architecture for LLM Serving, FAST 2025"),
}


def traces_dir() -> Path:
    return Path(os.path.expanduser(os.environ.get("RM_BENCH_TRACES") or "~/.cache/rm-bench/traces"))


def resolve(path: str) -> Path:
    """Expand ~ and $VARS; $RM_BENCH_TRACES means traces_dir() when it is unset."""
    if "RM_BENCH_TRACES" not in os.environ:
        path = path.replace("${RM_BENCH_TRACES}", str(traces_dir())).replace("$RM_BENCH_TRACES", str(traces_dir()))
    return Path(os.path.expanduser(os.path.expandvars(path)))


def fetch(names: list[str] | None = None, dest: Path | None = None, *, get=None) -> list[Path]:
    """Download catalog traces into `dest`, skipping files that already match the manifest.

    Writes MANIFEST.json (url, sha256, bytes, license) and ATTRIBUTION.md next to the data.
    """
    import requests

    get = get or (lambda url: requests.get(url, stream=True, timeout=120))
    dest = dest or traces_dir()
    names = names or list(CATALOG)
    unknown = [n for n in names if n not in CATALOG]
    if unknown:
        raise ValueError(f"unknown traces {unknown}; known: {sorted(CATALOG)}")
    manifest_path = dest / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    out = []
    for name in names:
        rel, url, source, lic, cite = CATALOG[name]
        target = dest / rel
        known = manifest.get(name)
        if known and target.is_file() and _sha256(target) == known["sha256"]:
            out.append(target)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".part")
        h, size = hashlib.sha256(), 0
        with get(url) as resp:
            resp.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in resp.iter_content(1 << 20):
                    f.write(chunk)
                    h.update(chunk)
                    size += len(chunk)
        tmp.replace(target)
        manifest[name] = {"path": rel, "url": url, "sha256": h.hexdigest(), "bytes": size,
                          "source": source, "license": lic,
                          "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
        out.append(target)
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = ["# Trace attribution", "",
             "Downloaded by `rm-bench traces fetch`. Not redistributed by rm-bench.", ""]
    for name, m in sorted(manifest.items()):
        cite = CATALOG.get(name, ("", "", "", "", ""))[4]
        lines.append(f"- `{m['path']}` — {m['source']} ({m['license']}). {cite}")
    (dest / "ATTRIBUTION.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- readers: yield (absolute time s, prompt tokens, output tokens, hash ids or None) -----------


def _parse_iso_s(ts: str) -> float:
    ts = ts.strip().replace(" ", "T")
    head, dot, frac = ts.partition(".")
    if dot:  # Python < 3.11 accepts at most 6 fractional digits
        digits = "".join(c for c in frac if c.isdigit())
        ts = f"{head}.{digits[:6]}{frac[len(digits):]}"
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _read_azure(path: Path, spec: dict):
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            yield _parse_iso_s(row["TIMESTAMP"]), int(row["ContextTokens"]), int(row["GeneratedTokens"]), None


def _read_burstgpt(path: Path, spec: dict):
    models = set(spec.get("models") or [])
    log_types = set(spec.get("log_types") or [])
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if models and row.get("Model") not in models:
                continue
            if log_types and row.get("Log Type") not in log_types:
                continue
            out = int(float(row["Response tokens"]))
            if out <= 0:  # failed request in the full release
                continue
            yield float(row["Timestamp"]), int(float(row["Request tokens"])), out, None


def _read_mooncake(path: Path, spec: dict):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            yield r["timestamp"] / 1000.0, int(r["input_length"]), int(r["output_length"]), tuple(r.get("hash_ids") or ())


READERS = {"azure": _read_azure, "burstgpt": _read_burstgpt, "mooncake": _read_mooncake}


def infer_format(path: Path) -> str:
    if path.suffix == ".jsonl":
        return "mooncake"
    with open(path, newline="", encoding="utf-8") as f:
        header = f.readline()
    if "ContextTokens" in header:
        return "azure"
    if "Request tokens" in header:
        return "burstgpt"
    raise ValueError(f"{path}: cannot tell the trace format; set trace.format to one of {FORMATS}")


@dataclass
class Window:
    """Requests selected from a trace, with what was dropped or clipped on the way."""
    requests: list = field(default_factory=list)  # (offset_s, prompt, output[, hash_ids])
    seen: int = 0
    skipped: int = 0
    clipped: int = 0
    trace_span_s: float = 0.0


def load(spec: dict, *, count: int | None = None, duration_s: float | None = None) -> Window:
    """Read a trace window as a schedule: offsets from the first selected request, scaled by speedup.

    Reading stops at `count` selected requests or at the first one past `duration_s` (schedule time).
    """
    raw_path = spec.get("path") or spec.get("csv")
    if not raw_path:
        raise ValueError("requests.trace.path is required for source: trace")
    path = resolve(str(raw_path))
    if not path.is_file():
        raise FileNotFoundError(f"trace {path} not found; run `rm-bench traces fetch` or set RM_BENCH_TRACES")
    fmt = spec.get("format") or infer_format(path)
    if fmt not in FORMATS:
        raise ValueError(f"trace.format must be one of {FORMATS}")
    policy = spec.get("policy", "skip")
    if policy not in POLICIES:
        raise ValueError(f"trace.policy must be one of {POLICIES}")
    speedup = float(spec.get("speedup", 1.0))
    if speedup <= 0:
        raise ValueError("trace.speedup must be > 0")
    start_s = float(spec.get("start_s", 0.0))
    max_p = spec.get("max_prompt_tokens")
    max_o = spec.get("max_output_tokens")
    max_t = spec.get("max_total_tokens")
    block = int(spec.get("block_tokens", 512))

    w = Window()
    t_first = t_sel = None
    last = None
    for ts, p, o, blocks in READERS[fmt](path, spec):
        t_first = ts if t_first is None else t_first
        if ts - t_first < start_s:
            continue
        w.seen += 1
        over = ((max_p is not None and p > max_p) or (max_o is not None and o > max_o)
                or (max_t is not None and p + o > max_t))
        if over and policy == "skip":
            w.skipped += 1
            continue
        if over:
            w.clipped += 1
            if max_o is not None:
                o = min(o, int(max_o))
            if max_p is not None:
                p = min(p, int(max_p))
            if max_t is not None and p + o > max_t:
                p = max(1, int(max_t) - o)
            if blocks:
                blocks = blocks[: max(1, -(-p // block))]
        t_sel = ts if t_sel is None else t_sel
        offset = (ts - t_sel) / speedup
        if duration_s is not None and offset >= duration_s:
            break
        w.requests.append((offset, max(1, p), max(1, o)) + ((blocks,) if blocks else ()))
        last = ts
        if count and len(w.requests) >= int(count):
            break
    if w.requests:
        w.trace_span_s = last - t_sel
    return w


# --- prompts -------------------------------------------------------------------------------------

# Common English words that Llama-family tokenizers encode as one token each (with a leading space).
_VOCAB = ("the of and to in is was for on with as at by from this that are be it an or have not "
          "but they his her one all were there their we can has more time been some would which "
          "when what new other only into after first two any these also may most then over state "
          "years those used work such people under world many even day way back should").split()


def block_text(hash_id: int, n: int) -> str:
    """`n` words that depend only on `hash_id`: equal ids give equal text."""
    return " ".join(_VOCAB[(hash_id * 2654435761 + i * 40503) % len(_VOCAB)] for i in range(n))


def prompt_for(prompt_tokens: int, *, blocks=None, block_tokens: int = 512, salt: int | None = None) -> str:
    """Prompt text of about `prompt_tokens` tokens.

    blocks: Mooncake hash ids; requests that share leading ids share leading text.
    salt:   a per-request value so trace prompts do not share a prefix by accident.
    Neither: the legacy "word word ..." prompt of synthetic scenarios.
    """
    n = max(1, int(prompt_tokens))
    if blocks:
        words = []
        for hid in blocks:
            words.extend(block_text(int(hid), block_tokens).split())
            if len(words) >= n:
                break
        return " ".join(words[:n])
    if salt is not None:
        return block_text(-1 - int(salt), n)
    return " ".join(["word"] * n)


# --- statistics ----------------------------------------------------------------------------------


def _pct(xs, q):
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def stats(window: Window, *, limits: dict | None = None) -> dict:
    """Shape of a selected window: rate and burstiness (schedule time), lengths, prefix reuse,
    and how much of it fits optional `limits` (max_prompt_tokens / max_output_tokens / max_total_tokens)."""
    reqs = window.requests
    out = {"requests": len(reqs), "seen": window.seen, "skipped": window.skipped, "clipped": window.clipped,
           "trace_span_s": round(window.trace_span_s, 1)}
    if not reqs:
        return out
    offs = [r[0] for r in reqs]
    span = max(offs[-1], 1e-9)
    p = [r[1] for r in reqs]
    o = [r[2] for r in reqs]
    per_min: dict[int, int] = {}
    for t in offs:
        per_min[int(t // 60)] = per_min.get(int(t // 60), 0) + 1
    out.update({
        "schedule_span_s": round(offs[-1], 1),
        "mean_rps": round(len(reqs) / span, 3) if offs[-1] > 0 else None,
        "peak_rps_60s": round(max(per_min.values()) / 60.0, 3),
        "prompt_tokens": {k: _pct(p, q) for k, q in (("p50", 50), ("p90", 90), ("p99", 99))},
        "output_tokens": {k: _pct(o, q) for k, q in (("p50", 50), ("p90", 90), ("p99", 99))},
    })
    blocks_seen: set = set()
    shared = total = 0
    for r in reqs:
        if len(r) > 3:
            for hid in r[3]:
                total += 1
                if hid in blocks_seen:
                    shared += 1
                blocks_seen.add(hid)
    if total:
        out["prefix_block_reuse_pct"] = round(100.0 * shared / total, 1)
    if limits:
        mp, mo, mt = (limits.get(k) for k in ("max_prompt_tokens", "max_output_tokens", "max_total_tokens"))
        fit = sum(1 for r in reqs if (mp is None or r[1] <= mp) and (mo is None or r[2] <= mo)
                  and (mt is None or r[1] + r[2] <= mt))
        out["fits_limits_pct"] = round(100.0 * fit / len(reqs), 1)
    return out
