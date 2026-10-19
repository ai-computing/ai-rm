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
- **TPOT**은 `(e2e − TTFT) / (출력 토큰 − 1)`이고, 출력 토큰 수는 서버의 `usage`(없으면 content chunk 수)입니다.
- **`--api completions`**(또는 시나리오 `api: completions`)는 스트리밍 없이 `/v1/completions`만 있는 서버용입니다. 첫 토큰을 볼 수
  없으므로 응답에 서버 측 시간(`pd.ttft_ms`, `pd.wall_ms`, rngd-pd 게이트웨이가 보냄)이 있으면 TTFT = (e2e − wall_ms) + ttft_ms,
  없으면 TTFT = e2e(상한)입니다. `--gateway`에 `/completions`로 끝나는 전체 URL을 주면 그대로 씁니다(접두사를 `/v1`로 바꾸는
  route 뒤).
- `--model`이 없으면 시나리오의 `model`, 그것도 없으면 게이트웨이 `/v1/models`의 첫 모델을 씁니다. `LLMD_API_KEY`가 있으면 보냅니다.
- `loadgen/` 도구들은 기존 정의(TPOT을 출력 chunk 수로 나눔, 토큰 = chunk)를 그대로 둡니다. 한 chunk에 여러 토큰을 보내는 서버에서는
  `tpot_*`/`tok_s`가 `rm-bench e2e`와 다르므로, 비교와 KPI에는 `rm-bench e2e` 값을 쓰세요.
</details>

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

이 도구로 실측한 결과: ai-rm [end-to-end 실행](../../docs/ko/e2e.md).

<details>
<summary><b>부하 생성기와 도구</b></summary>
<br>

| 경로 | 내용 |
|---|---|
| `rm_bench/` | `rm-bench e2e` 실행기, Measurement 출력, 트레이스 reader, ai-rm adapter(`rm_bench/airm.py`) |
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
`llm-d-setup/monitoring/`으로 갔습니다.
</details>

## 📄 라이선스

BSD-3-Clause ([LICENSE](LICENSE)). 받은 트레이스는 각자의 라이선스를 따릅니다(옆의 `ATTRIBUTION.md` 참고).
