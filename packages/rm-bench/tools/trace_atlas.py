"""Characterize the real traces fetched by `rm-bench traces fetch` (stdlib only). Prints one JSON document.

usage: python3 tools/trace_atlas.py [~/.cache/rm-bench/traces]

Per trace: rate and burstiness (peak/mean over 1-600 s windows, inter-arrival CV), length distributions
(percentiles, log2 histograms, CDF points), input/output rank correlation, token mix, KV size per request for
Llama-3.1-8B in bf16, share fitting each sequence length; BurstGPT hour-of-day and model/call-type mix;
Mooncake prefix reuse (block reuse, reuse distance, LRU block hit rate by cache size).
ai-rm docs/workload-traces.md is written from this output.
"""
import csv
import json
import math
import os
import sys
from collections import Counter, OrderedDict
from datetime import datetime, timezone
from pathlib import Path

KV_BYTES_PER_TOKEN = 2 * 32 * 8 * 128 * 2  # Llama-3.1-8B, bf16 K+V: 131072 B
BLOCK = 512                                # Mooncake hash block size (tokens)
ROOT = Path(os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else
                                os.environ.get("RM_BENCH_TRACES", "~/.cache/rm-bench/traces")))


def iso_s(ts):
    ts = ts.strip().replace(" ", "T")
    head, _, frac = ts.partition(".")
    if frac:
        ts = f"{head}.{''.join(c for c in frac if c.isdigit())[:6]}"
    dt = datetime.fromisoformat(ts)
    return dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp()


def read(name, path):
    rows = []  # (t, in, out, extra)
    if name.startswith("azure"):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append((iso_s(r["TIMESTAMP"]), int(r["ContextTokens"]), int(r["GeneratedTokens"]), None))
    elif name.startswith("burstgpt"):
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append((float(r["Timestamp"]), int(float(r["Request tokens"])), int(float(r["Response tokens"])),
                             (r["Model"], r["Log Type"])))
    else:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    rows.append((r["timestamp"] / 1000.0, int(r["input_length"]), int(r["output_length"]),
                                 tuple(r.get("hash_ids") or ())))
    rows.sort(key=lambda r: r[0])
    t0 = rows[0][0]
    return [(r[0] - t0,) + r[1:] for r in rows]


def pct(sorted_xs, q):
    if not sorted_xs:
        return None
    k = (len(sorted_xs) - 1) * q / 100.0
    lo = int(k)
    hi = min(lo + 1, len(sorted_xs) - 1)
    return round(sorted_xs[lo] + (sorted_xs[hi] - sorted_xs[lo]) * (k - lo), 3)


def dist(xs):
    s = sorted(xs)
    n = len(s)
    mean = sum(s) / n
    sd = math.sqrt(sum((x - mean) ** 2 for x in s) / n)
    return {"n": n, "mean": round(mean, 2), "sd": round(sd, 2), "cv": round(sd / mean, 3) if mean else None,
            "min": s[0], "max": s[-1], **{f"p{q}": pct(s, q) for q in (10, 25, 50, 75, 90, 95, 99, 99.9)}}


def log2_hist(xs, lo=0, hi=20):
    """Counts per power-of-two bin [2^k, 2^(k+1)); bin 'lo' also holds values < 2^lo."""
    c = Counter()
    for x in xs:
        k = max(lo, min(hi, int(math.log2(x)) if x >= 1 else lo))
        c[k] += 1
    return [[2 ** k, c.get(k, 0)] for k in range(lo, hi + 1)]


def cdf_points(xs, points=60):
    s = sorted(xs)
    n = len(s)
    return [[s[min(n - 1, int(i * (n - 1) / (points - 1)))], round(i / (points - 1), 4)] for i in range(points)]


def spearman(a, b):
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2.0
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return round(cov / (va * vb), 3) if va and vb else None


