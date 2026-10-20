# Workload traces and where the NPU stack stands

[Documentation](README.md) · [한국어](ko/workload-traces.md) · [End-to-end run](e2e.md)

Five public production traces describe what real LLM traffic looks like: how requests arrive, how long
prompts and answers are, and how often prompts share a prefix. This page records their characteristics
(analysed 2026-10-19 over the whole files) and what each one asks of the heterogeneous NPU stack today.

Reproduce: `rm-bench traces fetch`, then `python3 tools/trace_atlas.py ~/.cache/rm-bench/traces` in rm-bench
prints every figure below as JSON. Replay any trace with `rm-bench e2e --scenario trace-<name>`.

## Sources

| Trace | Origin | Records | License |
|---|---|---|---|
| Azure conversation, Azure code | Azure LLM inference trace 2023 (Splitwise, ISCA'24) | arrival, input/output tokens | CC-BY-4.0 |
| BurstGPT | Azure OpenAI GPT-3.5/4 usage, v2.0 without failures, file 1 | arrival (1 s), tokens, model, call type | CC-BY-4.0 |
| Mooncake conversation, tool-agent | Kimi production (FAST'25) | arrival, tokens, 512-token prefix block hashes | Apache-2.0 |

## Characteristics

| | Azure conversation | Azure code | BurstGPT | Mooncake conversation | Mooncake tool-agent |
|---|---|---|---|---|---|
| Requests / span | 19,366 / 1 h | 8,819 / 1 h | 1,404,294 / 61 days | 12,031 / 1 h | 23,608 / 1 h |
| Mean rate | 5.5 req/s | 2.6 req/s | 0.27 req/s | 3.4 req/s | 6.7 req/s |
| Inter-arrival CV (Poisson = 1) | 1.1 | 13.2 | 13.2 | 3.0* | 4.4* |
| Peak ÷ mean, 1 s / 60 s / 600 s | 2.9 / 1.5 / 1.2 | 26 / 4.1 / 1.4 | 135 / 69 / 40 | 8.2* / 1.2 / 1.1 | 7.0* / 1.2 / 1.1 |
| Input tokens p50 / p90 / p99 | 1,020 / 2,735 / 4,142 | 1,469 / 5,188 / 7,436 | 262 / 1,824 / 3,389 | 6,909 / 27,367 / 85,400 | 6,346 / 16,806 / 61,661 |
| Output tokens p50 / p90 / p99 | 129 / 424 / 601 | 13 / 55 / 251 | 36 / 276 / 1,505 | 350 / 597 / 1,119 | 30 / 507 / 898 |
| Input share of all tokens | 84.5 % | 98.7 % | 83.2 % | 97.2 % | 97.9 % |
| Prefill-heavy requests (output < input/10) | 23 % | 86 % | 57 % | 74 % | 87 % |
| Input–output rank correlation | 0.07 | −0.02 | 0.58 | 0.07 | 0.06 |
| KV per request, Llama-3.1-8B, p50 / p99 | 134 / 543 MB | 193 / 975 MB | 34 / 444 MB | 906 MB / 11.2 GB | 832 MB / 8.1 GB |
| Fit input+output ≤ 512 / 2 K / 8 K / 32 K | 32 / 85 / 100 / 100 % | 22 / 62 / 100 / 100 % | 62 / 88 / 100 / 100 % | 0 / 20 / 54 / 93 % | 0 / 9 / 78 / 97 % |
| Prefix block reuse | — | — | — | 37 % | 55 % |

\* Mooncake records arrivals in steps of about 3 s (90–95 % of requests share a timestamp), so its 1 s
burstiness and CV are artefacts; BurstGPT records whole seconds.

### What each trace is

- **Azure conversation — the balanced chat case.** Near-Poisson arrivals, kilotoken prompts, answers of a
  hundred-odd tokens. By tokens it is still prefill (84.5 %), but by time per request decode dominates: at
  the 17 ms/token we measure on RNGD, a median answer is ~2.2 s of decode, while prefill measured ~0.2 s
  for the 200–400-token prompts we could serve.
- **Azure code — prefill and bursts.** 86 % of requests are prefill-heavy and the median answer is 13 tokens.
  Arrivals clump hard: the busiest second carries 26× the mean rate. Tail latency is set by bursts.
- **BurstGPT — a daily cycle and two workloads.** 61 days with a ~12× swing between the quietest and busiest
  hour. API calls (90 % of requests) are short (output p50 26–40); conversation calls are long (229–240).
  The only trace where long prompts bring long answers (rank correlation 0.58).
- **Mooncake conversation — long context, reuse far apart.** Median prompt 6.9 K tokens, p99 85 K; 37 % of
  prefix blocks repeat, but half the repeats come ~2 minutes later. An LRU block cache needs ~1 TB of
  Llama-8B KV to hit 27 %; 4–70 GB hits about 4 %.
- **Mooncake tool-agent — long context, reuse immediate.** Same lengths, 55 % block reuse, and most repeats
  arrive at once: a 4 GB cache already hits 27 %, 17 GB 33 %.

## What each trace asks of our heterogeneous NPU stack

State as of 2026-10-19: one heterogeneous node (3 RNGD, 4 ATOM) schedulable; RNGD+ATOM PD verified with
KONI/Llama-8B at context 512, batch up to 8 (best 135–177 tok/s on 1 RNGD + 2–3 ATOM); the end-to-end run used
RNGD prefill + RNGD decode over `shm`.

| Limit | Azure conv | Azure code | BurstGPT | Mooncake conv | Mooncake tool |
|---|:-:|:-:|:-:|:-:|:-:|
| Compiled length S=512 | serves 32 % | 22 % | 62 % | 0 % | 0 % |
| Decode capacity (one decode instance, batch ≤ 8) | **binding** | — | binding at peaks | binding | — |
| Prefill capacity, no autoscaling | — | **binding** (bursts) | **binding** (daily peak) | binding | binding |
| ATOM memory (15.7 GiB/card) | B16 blocked | — | — | **long KV cannot live on ATOM** | same |
| KV transfer (shm copies the whole S buffer; P2P verified at 512) | minor | minor | minor | **binding** | **binding** |
| No prefix cache / KV tier | — | — | — | loses 37 % reuse | **loses 55 % reuse** |

### Limits in detail

1. **Sequence length.** Every compiled graph and validated path is context 512 (`seqLen` 256–512). That serves
   a third of chat traffic, a fifth of code and none of Mooncake. Covering 85 % of Azure conversation needs
   S=2048; Mooncake needs 32 K for 93 %. Graphs are compiled offline per shape, so each new S is new compile
   and validation work on both RNGD and ATOM.
2. **Decode capacity.** One decode instance serves requests one batch at a time. In the Azure replay the client's
   TPOT was 4–5× the server's: overlapping arrivals waited for decode. Batch 8 on ATOM already uses about
   15.0 of 15.7 GiB, so B16 needs memory work first. A rough sizing: Azure conversation's mean demand is
   ~1,170 output tok/s, seven to nine times one B8 PD group's 135–177 tok/s — beyond one node's 3 RNGD + 4 ATOM
   even before lengths over 512 are counted (an estimate from short-context throughput).
3. **Bursts and daily cycles.** Pools are fixed Deployments placed by hand; nothing scales them. A cold start
   takes about a minute (prefill 62 s, decode 18 s, graphs pre-compiled), so second-scale bursts (Azure code,
   26×) can only be absorbed by idle headroom, and BurstGPT's daily cycle leaves most capacity idle at night.
4. **ATOM memory and long context.** Llama-8B KV is 128 KiB per token: 0.9 GB for a median Mooncake prompt,
   11 GB at p99. ATOM has no room for that beside the weights, so long-context decode cannot sit on ATOM; RNGD
   (48 GB, ~32 GB free after weights) holds roughly 250 K tokens of KV in total, a handful of long requests.
5. **KV transfer.** The `shm` path copies the whole S-sized buffer (67 MB at S=512, ~111 ms p90). Scaled to a
   median Mooncake prompt that is over a second per request. RNGD→ATOM direct P2P is verified for exactness at
   context 512 (KONI, Qwen 0.5–3 B) and is not yet the default serving path; large transfers are unmeasured.
6. **No prefix reuse.** The PD gateway prefills every request from scratch; there is no prefix cache, no KV
   offload tier (npu-offload moves MoE experts, not KV) and no cache-aware routing in the EPP. Tool-agent
   traffic would get 27 % block hits from a 4 GB cache that RNGD's HBM could hold.
7. **Serving surface.** Non-streaming `/v1/completions` only, fixed generation length, greedy decoding; standard
   benchmark tools (GuideLLM, MLPerf LoadGen) cannot see TTFT until streaming exists.
8. **Efficiency.** Measured whole-system MFU upper bound 0.15–4.5 % and 3.9–120 GFLOPS/W on the host-staged path,
   against a 341 GFLOPS/W target; every limit above also lowers goodput per card and per watt.
9. **One node.** npu-node-2 (2 RNGD, 2 GPU) was cordoned and GPU/GB10 nodes unavailable during the analysis,
   so scale-out and RNGD+GPU mixes could not be exercised.

### Where to start, by trace

| Trace | First lever |
|---|---|
| Azure conversation | S=2048 graphs; decode batching and more decode instances (P:D 1:N) |
| Azure code | Longer prefill graphs and chunked prefill on RNGD; headroom or fast scale-up for bursts |
| BurstGPT | Autoscaling on queue depth (KEDA is installed); keep compiled artifacts warm to cut cold start |
| Mooncake conversation | Long-context graphs on RNGD, KV transfer over P2P, a host-DRAM KV tier for distant reuse |
| Mooncake tool-agent | A prefix cache in RNGD HBM and cache-aware routing in the EPP |

These are hypotheses from the traces and current measurements; the next experiments sweep them per trace with
`rm-bench` replay (goodput per card under SLO).
