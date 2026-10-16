# rm-bench

ai-rm의 부하 생성·측정 도구 모음입니다. llm-d(OpenAI 호환 엔드포인트)를 대상으로 트래픽을 만들고 TTFT/TPOT/E2E/TPS를 측정합니다.

| 경로 | 내용 |
|---|---|
| `loadgen/replay_vllm_azure2024.py` | Azure LLM inference trace 재생기 (QPS, 지연, 실시간 터미널 대시보드) |
| `loadgen/synthetic_load_llm.py` | 합성 부하 생성기 |
| `tools/monitor_live.py` | 엔드포인트 지표 실시간 확인 |
| `tools/send_test_traffic.sh` | 간단한 시험 요청 |

`rm_monitor`(ai-computing/rm_monitor@5d23892)에서 옮겨 왔습니다. 모니터링 스택(Prometheus, Grafana, DCGM)과 대시보드는 `llm-d-setup/monitoring/`으로 갔습니다.

## 사용 예

```bash
uv run python loadgen/replay_vllm_azure2024.py   --csv hf-cache/AzureLLMInferenceTrace_conv_1week.csv   --url http://<llm-d-gateway>/v1/chat/completions   --model meta-llama/Llama-3.1-8B-Instruct --speedup 10 --concurrency 16
```

측정 결과는 각 연구 repo의 `.research/report.py --metric ... --artifact ...`로 보고하면 research-hub가 MLflow에 기록합니다.

## ai-rm

[ai-rm](https://github.com/ai-computing/ai-rm)의 **L5 관측·운영** 구성요소입니다(`components/l5-ops/rm-bench`).
llm-d Gateway 같은 OpenAI 호환 엔드포인트에 부하를 걸고 지연·처리량을 측정합니다. 결과 지표 이름은
ai-rm `docs/interfaces.md`의 Metrics 표(`ttft_p90_ms`, `tpot_p90_ms`, `tok_s` …)를 따릅니다.
대상 주소는 `--url`로 넘기고 코드에 두지 않습니다. k8s Job으로 돌리는 매니페스트는 아직 없습니다.
