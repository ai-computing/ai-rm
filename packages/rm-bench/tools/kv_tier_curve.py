"""What a host-DRAM KV tier would buy on the Mooncake traces (stdlib only). Prints one JSON document.

usage: python3 tools/kv_tier_curve.py [~/.cache/rm-bench/traces] [--format md]

Mooncake requests carry `hash_ids`, one per 512-token prefix block (a block's hash covers everything before
it, so equal ids mean equal prefixes). Every block access goes to the front of one LRU stack whatever the
cache size, so a single pass computes each access's stack distance (distinct blocks touched since its last
use) and with it the hit rate of every cache size at once:

    block hit    the block is cached (distance < capacity), whether or not the blocks before it were
    prefix hit   it and every block before it in the request are cached: what an engine can actually reuse,
                 since prefill restarts at the first missing block
    tokens saved prompt tokens covered by prefix hits / all prompt tokens (the last block may be partial)

Two tiers (HBM of `hbm` blocks in front of DRAM, exclusive, one LRU order) split prefix hits into those
served from HBM (distance < hbm) and those reloaded from DRAM. The prefill-time model is per request:
overhead + missed tokens / prefill rate + DRAM-reloaded bytes / reload bandwidth, with the rates of
rm-controller's profiles.yaml (RNGD measured/derived, A100 estimated).

Assumes one cache in front of all prefill work: one instance, a shared store (Mooncake Store, LMCache
server), or routing that always finds the holder. Per-instance caches behind a cache-blind router hit less.
Timestamps are ignored (the order is the file's), so the curve is the same at any replay speed.
"""
import json
import os
import sys
from pathlib import Path

KV_BYTES_PER_TOKEN = 2 * 32 * 8 * 128 * 2   # Llama-3.1-8B, bf16 K+V: 131072 B
BLOCK = 512                                 # Mooncake hash block size (tokens)
BLOCK_BYTES = BLOCK * KV_BYTES_PER_TOKEN    # 64 MiB
GIB = 1 << 30
TRACES = {"mooncake-conversation": "mooncake/conversation_trace.jsonl",
          "mooncake-toolagent": "mooncake/toolagent_trace.jsonl"}
CACHE_GIB = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024)
HBM_GIB = (0, 4, 16)                         # cache room in device memory: none (ATOM), RNGD-like, A100-like
DRAM_GIB = (0, 64, 256)
# (name, prefill tok/s, overhead ms) from rm-controller profiles.yaml; (name, GB/s) reload paths
ENGINES = (("RNGD", 2500.0, 60.0), ("A100", 10000.0, 20.0))
RELOAD = (("host-staged 0.6 GB/s", 0.6), ("PCIe DMA 16 GB/s", 16.0))


def read(path):
    reqs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                reqs.append((int(r["input_length"]), tuple(r.get("hash_ids") or ())))
    return reqs


class _Fenwick:
    def __init__(self, n):
        self.n, self.t = n, [0] * (n + 1)

    def add(self, i, v):
        i += 1
        while i <= self.n:
            self.t[i] += v
            i += i & -i

    def prefix(self, i):            # sum over [0, i)
        s = 0
        while i > 0:
            s += self.t[i]
            i -= i & -i
        return s


def distances(reqs):
    """Per request, per block: (stack distance, running max over the request's prefix). None = first use."""
    n = sum(len(h) for _, h in reqs)
    bit, last, t, out = _Fenwick(n), {}, 0, []
    for _, hashes in reqs:
        row, run = [], -1
        for h in hashes:
            p = last.get(h)
            if p is None:
                d = None
            else:
                d = bit.prefix(t) - bit.prefix(p + 1)      # distinct blocks used since p
                bit.add(p, -1)
            bit.add(t, 1)
            last[h] = t
            t += 1
            run = None if d is None or run is None else max(run, d)
            row.append((d, run))
        out.append(row)
    return out


def _tokens(prompt, k):
    return max(0, min(BLOCK, prompt - k * BLOCK))


def curve(reqs, dists, cache_blocks):
    blocks = sum(len(r) for r in dists)
    tokens = sum(p for p, _ in reqs) or 1
    out = []
    for cap in cache_blocks:
        bh = ph = saved = 0
        for (prompt, _), row in zip(reqs, dists):
            for k, (d, run) in enumerate(row):
                if d is not None and d < cap:
                    bh += 1
                if run is not None and run < cap:
                    ph += 1
                    saved += _tokens(prompt, k)
        out.append({"cache_gib": round(cap * BLOCK_BYTES / GIB, 1), "block_hit_pct": round(100.0 * bh / blocks, 1),
                    "prefix_hit_pct": round(100.0 * ph / blocks, 1), "tokens_saved_pct": round(100.0 * saved / tokens, 1)})
    return out


