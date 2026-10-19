# rm-bench

ai-rm의 부하 생성·측정 도구 모음입니다. llm-d(OpenAI 호환 엔드포인트)를 대상으로 트래픽을 만들고 TTFT/TPOT/E2E/TPS를 측정합니다.

| 경로 | 내용 |
|---|---|
| `rm_bench/` | `rm-bench e2e` 시나리오 실행기, Measurement 결과 형식, ai-rm adapter(`rm_bench/airm.py`) |
| `scenarios/` | e2e 시나리오 정의 (`pd-smoke.yaml` …) |
| `loadgen/replay_vllm_azure2024.py` | Azure LLM inference trace 재생기 (QPS, 지연, 실시간 터미널 대시보드) |
| `loadgen/synthetic_load_llm.py` | 합성 부하 생성기 |
| `tools/monitor_live.py` | 엔드포인트 지표 실시간 확인 |
| `tools/send_test_traffic.sh` | 간단한 시험 요청 |

`rm_monitor`(ai-computing/rm_monitor@5d23892)에서 옮겨 왔습니다. 모니터링 스택(Prometheus, Grafana, DCGM)과 대시보드는 `llm-d-setup/monitoring/`으로 갔습니다.

## 사용 예

```bash
uv run python loadgen/replay_vllm_azure2024.py   --csv hf-cache/AzureLLMInferenceTrace_conv_1week.csv   --url http://<llm-d-gateway>/v1/chat/completions   --model meta-llama/Llama-3.1-8B-Instruct --speedup 10 --concurrency 16
```

두 loadgen 도구 모두 `--out results/<run>.json`을 주면 끝날 때 결과를 rm-core `Measurement` 목록으로도 저장합니다(아래 결과 형식 참고).
`tools/monitor_live.py`는 Prometheus를 실시간으로 보여 주기만 하고 실행 결과를 남기지 않으므로 `--out`이 없습니다.

측정 결과는 각 연구 repo의 `.research/report.py --metric ... --artifact ...`로 보고하면 research-hub가 MLflow에 기록합니다.

## ai-rm

[ai-rm](https://github.com/ai-computing/ai-rm)의 **L5 관측·운영** 구성요소입니다(`components/l5-ops/rm-bench`).
llm-d Gateway 같은 OpenAI 호환 엔드포인트에 부하를 걸고 지연·처리량을 측정합니다. 결과 지표 이름은
rm-core `rm_core.metrics.METRICS`(`ttft_p90_ms`, `tpot_p90_ms`, `tok_s` …)를 따릅니다.
대상 주소는 `--gateway`/`--url`이나 환경 변수(`LLMD_GATEWAY_URL`)로 넘기고, 코드나 시나리오 파일에 두지 않습니다.
k8s Job으로 돌리는 매니페스트는 아직 없습니다.

```bash
python -m pip install -e .            # rm-core v0.1.1 포함
python -m pytest -q tests             # 가짜 OpenAI 호환 서버로 e2e 확인
python -m rm_core.conformance
```

### 결과 형식 (Measurement JSON)

[rm-core](https://github.com/ai-computing/rm-core) protocol v0.1의 지표 이름·태그만 씁니다. 저장 전에 항목마다
`Measurement.validate()`를 통과해야 합니다.

```json
[{"name": "tok_s", "value": 812.4,
  "tags": {"component": "rm-bench", "model": "...", "workload": "pd-smoke", "run_id": "pd-smoke-20261019T001448Z-0c86f2"}}]
```

샘플이 없는 백분위 지표(예: 모든 요청이 실패한 경우의 `ttft_p90_ms`)는 0으로 쓰지 않고 뺍니다.

### e2e 시나리오

```bash
export LLMD_GATEWAY_URL=...           # 게이트웨이 base URL (/v1/chat/completions는 자동으로 붙음)
rm-bench e2e --scenario pd-smoke [--gateway URL] [--model M] [--out results/<run>.json] [--kv-transport NAME]
```

- 시나리오는 `scenarios/<name>.yaml`(또는 `.yaml` 경로, `$RM_BENCH_SCENARIOS` 디렉터리)에 둡니다. 이름으로 찾을 때는
  `$RM_BENCH_SCENARIOS`, 현재 디렉터리의 `scenarios/`, 이 checkout의 `scenarios/` 순서입니다(editable 설치 기준, wheel에는 시나리오가 들어 있지 않음). 요청 분포(`synthetic`
  또는 Azure `trace` CSV), 동시성, 시간, SLO(`rm_core.workload.SLO_KEYS`)를 정합니다. 형식은 `rm_bench/scenario.py` 맨 위에 있습니다.
- 출력: `slo_attainment_pct`(요청 단위로 SLO의 모든 지연 상한을 만족한 비율, 실패 요청은 미달, SLO가 없으면 성공률), `tok_s`, `ttft_p90_ms`, `tpot_p90_ms`.
- 열린 루프: 요청은 시나리오의 도착 시각에 맞춰 나가고, TTFT·E2E는 **예정 도착 시각부터** 잽니다. `concurrency` 한도 때문에
  클라이언트에서 기다린 시간도 사용자가 겪는 지연으로 들어갑니다. `duration_s`가 지나면 새 요청을 내지 않고,
  아직 대기열에 있던 요청은 실패(미처리)로 셉니다. `timeout_s`는 요청 하나의 전체 시간 한도입니다.
- 판정: SLO의 각 키(`ttft_p90_ms` 등은 실행 전체의 해당 백분위, `tok_s_min`은 처리량 하한)와 오류율(`max_error_pct`, 기본 0)을
  모두 만족하면 PASS. 종료 코드 0=PASS, 1=SLO 미달, 2=설정 오류.
- `--model`이 없으면 시나리오의 `model`, 그것도 없으면 게이트웨이 `/v1/models`의 첫 모델을 씁니다.
- 인증이 필요하면 `LLMD_API_KEY` 환경 변수를 씁니다.
- `pd-smoke`: 작은 요청 32개(poisson 8 rps, 동시성 8)로 PD 경로 전체가 응답하는지 확인합니다. 오류가 하나라도 있으면 FAIL.

TPOT은 `(e2e - TTFT) / (출력 토큰 - 1)`이고 출력 토큰 수는 서버가 주는 `usage`(없으면 content chunk 수)입니다.
loadgen 도구들은 기존 계산 방식(TPOT `/ 출력 chunk 수`, 출력 토큰 = chunk 수)을 그대로 둡니다. 그래서 한 chunk에 여러 토큰을 보내는
서버에서는 loadgen `--out`의 `tpot_*`/`tok_s`가 `rm-bench e2e` 값과 같은 정의가 아닙니다. 비교·KPI에는 `rm-bench e2e` 값을 쓰세요.

### ai-rm adapter: `airm.workloads` / `rm-bench`

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
| `kv_transport` | 아니오 | 시험 대상 서빙 경로의 KV transport 이름. rm-bench는 KV를 옮기지 않으므로 `kv_transport` 태그로만 기록 |
