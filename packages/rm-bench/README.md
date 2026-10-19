<div align="center">

<h1>rm-bench</h1>

<h3>End-to-end load, real-trace replay and SLO measurement for llm-d endpoints</h3>

<p>
  <strong>English</strong> · <a href="README.ko.md">한국어</a>
</p>

<p>
  <a href="https://github.com/ai-computing/ai-rm"><img src="https://img.shields.io/badge/ai--rm-L5%20observe%20%26%20operate-f472b6" alt="ai-rm layer L5"></a>
  <a href="https://github.com/ai-computing/rm-core/blob/v0.1.1/PROTOCOL.md"><img src="https://img.shields.io/badge/protocol-v0.1-7c5cff" alt="Protocol v0.1"></a>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml/badge.svg" alt="packages CI"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&amp;logoColor=white" alt="Python 3.9+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-64748b" alt="License: BSD-3-Clause"></a>
</p>

<p>
  <a href="#-quick-start"><b>Quick start</b></a> ·
  <a href="#-end-to-end-scenarios"><b>Scenarios</b></a> ·
  <a href="#-real-traces"><b>Real traces</b></a> ·
  <a href="#-ai-rm-integration"><b>ai-rm integration</b></a> ·
  <a href="#-results-format"><b>Results</b></a>
</p>

</div>

---

**rm-bench** is the measurement tool of [ai-rm](https://github.com/ai-computing/ai-rm) (L5). It sends load to an
OpenAI-compatible endpoint such as the llm-d gateway, judges the run against an SLO and reports TTFT, TPOT, E2E and
throughput under rm-core metric names. It lives in ai-rm as `packages/rm-bench` (moved from its own repository, now
archived, on 2026-10-19).

<table>
<tr>
<td width="33%" valign="top">
<b>🎯 SLO-judged scenarios</b><br>
Open-loop arrivals, latency measured from each request's scheduled time, per-request SLO attainment and an exit code
CI can use (0 PASS, 1 SLO miss, 2 setup error).
</td>
<td width="33%" valign="top">
<b>📈 Real production traces</b><br>
Replays Azure 2023, BurstGPT and Mooncake traces with their real arrival gaps and lengths, and Mooncake's prompt-prefix
sharing; stretches time without changing burst shape.
</td>
<td width="33%" valign="top">
<b>🧩 ai-rm native</b><br>
Results are rm-core <code>Measurement</code>s; the runner is the <code>airm.workloads:rm-bench</code> entry point;
target addresses only come from flags or the environment.
</td>
</tr>
</table>

## 🚀 Quick start

```bash
pip install "rm-bench @ git+https://github.com/ai-computing/ai-rm#subdirectory=packages/rm-bench"
# or, from an ai-rm checkout
pip install -e packages/rm-bench          # brings rm-core v0.1.1

export LLMD_GATEWAY_URL=http://<llm-d-gateway>
rm-bench e2e --scenario pd-smoke --out results/pd-smoke.json
python -m pytest -q packages/rm-bench/tests   # fake OpenAI-compatible server, no cluster needed
```

## 🎯 End-to-end scenarios

```bash
rm-bench e2e --scenario pd-smoke [--gateway URL] [--model M] [--out results/<run>.json] [--kv-transport NAME] [--api chat|completions]
```

- **Where scenarios live:** `scenarios/<name>.yaml`, a `.yaml` path, or a directory in `$RM_BENCH_SCENARIOS`. By name the
  search order is `$RM_BENCH_SCENARIOS`, `./scenarios`, then this package's `scenarios/` (editable installs; wheels carry no
  scenarios). A scenario sets the request distribution (`synthetic` or `trace`), concurrency, duration and SLO
  (`rm_core.workload.SLO_KEYS`); the format is at the top of `rm_bench/scenario.py`.
- **Output:** `slo_attainment_pct` (share of requests meeting every latency bound; failures miss; success rate when there is
  no SLO), `tok_s`, `ttft_p90_ms`, `tpot_p90_ms`.
- **Verdict:** PASS when every SLO key (percentiles over the run, `tok_s_min` as a floor) and the error rate
  (`max_error_pct`, default 0) hold.
- `pd-smoke`: 32 small requests (Poisson 8 rps, concurrency 8) through the whole PD path; any error fails it.

<details>
<summary><b>How latency is measured</b></summary>
<br>

- **Open loop:** requests leave at the scenario's arrival times, and TTFT/E2E count from the **scheduled** arrival, so time
  spent waiting for the client's `concurrency` limit is part of the latency a user would see. After `duration_s` no new
  request is sent; requests still queued count as failed (unserved). `timeout_s` bounds one whole request.
- **TPOT** is `(e2e − TTFT) / (output tokens − 1)`, output tokens from the server's `usage` (else the number of content chunks).
- **`--api completions`** (or scenario `api: completions`) is for servers with only non-streaming `/v1/completions`. Without a
  stream the first token is not visible: when the response carries server timing (`pd.ttft_ms`, `pd.wall_ms`, as rngd-pd's
  gateway sends), TTFT = (e2e − wall_ms) + ttft_ms; otherwise TTFT = e2e (an upper bound). A `--gateway` URL ending in
  `/completions` is used as given (for routes that rewrite their own prefix to `/v1`).
- `--model` defaults to the scenario's `model`, else the first model at the gateway's `/v1/models`. `LLMD_API_KEY` is sent
  when set.
- The `loadgen/` tools keep their own definitions (TPOT per output chunk, tokens = chunks), so on servers that send several
  tokens per chunk their `tpot_*`/`tok_s` differ from `rm-bench e2e`. Use `rm-bench e2e` numbers for comparisons and KPIs.
</details>

## 📈 Real traces