def rate_series(ts, bin_s):
    n = int(ts[-1] // bin_s) + 1
    c = [0] * n
    for t in ts:
        c[int(t // bin_s)] += 1
    return c


def burst(ts):
    out = {}
    span = max(ts[-1], 1e-9)
    mean = len(ts) / span
    for w in (1, 10, 60, 600):
        if span >= 3 * w:
            s = rate_series(ts, w)
            out[f"peak_to_mean_{w}s"] = round(max(s) / w / mean, 2)
    iat = [b - a for a, b in zip(ts, ts[1:]) if b >= a]
    d = dist(iat)
    out["iat"] = {k: d[k] for k in ("mean", "cv", "p50", "p90", "p99", "max")}
    out["iat_zero_pct"] = round(100.0 * sum(1 for x in iat if x == 0) / len(iat), 2)
    return out


def lru_curve(reqs, capacities):
    """Block hit rate of an LRU prefix cache holding `cap` blocks (each block = 512 tokens of KV)."""
    out = []
    for cap in capacities:
        cache = OrderedDict()
        hits = total = 0
        req_full_hit_prefix = 0
        for r in reqs:
            prefix_alive = True
            for h in r[3]:
                total += 1
                if h in cache:
                    cache.move_to_end(h)
                    hits += 1
                    if prefix_alive:
                        req_full_hit_prefix += 1
                else:
                    prefix_alive = False
                    cache[h] = None
                    if len(cache) > cap:
                        cache.popitem(last=False)
        out.append({"blocks": cap, "gb": round(cap * BLOCK * KV_BYTES_PER_TOKEN / 1e9, 1),
                    "block_hit_pct": round(100.0 * hits / total, 1),
                    "prefix_hit_pct": round(100.0 * req_full_hit_prefix / total, 1)})
    return out


def analyze(name, path):
    rows = read(name, path)
    ts = [r[0] for r in rows]
    ins = [r[1] for r in rows]
    outs = [r[2] for r in rows]
    span = ts[-1]
    res = {
        "name": name, "requests": len(rows), "span_s": round(span, 1),
        "mean_rps": round(len(rows) / span, 3),
        "input": dist(ins), "output": dist(outs),
        "input_hist": log2_hist(ins), "output_hist": log2_hist(outs),
        "input_cdf": cdf_points(ins), "output_cdf": cdf_points(outs),
        "spearman_in_out": spearman(ins[:50000], outs[:50000]),
        "token_share_input_pct": round(100.0 * sum(ins) / (sum(ins) + sum(outs)), 1),
        "kv_mb_per_request": {k: round(v * KV_BYTES_PER_TOKEN / 1e6, 1) for k, v in dist(ins).items()
                              if k in ("p50", "p90", "p99", "max")},
        "fits_total": {str(s): round(100.0 * sum(1 for i, o in zip(ins, outs) if i + o <= s) / len(rows), 1)
                       for s in (512, 1024, 2048, 4096, 8192, 16384, 32768, 131072)},
        "burst": burst(ts),
    }
    # output/input ratio buckets: decode-heavy vs prefill-heavy requests
    ratio = [o / max(1, i) for i, o in zip(ins, outs)]
    res["out_in_ratio"] = {k: dist(ratio)[k] for k in ("p10", "p50", "p90")}
    res["prefill_heavy_pct"] = round(100.0 * sum(1 for x in ratio if x < 0.1) / len(ratio), 1)
    res["decode_heavy_pct"] = round(100.0 * sum(1 for x in ratio if x > 1.0) / len(ratio), 1)
    # rate over time
    if span <= 2 * 3600:
        res["rate_series"] = {"bin_s": 10, "rps": [round(c / 10, 2) for c in rate_series(ts, 10)]}
    else:
        hourly = rate_series(ts, 3600)
        res["rate_series"] = {"bin_s": 3600, "rps": [round(c / 3600, 3) for c in hourly]}
        hod = [0.0] * 24
        days = [0] * 24
        for h, c in enumerate(hourly):
            hod[h % 24] += c
            days[h % 24] += 1
        res["hour_of_day_rps"] = [round(hod[h] / max(1, days[h]) / 3600, 3) for h in range(24)]
        daily = rate_series(ts, 86400)
        res["daily_requests"] = daily
    if name.startswith("burstgpt"):
        res["models"] = dict(Counter(r[3][0] for r in rows).most_common())
        res["log_types"] = dict(Counter(r[3][1] for r in rows).most_common())
        by = {}
        for r in rows:
            by.setdefault(r[3], []).append(r)
        res["by_model_logtype"] = {f"{m} / {lt}": {"requests": len(v), "input_p50": pct(sorted(x[1] for x in v), 50),
                                                  "output_p50": pct(sorted(x[2] for x in v), 50)}
                                   for (m, lt), v in sorted(by.items(), key=lambda kv: -len(kv[1]))}
    if name.startswith("mooncake"):
        seen = {}
        reuse_req = []
        distance = []
        for i, r in enumerate(rows):
            hit = 0
            for h in r[3]:
                if h in seen:
                    hit += 1
                    distance.append(r[0] - seen[h])
                seen[h] = r[0]
            reuse_req.append(hit / max(1, len(r[3])))
        blocks_total = sum(len(r[3]) for r in rows)
        res["prefix"] = {
            "blocks_total": blocks_total, "blocks_unique": len(seen),
            "block_reuse_pct": round(100.0 * (blocks_total - len(seen)) / blocks_total, 1),
            "working_set_gb": round(len(seen) * BLOCK * KV_BYTES_PER_TOKEN / 1e9, 1),
            "req_reuse_frac": {k: dist(reuse_req)[k] for k in ("p25", "p50", "p75", "p90")},
            "req_any_reuse_pct": round(100.0 * sum(1 for x in reuse_req if x > 0) / len(reuse_req), 1),
            "reuse_distance_s": {k: dist(distance)[k] for k in ("p50", "p90", "p99")} if distance else None,
            "top_shared_blocks": [c for _, c in Counter(h for r in rows for h in r[3]).most_common(5)],
        }
        caps = [64, 256, 1024, 4096, 16384, 65536]
        res["lru"] = lru_curve(rows, caps)
    return res


FILES = {
    "azure-conv": "azure-2023/AzureLLMInferenceTrace_conv.csv",
    "azure-code": "azure-2023/AzureLLMInferenceTrace_code.csv",
    "burstgpt": "burstgpt/BurstGPT_without_fails_1.csv",
    "mooncake-conversation": "mooncake/conversation_trace.jsonl",
    "mooncake-toolagent": "mooncake/toolagent_trace.jsonl",
}
print(json.dumps({n: analyze(n, ROOT / p) for n, p in FILES.items()}, separators=(",", ":")))