def tiers(reqs, dists, hbm_blocks, dram_blocks):
    """Mean prefill seconds per request and hit split for an HBM + DRAM tier pair, per engine and reload path."""
    cap = hbm_blocks + dram_blocks
    hbm_tok = dram_tok = 0
    per_req = []                                   # (missed tokens, DRAM-reloaded tokens)
    for (prompt, _), row in zip(reqs, dists):
        miss, from_dram = prompt, 0
        for k, (d, run) in enumerate(row):
            if run is not None and run < cap:
                n = _tokens(prompt, k)
                miss -= n
                if d < hbm_blocks:
                    hbm_tok += n
                else:
                    dram_tok += n
                    from_dram += n
        per_req.append((max(0, miss), from_dram))
    tokens = sum(p for p, _ in reqs) or 1
    res = {"hbm_gib": round(hbm_blocks * BLOCK_BYTES / GIB), "dram_gib": round(dram_blocks * BLOCK_BYTES / GIB),
           "hbm_tokens_pct": round(100.0 * hbm_tok / tokens, 1), "dram_tokens_pct": round(100.0 * dram_tok / tokens, 1),
           "prefill_s": {}}
    for name, rate, overhead in ENGINES:
        for path, gbs in RELOAD:
            s = sum(overhead / 1000.0 + m / rate + r * KV_BYTES_PER_TOKEN / (gbs * 1e9) for m, r in per_req)
            res["prefill_s"][f"{name}, {path}"] = round(s / len(per_req), 3)
    return res


def analyze(path):
    reqs = read(path)
    dists = distances(reqs)
    blocks = lambda gib: int(gib * GIB // BLOCK_BYTES)   # noqa: E731
    pairs = [(h, d) for h in HBM_GIB for d in DRAM_GIB]
    return {"requests": len(reqs), "blocks": sum(len(r) for r in dists),
            "distinct_blocks": len({h for _, hs in reqs for h in hs}),
            "curve": curve(reqs, dists, [blocks(g) for g in CACHE_GIB]),
            "tiers": [tiers(reqs, dists, blocks(h), blocks(d)) for h, d in pairs]}


def markdown(res):
    lines = []
    for name, r in res.items():
        lines += [f"**{name}** ({r['requests']} requests, {r['blocks']} block accesses, {r['distinct_blocks']} distinct)",
                  "", "| Cache GiB | Block hit % | Prefix hit % | Prompt tokens saved % |", "|--:|--:|--:|--:|"]
        lines += [f"| {c['cache_gib']:g} | {c['block_hit_pct']} | {c['prefix_hit_pct']} | {c['tokens_saved_pct']} |"
                  for c in r["curve"]]
        keys = list(r["tiers"][0]["prefill_s"])
        lines += ["", "| HBM GiB | DRAM GiB | Tokens from HBM % | from DRAM % | " + " | ".join(f"{k} s" for k in keys) + " |",
                  "|--:|--:|--:|--:|" + "--:|" * len(keys)]
        lines += [f"| {t['hbm_gib']} | {t['dram_gib']} | {t['hbm_tokens_pct']} | {t['dram_tokens_pct']} | "
                  + " | ".join(f"{t['prefill_s'][k]:.3f}" for k in keys) + " |" for t in r["tiers"]]
        lines.append("")
    return "\n".join(lines)


def main(argv):
    fmt = "md" if "--format" in argv and argv[argv.index("--format") + 1] == "md" else "json"
    args = [a for i, a in enumerate(argv) if not a.startswith("--") and (i == 0 or argv[i - 1] != "--format")]
    root = Path(os.path.expanduser(args[0] if args else os.environ.get("RM_BENCH_TRACES", "~/.cache/rm-bench/traces")))
    res = {name: analyze(root / rel) for name, rel in TRACES.items() if (root / rel).is_file()}
    if not res:
        print(f"no Mooncake traces under {root}; run `rm-bench traces fetch`", file=sys.stderr)
        return 1
    print(markdown(res) if fmt == "md" else json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
