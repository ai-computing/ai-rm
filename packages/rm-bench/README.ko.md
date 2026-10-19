<div align="center">

<h1>rm-bench</h1>

<h3>llm-d 엔드포인트용 end-to-end 부하, 실제 트레이스 재생, SLO 측정</h3>

<p>
  <a href="README.md">English</a> · <strong>한국어</strong>
</p>

<p>
  <a href="https://github.com/ai-computing/ai-rm"><img src="https://img.shields.io/badge/ai--rm-L5%20observe%20%26%20operate-f472b6" alt="ai-rm L5 계층"></a>
  <a href="https://github.com/ai-computing/rm-core/blob/v0.1.1/PROTOCOL.md"><img src="https://img.shields.io/badge/protocol-v0.1-7c5cff" alt="프로토콜 v0.1"></a>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml/badge.svg" alt="packages CI"></a>
  <img src="https://img.shields.io/badge/python-3.9%2B-3776ab?logo=python&amp;logoColor=white" alt="Python 3.9+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-64748b" alt="라이선스: BSD-3-Clause"></a>
</p>

<p>
  <a href="#-빠른-시작"><b>빠른 시작</b></a> ·
  <a href="#-end-to-end-시나리오"><b>시나리오</b></a> ·
  <a href="#-실제-트레이스"><b>실제 트레이스</b></a> ·
  <a href="#-에너지-표준-벤치마크-기준선-비교"><b>에너지·기준선</b></a> ·
  <a href="#-ai-rm-연동"><b>ai-rm 연동</b></a> ·
  <a href="#-결과-형식"><b>결과 형식</b></a>
</p>

</div>

---