Public production traces replayed with their **arrival times and input/output lengths** (Mooncake also with **prompt-prefix
sharing**). The data is never stored in a repository: `rm-bench traces fetch` downloads it to `$RM_BENCH_TRACES` (default
`~/.cache/rm-bench/traces`) with `ATTRIBUTION.md` and a sha256 `MANIFEST.json`.

| Name | Source | Records | License |
|---|---|---|---|
| `azure-2023-conv`, `azure-2023-code` | Azure LLM inference trace 2023 (Splitwise, ISCA'24) | arrival, input/output tokens | CC-BY-4.0 |
| `burstgpt-1` | BurstGPT v2.0, without failures, file 1 | Azure OpenAI GPT-3.5/4 usage, model, call type | CC-BY-4.0 |
| `mooncake-conversation`, `mooncake-toolagent` | Mooncake (Kimi, FAST'25) | arrival (ms), tokens, 512-token block `hash_ids` | Apache-2.0 |

```bash
rm-bench traces fetch                                    # all, or name some
rm-bench traces stats trace-azure-conv                   # requests, mean/peak rps, length p50/p90/p99, prefix reuse
rm-bench traces stats trace-azure-conv --max-total-tokens 512 --no-filter   # share that fits a target
rm-bench e2e --scenario trace-azure-conv --gateway URL --speedup 0.25 --max-total-tokens 512 --duration 300
python3 tools/trace_atlas.py                             # full characterization as JSON
```

- Scenarios: `trace-azure-conv`, `trace-azure-code`, `trace-burstgpt`, `trace-mooncake-conversation`; keys at the top of
  `rm_bench/traces.py`.
- `speedup` stretches or compresses time only, so bursts keep their shape.
- Requests over the target's limits (`--max-prompt-tokens`, `--max-output-tokens`, `--max-total-tokens`) are skipped
  (`--policy skip`, default, keeps the distribution) or clipped (`clip`). Check how many remain with `traces stats` first.
- Prompt text is not published, so prompts are synthetic text of the right length: unique per request (no accidental prefix
  sharing), and for Mooncake equal `hash_id` blocks get equal text so the trace's prefix reuse is real. Token counts are
  approximated by word counts.

What the traces look like and what they ask of the NPU stack: ai-rm [workload traces](../../docs/workload-traces.md).

## 🔌 ai-rm integration

Results use rm-core metric names (`rm_core.metrics.METRICS`: `ttft_p90_ms`, `tpot_p90_ms`, `tok_s`, …). Target addresses come
from `--gateway`/`--url` or `LLMD_GATEWAY_URL`, never from code or scenario files. There is no Kubernetes Job manifest yet.

```python
from rm_core import Workload, registry
runner = registry.load("airm.workloads", "rm-bench")
result = runner(Workload(kind="serve", model="meta-llama/Llama-3.1-8B-Instruct", slo={"ttft_p90_ms": 2000}),
                scenario="pd-smoke")
result.passed, result.measurements
```

Accepts `Workload(kind="serve")` only; `Workload.model` is the model requested and a non-empty `Workload.slo` replaces the
scenario's.

| Key | Required | Meaning |
|---|---|---|
| `scenario` | yes | scenario name in `scenarios/` or a `.yaml` path |
| `gateway` | no | gateway base URL; default `$LLMD_GATEWAY_URL` |
| `out` | no | Measurement JSON path; default `results/<run_id>.json`, `None` to skip |
| `kv_transport` | no | KV transport of the serving path under test, recorded as the `kv_transport` tag (rm-bench moves no KV) |

```bash
python -m pytest -q tests     # from packages/rm-bench
python -m rm_core.conformance
```

## 📊 Results format

Only rm-core protocol v0.1 metric names and tags; every entry passes `Measurement.validate()` before it is written.
Percentile metrics with no samples (e.g. `ttft_p90_ms` when every request failed) are omitted, not written as 0.

```json
[{"name": "tok_s", "value": 812.4,
  "tags": {"component": "rm-bench", "model": "...", "workload": "pd-smoke", "run_id": "pd-smoke-20261019T001448Z-0c86f2"}}]
```

Measured runs with these tools: ai-rm [end-to-end run](../../docs/e2e.md).

<details>
<summary><b>Load generators and tools</b></summary>
<br>

| Path | Contents |
|---|---|
| `rm_bench/` | `rm-bench e2e` runner, Measurement output, trace readers, ai-rm adapter (`rm_bench/airm.py`) |
| `scenarios/` | e2e scenarios (`pd-smoke.yaml`, `trace-*.yaml`) |
| `loadgen/replay_vllm_azure2024.py` | Azure LLM inference trace replayer (QPS, latency, live terminal dashboard) |
| `loadgen/synthetic_load_llm.py` | synthetic load generator |
| `tools/trace_atlas.py` | characterization of fetched traces |
| `tools/monitor_live.py` | live endpoint metrics (Prometheus view only, no `--out`) |
| `tools/send_test_traffic.sh` | a few test requests |

```bash
uv run python loadgen/replay_vllm_azure2024.py --csv hf-cache/AzureLLMInferenceTrace_conv_1week.csv \
  --url http://<llm-d-gateway>/v1/chat/completions --model meta-llama/Llama-3.1-8B-Instruct --speedup 10 --concurrency 16
```

Both loadgen tools also write rm-core Measurements with `--out results/<run>.json`. Research repositories report results
with `.research/report.py --metric ... --artifact ...`, which research-hub records in MLflow.

Moved from `rm_monitor` (ai-computing/rm_monitor@5d23892); the monitoring stack (Prometheus, Grafana, DCGM) and dashboards
went to `hetero-llm-d/monitoring/`.
</details>

## 📄 License

BSD-3-Clause ([LICENSE](LICENSE)). Downloaded traces keep their own licenses (see `ATTRIBUTION.md` next to them).