**rm-bench**는 [ai-rm](https://github.com/ai-computing/ai-rm)의 측정 도구(L5)입니다. llm-d 게이트웨이 같은 OpenAI 호환
엔드포인트에 부하를 걸고, 실행을 SLO로 판정하고, TTFT·TPOT·E2E·처리량을 rm-core 지표 이름으로 보고합니다. ai-rm의
`packages/rm-bench`에 있습니다(2026-10-19에 독립 저장소에서 옮겨 왔고, 기존 저장소는 archive).

<table>
<tr>
<td width="33%" valign="top">
<b>🎯 SLO로 판정하는 시나리오</b><br>
열린 루프 도착, 요청마다 예정 도착 시각부터 잰 지연, 요청 단위 SLO 달성률, CI가 쓸 수 있는 종료 코드(0 PASS, 1 SLO 미달,
2 설정 오류).
</td>
<td width="33%" valign="top">
<b>📈 실제 운영 트레이스</b><br>
Azure 2023, BurstGPT, Mooncake 트레이스를 실제 도착 간격과 길이, Mooncake는 프롬프트 prefix 공유까지 그대로 재생합니다.
burst 모양은 유지한 채 시간만 늘리거나 줄입니다.
</td>
<td width="33%" valign="top">
<b>🧩 ai-rm 기본 연동</b><br>
결과는 rm-core <code>Measurement</code>, 실행기는 <code>airm.workloads:rm-bench</code> entry point, 대상 주소는 옵션이나
환경 변수로만 받습니다.
</td>
</tr>
</table>

## 🚀 빠른 시작

```bash
pip install "rm-bench @ git+https://github.com/ai-computing/ai-rm#subdirectory=packages/rm-bench"
# 또는 ai-rm checkout에서
pip install -e packages/rm-bench          # rm-core v0.1.1 포함

export LLMD_GATEWAY_URL=http://<llm-d-gateway>
rm-bench e2e --scenario pd-smoke --out results/pd-smoke.json
python -m pytest -q packages/rm-bench/tests   # 가짜 OpenAI 호환 서버, 클러스터 불필요
```

## 🎯 end-to-end 시나리오

```bash
rm-bench e2e --scenario pd-smoke [--gateway URL] [--model M] [--out results/<run>.json] [--kv-transport NAME] [--api chat|completions]
         [--deployment LABEL] [--cards N] [--power prom|cmd|none ...]
```

- **시나리오 위치:** `scenarios/<name>.yaml`, `.yaml` 경로, 또는 `$RM_BENCH_SCENARIOS` 디렉터리. 이름으로 찾을 때는
  `$RM_BENCH_SCENARIOS`, 현재 디렉터리의 `scenarios/`, 이 패키지의 `scenarios/` 순서입니다(editable 설치 기준, wheel에는 시나리오가
  없음). 시나리오는 요청 분포(`synthetic` 또는 `trace`), 동시성, 시간, SLO(`rm_core.workload.SLO_KEYS`)를 정하고, 형식은
  `rm_bench/scenario.py` 맨 위에 있습니다.
- **출력:** `slo_attainment_pct`(모든 지연 상한을 만족한 요청 비율, 실패는 미달, SLO가 없으면 성공률), `tok_s`, `ttft_p90_ms`, `tpot_p90_ms`.
- **판정:** SLO의 각 키(실행 전체의 백분위, `tok_s_min`은 하한)와 오류율(`max_error_pct`, 기본 0)을 모두 만족하면 PASS.
- `pd-smoke`: 작은 요청 32개(poisson 8 rps, 동시성 8)로 PD 경로 전체가 응답하는지 확인합니다. 오류가 하나라도 있으면 FAIL.

<details>
<summary><b>지연을 재는 방식</b></summary>
<br>

- **열린 루프:** 요청은 시나리오의 도착 시각에 맞춰 나가고 TTFT·E2E는 **예정 도착 시각부터** 잽니다. 그래서 클라이언트의
  `concurrency` 한도 때문에 기다린 시간도 사용자가 겪는 지연에 들어갑니다. `duration_s`가 지나면 새 요청을 내지 않고, 대기열에
  남은 요청은 실패(미처리)로 셉니다. `timeout_s`는 요청 하나의 전체 시간 한도입니다.
- **스트리밍 chat**(`--api chat`, 기본)은 SSE chunk로 잽니다. TTFT는 생성 텍스트(`content`, 추론 모델의 `reasoning_content`)가 든 첫
  chunk, ITL은 텍스트 chunk 사이 간격(p50/p90/p99는 실행 기록에), TPOT은 `(마지막 토큰 − TTFT) / (출력 토큰 − 1)`이라 마지막 토큰 뒤의
  `usage` chunk와 `[DONE]`은 decode 시간에 들어가지 않습니다. 출력 토큰 수는 마지막 `usage` chunk(없으면 텍스트 chunk 수)입니다.
  `[DONE]`으로 끝나거나 `finish_reason` 뒤 정상 종료되면 성공이고, `stream`을 무시하고 JSON 하나로 답하는 서버는 `--api completions`처럼
  잽니다. 연결 종료로 끝나는 스트림도 버퍼가 찰 때까지 기다리지 않고 도착하는 대로 읽습니다.
- **`--api completions`**(또는 시나리오 `api: completions`)는 스트리밍 없이 `/v1/completions`만 있는 서버용입니다. 첫 토큰을 볼 수
  없으므로 응답에 서버 측 시간(`pd.ttft_ms`, `pd.wall_ms`, rngd-pd 게이트웨이가 보냄)이 있으면 TTFT = (e2e − wall_ms) + ttft_ms,
  없으면 TTFT = e2e(상한)입니다. `--gateway`에 `/completions`로 끝나는 전체 URL을 주면 그대로 씁니다(접두사를 `/v1`로 바꾸는
  route 뒤).
- `--model`이 없으면 시나리오의 `model`, 그것도 없으면 게이트웨이 `/v1/models`의 첫 모델을 씁니다. `LLMD_API_KEY`가 있으면 보냅니다.
- `loadgen/` 도구들은 기존 정의(TPOT을 출력 chunk 수로 나눔, 토큰 = chunk)를 그대로 둡니다. 한 chunk에 여러 토큰을 보내는 서버에서는
  `tpot_*`/`tok_s`가 `rm-bench e2e`와 다르므로, 비교와 KPI에는 `rm-bench e2e` 값을 쓰세요.
</details>

## 🔋 에너지, 표준 벤치마크, 기준선 비교

```bash
# 실행 중 전력 샘플링 -> power_w, energy_j, tok/J (W7 근거)
rm-bench e2e --scenario pd-smoke --deployment same-vendor-pd --cards 2 \
  --power prom --power-url http://<prometheus> --power-query 'sum(DCGM_FI_DEV_POWER_USAGE)'
rm-bench e2e --scenario pd-smoke --power cmd --power-cmd 'furiosa-smi info' --power-regex '(\d+(?:\.\d+)?)\s*W\b'
# GuideLLM sweep과 MLPerf LoadGen 결과를 같은 형식으로
rm-bench import guidellm benchmarks.json --deployment vendor-pd --cards 2 --slo ttft_p90_ms=2000
rm-bench import mlperf mlperf_log_summary.txt --model meta-llama/Llama-3.1-8B-Instruct --deployment replication
# 하나의 markdown 표: SLO 달성률, 카드당 goodput, tok/J
rm-bench compare results/*.json [LABEL=results/x.json ...] --out compare.md
```

기준 클러스터의 exporter에서 동작을 확인한 전력 쿼리입니다(실행에 쓰는 카드만 합산).

| 가속기 | Exporter | `--power-query` |
|---|---|---|
| FuriosaAI RNGD | furiosa-metrics-exporter | `sum(furiosa_npu_hw_power{hostname="<node>",label="rms",device=~"npu0\|npu1"})` |
| Rebellions ATOM | rbln-metrics-exporter | `sum(RBLN_DEVICE_STATUS:CARD_POWER{node="<node>",name=~"rbln0"})` |
| NVIDIA GPU | DCGM exporter | `sum(DCGM_FI_DEV_POWER_USAGE{Hostname="<node>"})` |

세 쿼리 모두 `--power prom`으로 실제 샘플링해 읽기 오류가 없음을 확인했습니다.

- **전력** (`--power prom|cmd|none`, 기본 `none`): 요청이 도는 동안 `--power-interval`초(기본 1)마다 샘플링합니다. `prom`은 instant
  query 결과 벡터의 합(기본 `sum(DCGM_FI_DEV_POWER_USAGE)`, `--power-url` 또는 `$PROMETHEUS_URL`, NPU는 쓰는 exporter의 query를
  지정)입니다. `cmd`는 와트를 출력하는 아무 CLI나 실행해 `--power-regex`(첫 그룹)에 맞는 값을 모두 더합니다. 상한(cap) 열이 아니라
  소비 전력 열만 맞추세요. 평균 전력은 샘플의 시간 가중 평균, 에너지 = 평균 × 실행 시간, tok/J = 출력 토큰 / 에너지입니다.
  `power_w`, `energy_j`를 `scope=card|node`(`--power-scope`, 기본 `card`)로 기록하고, 최대 W와 tok/J는 실행 기록에 남깁니다. 읽기
  실패는 샘플 하나만 잃고 실행은 계속됩니다.
- **`--deployment LABEL`**은 배치 형태 이름(예: `same-vendor-pd`, `vendor-pd`, `replication`), **`--cards N`**은 `accelerators`를
  기록하고 카드당 goodput에 씁니다.
- **가져오기.** `guidellm`: GuideLLM JSON 보고서(`benchmarks.json`, GuideLLM 0.8 스키마, 예전 `run_stats`/`median` 형태도). sweep의
  benchmark마다 실행 하나가 되고 TTFT/TPOT p50/p90/p99, `e2e_p90_ms`, tok/s(측정 구간의 출력 토큰), req/s, 그리고 GuideLLM에 목표가
  있었으면 `slo_attainment`/`request_goodput`을 씁니다. `mlperf`: LoadGen의 `mlperf_log_summary.txt` 또는 `mlperf_log_detail.txt`
  (LLM Server/Offline). 첫 토큰·출력 토큰당 시간 백분위, 초당 완료 토큰/샘플, 그리고 `Result is : VALID`와 Server의 TTFT/TPOT p99
  제약으로 판정합니다. LoadGen은 요청별 SLO 비율을 내지 않으므로 MLPerf 실행에는 `slo_attainment_pct`가 없습니다.
  `--slo KEY=VALUE`를 주면 백분위로 SLO를 판정합니다.
- **비교**는 run_id마다 한 행: SLO 달성률과 판정, TTFT/TPOT p90, tok/s, goodput(초당 SLO 만족 요청, 없으면 req/s × 달성률), 카드당
  goodput, 평균(최대) W, tok/J(없으면 tok_s / power_w). 라벨은 `LABEL=`, 없으면 실행의 deployment, 없으면 파일 이름입니다.

## 📈 실제 트레이스

공개 운영 트레이스를 **도착 시각과 입출력 길이**(Mooncake는 **프롬프트 prefix 공유**까지) 그대로 재생합니다. 데이터는 저장소에
넣지 않고 `rm-bench traces fetch`로 `$RM_BENCH_TRACES`(기본 `~/.cache/rm-bench/traces`)에 받으며, 옆에 `ATTRIBUTION.md`와
sha256 `MANIFEST.json`을 남깁니다.

| 이름 | 출처 | 기록 | 라이선스 |
|---|---|---|---|
| `azure-2023-conv`, `azure-2023-code` | Azure LLM inference trace 2023 (Splitwise, ISCA'24) | 도착 시각, 입출력 토큰 | CC-BY-4.0 |
| `burstgpt-1` | BurstGPT v2.0 실패 제외본 1 | Azure OpenAI GPT-3.5/4 사용 기록, 모델·호출 유형 | CC-BY-4.0 |
| `mooncake-conversation`, `mooncake-toolagent` | Mooncake (Kimi, FAST'25) | 도착 시각(ms), 토큰, 512토큰 블록 `hash_ids` | Apache-2.0 |

```bash
rm-bench traces fetch                                    # 전부 (또는 이름 지정)
rm-bench traces stats trace-azure-conv                   # 요청 수, 평균·피크 rps, 길이 p50/p90/p99, prefix 재사용
rm-bench traces stats trace-azure-conv --max-total-tokens 512 --no-filter   # 대상 한도에 맞는 비율
rm-bench e2e --scenario trace-azure-conv --gateway URL --speedup 0.25 --max-total-tokens 512 --duration 300
python3 tools/trace_atlas.py                             # 전체 특성(JSON)
```

- 시나리오: `trace-azure-conv`, `trace-azure-code`, `trace-burstgpt`, `trace-mooncake-conversation`. 설정 키는 `rm_bench/traces.py` 맨 위.
- `speedup`은 시간 축만 바꾸므로 burst 모양은 유지됩니다.
- 대상 한도(`--max-prompt-tokens`, `--max-output-tokens`, `--max-total-tokens`)를 넘는 요청은 빼거나(`--policy skip`, 기본, 원래 분포
  유지) 잘라서(`clip`) 보냅니다. 얼마나 남는지는 `traces stats`로 먼저 확인하세요.
- 프롬프트 원문은 공개되지 않았으므로 길이만 맞춘 합성 텍스트입니다. 요청마다 다른 텍스트라 우연한 prefix 공유가 없고, Mooncake는
  같은 `hash_id` 블록에 같은 텍스트를 써서 원래 prefix 재사용을 재현합니다. 토큰 수는 단어 수로 맞춘 근사입니다.

트레이스의 모양과 NPU 환경에 요구하는 것: ai-rm [워크로드 트레이스](../../docs/ko/workload-traces.md).

## 🔌 ai-rm 연동

결과 지표는 rm-core 이름(`rm_core.metrics.METRICS`: `ttft_p90_ms`, `tpot_p90_ms`, `tok_s` …)을 따릅니다. 대상 주소는
`--gateway`/`--url`이나 `LLMD_GATEWAY_URL`로만 받고 코드나 시나리오 파일에 두지 않습니다. Kubernetes Job 매니페스트는 아직 없습니다.

```python
from rm_core import Workload, registry
runner = registry.load("airm.workloads", "rm-bench")
result = runner(Workload(kind="serve", model="meta-llama/Llama-3.1-8B-Instruct", slo={"ttft_p90_ms": 2000}),
                scenario="pd-smoke")
result.passed, result.measurements
```

`Workload(kind="serve")`만 받습니다. `Workload.model`로 요청하고, `Workload.slo`가 비어 있지 않으면 시나리오의 SLO 대신 씁니다.

| 설정 키 | 필수 | 내용 |
|---|---|---|
| `scenario` | 예 | `scenarios/`의 시나리오 이름 또는 `.yaml` 경로 |
| `gateway` | 아니오 | 게이트웨이 base URL. 기본 `$LLMD_GATEWAY_URL` |
| `out` | 아니오 | Measurement JSON 경로. 기본 `results/<run_id>.json`, `None`이면 저장 안 함 |
| `kv_transport` | 아니오 | 시험 대상 서빙 경로의 KV transport 이름. `kv_transport` 태그로만 기록(rm-bench는 KV를 옮기지 않음) |
| `power` | 아니오 | `rm_bench.power.make_sampler(...)`로 만든 sampler. 실행 중 샘플링 |
| `deployment`, `cards` | 아니오 | `rm-bench compare`용 배치 라벨과 가속기 수 |

```bash
python -m pytest -q tests     # packages/rm-bench에서
python -m rm_core.conformance
```

## 📊 결과 형식

rm-core protocol v0.1의 지표 이름·태그만 쓰고, 저장 전에 항목마다 `Measurement.validate()`를 통과해야 합니다. 샘플이 없는 백분위
지표(예: 모든 요청이 실패한 경우의 `ttft_p90_ms`)는 0으로 쓰지 않고 뺍니다.

```json
[{"name": "tok_s", "value": 812.4,
  "tags": {"component": "rm-bench", "model": "...", "workload": "pd-smoke", "run_id": "pd-smoke-20261019T001448Z-0c86f2"}}]
```

옆의 `<name>.meta.json`은 rm-core 지표에 없는 내용을 담는 실행 기록입니다: deployment, cards, SLO 판정 내역, goodput, ITL 백분위,
전력(`power_w`, `power_peak_w`, `energy_j`, `tok_per_j`, `scope`, `source`, `samples`). `rm-bench compare`는 둘 다 읽고, 기록이 없는
파일(예: `loadgen/` 출력)도 비교할 수 있습니다.

이 도구로 실측한 결과: ai-rm [end-to-end 실행](../../docs/ko/e2e.md).

<details>
<summary><b>부하 생성기와 도구</b></summary>
<br>

| 경로 | 내용 |
|---|---|
| `rm_bench/` | `rm-bench e2e` 실행기, Measurement 출력, 트레이스 reader, ai-rm adapter(`rm_bench/airm.py`), 전력 sampler(`power.py`), GuideLLM/MLPerf 가져오기(`imports.py`), 비교 표(`compare.py`) |
| `scenarios/` | e2e 시나리오 (`pd-smoke.yaml`, `trace-*.yaml`) |
| `loadgen/replay_vllm_azure2024.py` | Azure LLM inference trace 재생기 (QPS, 지연, 실시간 터미널 대시보드) |
| `loadgen/synthetic_load_llm.py` | 합성 부하 생성기 |
| `tools/trace_atlas.py` | 받은 트레이스의 특성 분석 |
| `tools/monitor_live.py` | 엔드포인트 지표 실시간 확인 (Prometheus 보기 전용, `--out` 없음) |
| `tools/send_test_traffic.sh` | 간단한 시험 요청 |

```bash
uv run python loadgen/replay_vllm_azure2024.py --csv hf-cache/AzureLLMInferenceTrace_conv_1week.csv \
  --url http://<llm-d-gateway>/v1/chat/completions --model meta-llama/Llama-3.1-8B-Instruct --speedup 10 --concurrency 16
```

두 loadgen 도구 모두 `--out results/<run>.json`을 주면 rm-core Measurement로도 저장합니다. 연구 저장소는
`.research/report.py --metric ... --artifact ...`로 보고하고 research-hub가 MLflow에 기록합니다.

`rm_monitor`(ai-computing/rm_monitor@5d23892)에서 옮겨 왔습니다. 모니터링 스택(Prometheus, Grafana, DCGM)과 대시보드는
`hetero-llm-d/monitoring/`으로 갔습니다.
</details>

## 📄 라이선스

BSD-3-Clause ([LICENSE](LICENSE)). 받은 트레이스는 각자의 라이선스를 따릅니다(옆의 `ATTRIBUTION.md` 참고).
