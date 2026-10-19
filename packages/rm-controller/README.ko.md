<div align="center">

<h1>rm-controller</h1>

<h3>이종 llm-d 풀을 위한 토폴로지 인지·최적 배치</h3>

<p>
  <a href="README.md">English</a> · <strong>한국어</strong>
</p>

<p>
  <a href="https://github.com/ai-computing/ai-rm"><img src="https://img.shields.io/badge/ai--rm-L4%20cluster%20%26%20placement-fbbf24" alt="ai-rm L4 계층"></a>
  <a href="https://github.com/ai-computing/rm-core/blob/v0.1.1/PROTOCOL.md"><img src="https://img.shields.io/badge/protocol-v0.1-7c5cff" alt="프로토콜 v0.1"></a>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml/badge.svg" alt="packages CI"></a>
  <img src="https://img.shields.io/badge/stage-first%20version-107e72" alt="단계: 1차 구현">
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-64748b" alt="라이선스: BSD-3-Clause"></a>
</p>

<p>
  <a href="#-빠른-시작"><b>빠른 시작</b></a> ·
  <a href="#-배치-정책"><b>정책</b></a> ·
  <a href="#-spec"><b>Spec</b></a> ·
  <a href="#-제어-루프"><b>제어 루프</b></a> ·
  <a href="#-시뮬레이션-topology-대-optimal"><b>시뮬레이션</b></a> ·
  <a href="#-검증"><b>검증</b></a> ·
  <a href="#-로드맵"><b>로드맵</b></a>
</p>

</div>

---

**rm-controller**는 [ai-rm](https://github.com/ai-computing/ai-rm)의 L4 배치 컨트롤러입니다. L1이 게시한 가속기
(`AcceleratorProfile`)와 그 상태, 노드 상태를 읽고, spec이 요구하는 prefill/decode 풀을 배치하고, 결정을 ConfigMap
`airm-placement`에 씁니다. EPP scorer와 lmd-top이 이 ConfigMap을 읽습니다(rm-core PROTOCOL §5.4, `rm_core.placement`, 키
`decisions.json`). 선택적으로 부하에 따라 P:D를 재조정하고, 서빙 Deployment가 결정을 따르도록 patch합니다.

<table>
<tr>
<td width="33%" valign="top">
<b>🧭 토폴로지 우선</b><br>
host-local KV 경로는 prefill과 decode를 한 노드의 서로 다른 카드에 둡니다. cordon·NotReady 노드는 고르지 않습니다.
</td>
<td width="33%" valign="top">
<b>🧮 파드가 아니라 풀 단위</b><br>
풀마다 P:D 1:N, 풀은 순서대로 배치하고 카드를 공유하지 않으며, 들어갈 곳이 없으면 이유와 함께 빈 결정을 남깁니다.
</td>
<td width="33%" valign="top">
<b>📝 바뀔 때만 기록</b><br>
결정이 바뀔 때만 문서의 <code>generation</code>이 올라갑니다. 유효한 배치는 유지하고, 카드를 잃은 역할만 다시 배치합니다.
</td>
</tr>
</table>

## 🚀 빠른 시작

```bash
pip install "rm-core @ git+https://github.com/ai-computing/rm-core@v0.1.2"   # rm-core>=0.1.2,<0.2 (PyPI에 없음)
pip install -e packages/rm-controller            # PyYAML. [k8s]는 클러스터 안 클라이언트 추가
rm-controller --spec packages/rm-controller/examples/spec.yaml --dry-run   # 쓸 내용만 출력
rm-controller --spec spec.yaml --once            # 결정이 바뀌었으면 기록 (generation +1)
rm-controller --spec spec.yaml --interval 60     # 계속 배치
rm-controller --spec spec.yaml --apply --dry-run # Deployment patch도 출력 (--apply만 주면 patch 적용)
rm-controller --spec spec.yaml --rebalance       # prefill과 decode 사이 카드 재조정 (W5)
rm-controller --spec packages/rm-controller/examples/optimal.yaml --dry-run   # optimal 정책 (W6)
python -m rm_core.conformance airm.placements topology optimal
python -m rm_controller.sim --compare            # 트레이스 통계로 topology와 optimal을 시뮬레이션 비교
python -m rm_controller.sim --episode            # W5 재조정기 에피소드 재생, 선형 규칙 대 예측 규칙
python -m rm_controller.baselines --compare      # DistServe·HexGen-2 방식 기준선
```

파드 밖에서는 현재 kubeconfig로 `kubectl`을, 파드 안(`KUBERNETES_SERVICE_HOST` 있음)에서는 Python 클라이언트
(`pip install -e "packages/rm-controller[k8s]"`)를 씁니다. 종료 코드: 0 기록 또는 변경 없음, 1 배치하지 못한 풀이 있음(문서에 이유를
남김), 2 사용법·클러스터 오류.

## 🧭 배치 정책

정책 `topology`, entry point `airm.placements:topology`. 첫 end-to-end 실행에서 드러난 문제(ai-rm [e2e](../../docs/ko/e2e.md):
rm-core 참조 `greedy`가 cordon된 노드의 같은 카드에 prefill과 decode를 둠)를 바탕으로 만들었습니다.

| 규칙 | 이유 |
|---|---|
| `shm`, `p2p`, `loopback`은 prefill·decode를 **한 노드**에, `loopback`이 아니면 카드는 서로 다르게 | KV 경로가 호스트 안에 있음 |
| cordon·NotReady 노드 제외 | 그곳 배치는 실행될 수 없음 |
| prefill은 **최고 peak**(워크로드 정밀도 기준), decode는 **최대 메모리**, 동점은 낮은 카드 번호 | prefill은 연산, decode는 메모리가 좌우, 선택이 안정적 |
| 역할별 `count` | P:D 1:N |
| 풀은 순서대로, 카드 공유 없음 | 중복 배정 방지 |
| 들어갈 곳이 없으면 이유와 함께 빈 결정 | 오류로 멈추지 않고 이유가 남음 |

`AcceleratorProfile`이 비정상으로 보고한 카드(`spec.extra.health`, 또는 `status.health`나 True가 아닌 `Healthy`/`Ready`
condition)와 Disk/Memory/PID pressure 노드도 cordon 노드처럼 제외합니다.
`place()`는 rm-core의 워크로드 단위 계약을 지키고(적합성 PASS), `place_pd()`는 prefill/decode 쌍을 함께 배치합니다.

### `optimal` (W6)

정책 `optimal`, entry point `airm.placements:optimal`(spec의 `placement: optimal`). prefill 장치 종류(들), decode 장치 종류(들),
각각의 인스턴스 수, 노드, KV 링크를 골라 **SLO를 지키는 카드당 goodput**을 최대로 합니다. 입력:

- 비어 있고 정상인 카드(종류 `vendor.model`, 노드)와 역할별 종류 필터(선택);
- 장치 종류별 처리량 프로파일(prefill tok/s, batch 1과 최대 batch의 decode TPOT, KV 용량, 인스턴스당 카드 수)과 KV 링크별
  비용(대역폭, 지연, 범위 host/cluster, 검증된 종류 쌍): [`rm_controller/profiles.yaml`](rm_controller/profiles.yaml), 또는
  `--profiles` / `profiles:`로 직접 지정;
- 워크로드 구성: 평균·p90 길이, 평균 도착률, 60초 peak/평균. 트레이스 통계(`workload: {trace: azure-conv}`)나 직접 값;
- SLO(`ttft_p90_ms`, `tpot_p90_ms`)와 카드 `budget`.

| | |
|---|---|
| Decode | batch = TPOT ≤ SLO이고 batch × (입력 + 출력) ≤ KV 용량인 최댓값. 프롬프트의 90 % 미만이 KV에 들어가면 그 종류는 제외 |
| TTFT p90 | prefill(p90 프롬프트) + KV(링크, p90 프롬프트) + TPOT + prefill 서버 대기 p90 + decode 슬롯 대기 p90 (M/G/c, Erlang C + Allen–Cunneen) |
| Goodput | TTFT p90 ≤ SLO인 최대 도착률 ÷ peak/평균 (60초 peak 기준으로 용량 산정) |
| 역할 내 혼합 | `mixed_roles: true`(기본): 한 역할에 여러 종류의 인스턴스. prefill은 종류별 M/G/c, 도착을 라우팅 가중치로 나눔 — 가중치 = 그 종류 그룹이 자신의 TTFT p90을 SLO 안에 지키며 받는 도착률(그래서 모든 그룹이 SLO를 지킴). decode는 용량 비례. 역할마다 한 종류면 위 모델과 같은 값 |
| 제약 | 인스턴스의 카드는 한 노드, 모든 prefill→decode 종류 쌍이 계획의 KV 링크로 연결, host 범위 링크(`shm`, `p2p`)는 풀을 한 노드에, 역할별 인스턴스 ≥ 1, 카드 ≤ budget, `mixed_roles: false`면 역할마다 종류 하나 |
| 목적 | 도착률 없음: 카드당 goodput 최대, 다음 goodput. 도착률 있음: 감당하는 최소 카드. `objective: goodput`: goodput 최대 |
| 탐색 | 링크 × 노드 × 종류² × 인스턴스 수 완전 열거 (카드 32장에서 수천 후보). 혼합은 카드·budget 안의 종류별 개수 벡터 쌍을 상한(min(prefill, decode 용량)/peak) 순으로 보고 상한이 못 이기면 중단. 20만 쌍을 넘는 범위는 종류 하나씩만 보고 reason에 기록 |
| 대체 | 빈 카드 종류에 프로파일이 없거나, `loopback`, 모르는 전송, SLO를 지키는 후보 없음 → spec의 개수로 `topology`, 이유에 기록. 선택지가 하나뿐인 풀은 topology와 같은 결과 |

`kv_transport: auto`는 구현된 링크 중에서 고릅니다. `p2p`는 검증된 RNGD → ATOM에만 제시합니다.
프로파일 수치마다 파일에 측정(measured)·유도(derived)·추정(estimate)을 표시했습니다. RNGD와 ATOM decode는 실제 S=512 그래프에서
측정했고([기준선](../../docs/ko/baselines.md)), 노드 간 `tcp` 링크(다른 노드의 relay를 거치는 rngd-pd TCP 전송, 1 GbE)도 측정값입니다.
ATOM prefill, A100과 `p2p`·`cuda-ipc` 링크는 FASOP NPU 비용 모델
([aicomp #50](https://github.com/ai-computing/aicomp/issues/50))이나 sweep으로 바꿀 때까지 추정치입니다.

## 📝 Spec

```yaml
namespace: llm-serving                 # airm-placement가 있는 네임스페이스 (llm-d 네임스페이스)
pools:
  - pool: llama8b-pd-pool              # InferencePool 이름
    model: meta-llama/Llama-3.1-8B-Instruct
    kv_transport: shm                  # airm.kv_transports 이름
    slo: {tpot_p90_ms: 100}
    prefill: {accelerator: furiosa.RNGD, count: 1}
    decode:  {accelerator: furiosa.RNGD, count: 1}
```

`accelerator`는 노드 레이블 `airm.ai-computing.io/<vendor>.<model>`과 같은 `vendor.model` 형식입니다. 선택 키:

```yaml
placement: optimal                     # topology (기본) | optimal
objective: per_card                    # optimal: per_card (기본) | goodput
mixed_roles: true                      # optimal: 역할 안에 장치 종류 혼합 허용 (기본 true)
profiles: my-profiles.yaml             # optimal / rebalance / apply: 처리량 표 (기본: 패키지 내장)
pools:
  - pool: ...
    kv_transport: auto                 # optimal 전용: 구현된 링크 중 선택
    workload: {trace: azure-conv}      # 또는 {mean_input_tokens, mean_output_tokens, rate_rps, peak_ratio}
    budget: 6                          # 이 풀의 최대 카드 수 (optimal, rebalance)
    rebalance: {metrics: http://<pod>:8000/metrics, band: 0.2, hold: 3, cooldown_s: 300, margin: 0.2}
```

**여러 풀, 여러 모델 (HUB-35).** spec에는 풀을 몇 개든 쓸 수 있고 풀마다 모델이 다릅니다. 순서대로 배치하며 한 카드를
두 풀에 주지 않습니다. 풀은 prefill/decode(위와 같음)이거나, 두 단계를 한 카드에서 모두 도는 엔진(furiosa-llm, vLLM)의
단일 카드 레플리카로 된 aggregated 풀입니다:

```yaml
  - pool: qwen3-4b-pool
    model: furiosa-ai/Qwen3-4B-FP8
    serve: {accelerator: furiosa.RNGD, count: 1}   # `serve` 결정 하나; kv_transport, rebalance 없음
```

aggregated 풀은 어느 정책에서든 그 종류의 빈 카드 `count`장을 가져갑니다(그런 카드가 가장 많은 노드부터). 프로파일은
prefill/decode 경로를 기술할 뿐 다른 모델의 단일 카드 서빙은 기술하지 않기 때문입니다. Deployment에는 `role: serve`를
붙입니다. 한 풀의 spec이 바뀌면 그 풀은 직전 세대에 다른 풀이 쓰던 카드를 피해 들어갈 수 있으면 그렇게 배치되고, 다른
풀은 결정을 그대로 유지합니다. 그래서 다시 실행해도 바뀐 풀만 움직입니다
(라이브: [baselines](../../docs/ko/baselines.md#w2-한-노드의-두-모델-풀-hub-35)).

예시: [`examples/spec.yaml`](examples/spec.yaml)(shm으로 RNGD+RNGD, rebalance 포함),
[`examples/hetero-p2p.yaml`](examples/hetero-p2p.yaml)(같은 호스트 P2P로 RNGD prefill, ATOM ×2 decode),
[`examples/optimal.yaml`](examples/optimal.yaml)(optimal, `kv_transport: auto`, budget 6),
[`examples/multi-pool.yaml`](examples/multi-pool.yaml)(두 모델: Llama-3.1-8B PD와 Qwen3-4B aggregated).

## 🔁 제어 루프

**재배치 (W5).** 아직 유효한 결정은 유지하므로, 노드가 복구돼도 실행 중인 풀을 옮기지 않습니다. 배치된 카드가 사라지거나
비정상이 되거나 그 노드가 스케줄 불가가 되면 그 카드를 잃은 역할만 다시 배치합니다(KV 경로가 host-local이거나 인스턴스가 여러
카드면 같은 노드에서). 두 역할 모두 잃으면 풀을 새로 배치합니다. 바뀐 결정이 `generation`을 올리고, `reason`에 잃은 카드와
이유(`gone`, `unhealthy`, `node … unschedulable`)가 남습니다.

**P:D 재조정 (W5, `--rebalance`).** `rebalance:` 절이 있는 풀마다 카드 `budget`을 prefill과 decode 인스턴스로 나눌 목표를 계산합니다.

- 지표로: URL이나 파일의 Prometheus 텍스트(하나, 또는 `{prefill: …, decode: …}`). 역할별 `vllm:num_requests_waiting`
  (`role` / `llm-d.ai/role` 레이블), `vllm:time_to_first_token_seconds`·`vllm:time_per_output_token_seconds` 히스토그램
  (읽기 사이 구간), 또는 게이트웨이의 `airm_ttft_p90_ms` / `airm_tpot_p90_ms`. Optimus Prime이
  [aicomp #45](https://github.com/ai-computing/aicomp/issues/45)로 내보낼 이름입니다. 역할별 압력 = max(지연/SLO, 인스턴스당 대기/2).
  도착률과 평균 길이는 `vllm:request_success_total`과 `vllm:request_prompt_tokens` / `vllm:request_generation_tokens`
  히스토그램, 또는 게이트웨이의 `airm_req_s` / `airm_tok_s`에서, 없으면 풀의 `workload` 트레이스 통계에서 가져옵니다;
- 지표가 없으면 워크로드의 트레이스 통계와 프로파일로(peak 도착률 ÷ 인스턴스 하나의 용량).

지표가 있고 두 장치 종류의 프로파일이 있으면 목표는 예측에서 나옵니다([`predict.py`](rm_controller/predict.py)). 예산의 모든
분할에서 두 역할의 압력을 `optimal`의 대기열 모델로 예측합니다(prefill은 TTFT p90용 M/G/c, decode는 TPOT SLO 배치의 lane과 그
대기를 TPOT에 넣고, `admit_blocking` 링크(`shm`)에서는 admission마다 KV 로드 동안 decode 루프가 멈춤). 모델은 먼저 현재 분할에
맞춥니다. SLO를 넘은 역할이 보이는 값을 재현하는 도착률이 풀의 실효 도착률이 되고(평균 도착률이 놓치는 burst가 여기 드러남),
여유 있는 역할은 자기 측정값으로 예측 도착률에 상한을 두며, decode는 prefill이 통과시키는 만큼 받으므로 prefill이 많은 분할일수록
burst가 decode에 더 많이 넘어갑니다. 가장 좋은 분할의 예측 최악 역할 압력이 현재 분할보다 `margin`(기본 20 %) 이상 낮을 때만
목표가 되고, 아니면 분할을 유지하며 라운드 로그에 이유를 남깁니다(예: `hold: no split predicted better than now 1:2 P 2.44 D
0.66; best other 2:1 P 0.12 D inf at 6.37 req/s (prefill fit)`). 프로파일이 없는 장치 종류는 선형 규칙(필요 인스턴스 = 현재 ×
압력)을 그대로 씁니다.

히스테리시스: 두 압력이 모두 1 이하면 그대로 둡니다. 목표는 P:D 비율을 `band`보다 크게 바꿔야 하고, `hold`번 연속 제안되어야
하며, 마지막 변경 후 `cooldown_s`가 지나야 합니다(`--once`는 hold 1, cooldown 없음). 분할이, 따라서 결정이 바뀔 때만 새
generation을 씁니다. `topology`에서는 분할이 역할별 개수가 되고, `optimal`에서는 인스턴스 수를 고정한 채 종류·노드·링크를 고릅니다.

**적용 모드 (HUB-11, `--apply`).** `airm.ai-computing.io/pool: <pool>`과 `airm.ai-computing.io/role: prefill|decode|serve`
annotation이 있는 Deployment에 merge patch를 보냅니다: `spec.replicas`(카드 수 ÷ 인스턴스당 카드), 레이블
`airm.ai-computing.io/<vendor>.<model>`과 결정의 노드(`kubernetes.io/hostname`)에 대한 필수 node affinity, 장치를 고정하는
chart를 위한 pod template annotation `airm.ai-computing.io/accelerator-ids`. 종류를 섞은 역할은 종류마다 Deployment를 두고
`airm.ai-computing.io/accelerator: <vendor>.<model>` annotation을 답니다. 그 종류의 카드만 따르고, 결정에 그 종류가 없으면 replicas 0.
라우팅 가중치는 결정의 `reason`에 있고, 게이트웨이가 그 비율로 나눠야 합니다(시뮬레이터는 그렇게 함). 이미 일치하는 Deployment는 patch하지 않고,
빈 결정은 Deployment를 건드리지 않습니다. `--apply --dry-run`은 `{"document", "patches"}`를 출력합니다. `--apply`가 없으면
이전처럼 ConfigMap만 씁니다.

## 📊 시뮬레이션: topology 대 optimal

`python -m rm_controller.sim --compare`는 트레이스 통계([워크로드 트레이스](../../docs/ko/workload-traces.md)의 길이 분위수,
평균 도착률, 60초 peak/평균)를 배치의 이산 사건 모델(인스턴스별 FCFS prefill, 링크를 통한 KV 전달, KV 용량으로 받는 continuous
batching decode)에 넣고, 요청의 90 % 이상이 TTFT와 TPOT를 지키는 최대 평균 도착률(goodput)을 찾습니다. SLO: Azure 대화와
BurstGPT 2초/100 ms, Azure 코드 4초/100 ms, Mooncake 15초/100 ms(긴 프롬프트). 실행당 요청 4,000개, seed 1:

**1 node: 2 RNGD + 4 ATOM** — goodput req/s (카드당 req/s), optimal은 숫자 아래에 배치

| 트레이스 | topology RNGD/RNGD shm | topology RNGD/ATOM×2 p2p | optimal (per card) | optimal (max goodput) |
|---|--:|--:|--:|--:|
| azure-conv | 0.813 (0.406) | 0.000 (0.000) | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm |
| azure-code | 0.943 (0.472) | 0.000 (0.000) | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm |
| burstgpt | 0.025 (0.013) | 0.000 (0.000) | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-conv | 0.563 (0.281) | 0.000 (0.000) | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-tool | 0.950 (0.475) | 0.000 (0.000) | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm |

**2 nodes: 2 x (2 RNGD + 4 ATOM)** — goodput req/s (카드당 req/s), optimal은 숫자 아래에 배치

| 트레이스 | topology RNGD/RNGD shm | topology RNGD/ATOM×2 p2p | optimal (per card) | optimal (max goodput) | optimal (max goodput, `tcp` only) |
|---|--:|--:|--:|--:|--:|
| azure-conv | 0.813 (0.406) | 0.000 (0.000) | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |
| azure-code | 0.943 (0.472) | 0.000 (0.000) | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |
| burstgpt | 0.025 (0.013) | 0.000 (0.000) | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |
| mooncake-conv | 0.563 (0.281) | 0.000 (0.000) | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |
| mooncake-tool | 0.950 (0.475) | 0.000 (0.000) | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, tcp |

이 프로파일로 보면:

- **프로파일은 이제 대부분 측정값**입니다. 실제 기준선 실험의 S=512 그래프에서 쟀습니다([기준선](../../docs/ko/baselines.md)):
  RNGD prefill 66 ms + 12K tok/s, RNGD decode는 batch 8까지 토큰당 30 ms(continuous B=8 그래프는 폭이 고정), ATOM decode는 카드 한 장에서
  batch 4까지 토큰당 108 ms, `shm` 1.6 GB/s, `tcp` 0.08 GB/s + 14 ms(NPU 노드의 1 GbE 링크로 노드 간 측정). ATOM prefill과 `p2p`는 아직 추정치입니다.
- **노드 하나에서는 optimal이 RNGD/RNGD 풀**입니다. ATOM decode는 어떤 batch에서도 TPOT SLO 100 ms를 넘으므로 ATOM으로 decode하는
  풀은 goodput이 0입니다. 실제 RNGD → ATOM 기준선도 SLO를 지킨 요청이 0 %였습니다.
- **노드 둘에서는 측정한 `tcp` 링크로 얻는 것이 없습니다.** 요청당 67 MB(S=512 버퍼 전체, 1 GbE)를 ~0.85초에 옮기고 트레이스
  프롬프트의 KV는 몇 초가 걸리므로 TTFT SLO를 지키는 2노드 계획이 없습니다. optimal은 `shm`으로 한 노드에 머물고, 가장 좋은
  `tcp` 계획(마지막 열; SLO를 지키는 계획이 없어 topology의 1P+1D)은 goodput이 0입니다. 예전 추정치(0.5 GB/s, 계획 링크)로는 같은
  열이 0.087–2.724 req/s, 한 노드의 2.0–3.5배였습니다. 대역폭을 바꿔 보면 2노드 배치는 0.15–0.25 GB/s 사이(2.5 GbE 이상)에서
  돌아오고, 0.8 GB/s에서는 Azure 대화 2.73 req/s(P 1 / D 3 RNGD), Azure 코드 2.39(P 3 / D 1)로 추정치 때와 같습니다. 두 노드 사이
  NPU 간 전송은 측정하지 않았습니다. 두 번째 NPU 노드가 cordon 상태여서 RNGD → CPU relay 노드 → RNGD로 쟀습니다.
- Mooncake 행은 외삽입니다. S=512 그래프는 그 프롬프트를 아예 처리하지 못하고, prefill 속도를 512 토큰 너머로 선형 연장했으므로
  (attention의 제곱 항 무시) 낙관적입니다.
- 용량을 트레이스별 60초 peak(BurstGPT 69배)에 맞추므로 절대값이 낮습니다.
- `optimal`의 분석 모델은 시뮬레이션 goodput의 0.68–0.93배로 모든 행에서 보수적입니다([컴포넌트 카드](../../docs/components/rm-controller.md)의
  "Model est." 열). 둘 다 같은 프로파일을 읽으며, 프로파일 자체는 실제 실행으로 확인합니다([기준선](../../docs/ko/baselines.md#보정-w6)).

**에피소드 재생 (`--episode`).** [`episode.py`](rm_controller/episode.py)는 W5의 실제 재조정기 실행을 재생합니다. rngd-pd
게이트웨이 뒤 RNGD 카드 3장에 Azure 코드 ×3과 대화 ×2 재생을 번갈아 걸고(`$RM_BENCH_TRACES`의 Azure 2023 CSV가 있으면 실제
도착 시각, 없으면 구간 통계), 재조정기가 60초마다 게이트웨이 지표를 읽어 hysteresis대로 움직입니다. 파드 시작 2분, 옮기는 카드의
처리 중 요청 손실도 넣습니다. 프로파일 위에 클라이언트의 동시 요청 64개, decode admission 때 루프 안의 KV 로드, Service로 무작위로
닿는 prefill 파드, 부하에서 유휴 프로파일의 1.5배인 prefill 시간(`--prefill-scale`)을 모델링합니다. 결과:
[기준선](../../docs/ko/baselines.md#예측-규칙).

## ⚖️ 기준선: DistServe·HexGen-2 방식 배치

`python -m rm_controller.baselines --compare`는 발표된 배치 알고리즘 두 가지를 단순화해([`rm_controller/baselines.py`](rm_controller/baselines.py))
`topology`, `optimal`과 같은 시뮬레이터로 돌립니다. 카드 구성은 GPU 전용 노드(A100 4장), NPU 노드(RNGD 2 + ATOM 4), 혼합 노드
(A100 2 + RNGD 2 + ATOM 4)입니다.

- **distserve** (DistServe, OSDI'24, "high node-affinity" 배치): 두 단계 모두 한 장치 종류, 한 노드. prefill은 TTFT SLO에 대한
  M/D/1 대기열로, decode는 TPOT SLO를 지키는 최대 batch로 단계별로 따로 크기를 정한 뒤, 카드당 goodput이 가장 좋은 인스턴스 수와
  종류를 고릅니다. 병렬화(TP/PP) 탐색은 뺐습니다.
- **hexgen2** (HexGen-2, ICLR'25): 카드 → 인스턴스, 인스턴스마다 역할, source → prefill → (KV 링크) → decode → sink의 max-flow,
  흐름이 커지는 동안 역할 뒤집기·맞바꾸기로 개선, 흐름이 없는 인스턴스는 제외. 한 역할 안에 종류가 섞일 수 있습니다. 간선별 링크
  선택, 흐름 비례 라우팅, 병렬화 탐색은 뺐습니다.
- Helix(레이어 배치에 대한 MILP)는 모델링하지 않았습니다. 우리 엔진은 모델 전체를 한 인스턴스로 돌립니다.

A100 수치는 일부 추정입니다(prefill 속도와 batch 1 TPOT는 데이터시트에서, batch 64 TPOT는 hetero-llm-d A100 실행에서 유도). GPU
링크 `cuda-ipc`(vLLM NixlConnector 경로, 20 GB/s 추정)는 ai-rm에 전송 플러그인이 없지만 여기서는 모든 정책이 쓸 수 있다고 봅니다.
실행당 요청 4,000개, seed 1:

**GPU only: 1 node, 4 A100** — goodput req/s (카드당 req/s), 숫자 아래에 배치

| 트레이스 | topology (cuda-ipc) | optimal, per card | optimal, max goodput | distserve | hexgen2 |
|---|--:|--:|--:|--:|--:|
| azure-conv | 4.218 (2.109)<br>P 1x A100 / D 1x A100, cuda-ipc | 8.644 (2.881)<br>P 2x A100 / D 1x A100, cuda-ipc | 12.113 (3.028)<br>P 3x A100 / D 1x A100, cuda-ipc | 8.644 (2.881)<br>P 2x A100 / D 1x A100, cuda-ipc | 12.113 (3.028)<br>P 3x A100 / D 1x A100, cuda-ipc |
| azure-code | 1.040 (0.520)<br>P 1x A100 / D 1x A100, cuda-ipc | 3.160 (0.790)<br>P 3x A100 / D 1x A100, cuda-ipc | 3.160 (0.790)<br>P 3x A100 / D 1x A100, cuda-ipc | 3.160 (0.790)<br>P 3x A100 / D 1x A100, cuda-ipc | 3.160 (0.790)<br>P 3x A100 / D 1x A100, cuda-ipc |
| burstgpt | 0.163 (0.082)<br>P 1x A100 / D 1x A100, cuda-ipc | 0.341 (0.114)<br>P 2x A100 / D 1x A100, cuda-ipc | 0.348 (0.087)<br>P 2x A100 / D 2x A100, cuda-ipc | 0.341 (0.114)<br>P 2x A100 / D 1x A100, cuda-ipc | 0.348 (0.087)<br>P 2x A100 / D 2x A100, cuda-ipc |
| mooncake-conv | 0.536 (0.268)<br>P 1x A100 / D 1x A100, cuda-ipc | 1.953 (0.488)<br>P 3x A100 / D 1x A100, cuda-ipc | 1.953 (0.488)<br>P 3x A100 / D 1x A100, cuda-ipc | 1.953 (0.488)<br>P 3x A100 / D 1x A100, cuda-ipc | 1.953 (0.488)<br>P 3x A100 / D 1x A100, cuda-ipc |
| mooncake-tool | 0.814 (0.407)<br>P 1x A100 / D 1x A100, cuda-ipc | 2.904 (0.726)<br>P 3x A100 / D 1x A100, cuda-ipc | 2.904 (0.726)<br>P 3x A100 / D 1x A100, cuda-ipc | 2.904 (0.726)<br>P 3x A100 / D 1x A100, cuda-ipc | 2.904 (0.726)<br>P 3x A100 / D 1x A100, cuda-ipc |

**NPU only: 1 node, 2 RNGD + 4 ATOM** — goodput req/s (카드당 req/s), 숫자 아래에 배치

| 트레이스 | topology (shm) | optimal, per card | optimal, max goodput | distserve | hexgen2 |
|---|--:|--:|--:|--:|--:|
| azure-conv | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm | 0.813 (0.406)<br>P 1x RNGD / D 1x RNGD, shm |
| azure-code | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm | 0.943 (0.472)<br>P 1x RNGD / D 1x RNGD, shm |
| burstgpt | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.025 (0.013)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-conv | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm | 0.563 (0.281)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-tool | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm |

**Mixed: 1 node, 2 A100 + 2 RNGD + 4 ATOM** — goodput req/s (카드당 req/s), 숫자 아래에 배치

| 트레이스 | topology (shm) | optimal, per card | optimal, max goodput | distserve | hexgen2 |
|---|--:|--:|--:|--:|--:|
| azure-conv | 4.202 (2.101)<br>P 1x A100 / D 1x A100, shm | **11.780 (2.945)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 7.525 (2.508), P 2x RNGD / D 1x A100_ | **11.780 (2.945)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 7.525 (2.508), P 2x RNGD / D 1x A100_ | 4.218 (2.109)<br>P 1x A100 / D 1x A100, cuda-ipc | 11.935 (2.984)<br>P 2x RNGD+1x A100 / D 1x A100, shm |
| azure-code | 1.038 (0.519)<br>P 1x A100 / D 1x A100, shm | **3.019 (0.755)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 2.087 (0.696), P 2x RNGD / D 1x A100_ | **3.019 (0.755)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 2.160 (0.540), P 2x A100 / D 2x RNGD_ | 1.040 (0.520)<br>P 1x A100 / D 1x A100, cuda-ipc | 3.070 (0.767)<br>P 2x RNGD+1x A100 / D 1x A100, shm |
| burstgpt | 0.163 (0.081)<br>P 1x A100 / D 1x A100, shm | **0.289 (0.097)**<br>P 1x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 0.163 (0.082), P 1x A100 / D 1x A100, cuda-ipc_ | **0.362 (0.091)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 0.243 (0.081), P 2x RNGD / D 1x A100_ | 0.163 (0.082)<br>P 1x A100 / D 1x A100, cuda-ipc | 0.363 (0.091)<br>P 2x RNGD+1x A100 / D 1x A100, shm |
| mooncake-conv | 0.505 (0.253)<br>P 1x A100 / D 1x A100, shm | **1.930 (0.482)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 1.488 (0.496), P 2x RNGD / D 1x A100_ | **1.930 (0.482)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 1.488 (0.496), P 2x RNGD / D 1x A100_ | 0.536 (0.268)<br>P 1x A100 / D 1x A100, cuda-ipc | 2.196 (0.549)<br>P 2x RNGD+1x A100 / D 1x A100, shm |
| mooncake-tool | 0.802 (0.401)<br>P 1x A100 / D 1x A100, shm | **2.921 (0.730)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 2.102 (0.701), P 2x RNGD / D 1x A100_ | **2.921 (0.730)**<br>P 2x RNGD+1x A100 / D 1x A100, shm<br>_one type per role: 2.102 (0.701), P 2x RNGD / D 1x A100_ | 0.950 (0.475)<br>P 1x RNGD / D 1x RNGD, shm | 3.151 (0.788)<br>P 2x RNGD+1x A100 / D 1x A100, shm |

이 프로파일로 보면(RNGD·ATOM·`shm`은 측정, A100은 일부 추정):

- **GPU 전용**: 보정으로 바뀐 것이 없습니다. `optimal`(per card)과 `distserve`, `optimal`(max goodput)과 `hexgen2`가 모든 트레이스에서
  같은 배치를 고르고, topology의 고정 1:1 분할은 카드당 1.4–1.8배 뒤처집니다.
- **NPU 전용**: `hexgen2`를 포함해 모든 정책이 RNGD/RNGD를 고릅니다. 측정한 ATOM decode(토큰당 108 ms)로는 어떤 ATOM decode 인스턴스도
  TPOT SLO를 못 지키므로 max-flow 탐색도 더 이상 ATOM을 더하지 않습니다. goodput은 보정 전 표의 2.4–26배(Azure 대화 0.336 → 0.813 req/s, BurstGPT는 0.025로 그대로)이며,
  측정한 RNGD prefill과 `shm` 적재 덕분입니다. Mooncake 행은 S=512 너머의 외삽입니다.
- **혼합**: 측정한 RNGD prefill(12K tok/s, A100 추정 10K)이 선택을 바꿉니다. `optimal`은 이제 Azure 대화·코드와 Mooncake 둘에서 카드당과
  max goodput 모두 RNGD 2장 + A100 1장 prefill, A100 decode를 고릅니다(Azure 대화 11.78 req/s, 동종 A100 쌍인 `distserve`의 2.8배). 역할당
  한 종류로는 RNGD 2장 prefill + A100 1장 decode(7.53)입니다. `hexgen2`는 ATOM decode 없이 같은 4카드 배치에 이르고 `optimal`과 1–14 %
  차이입니다(11.94 대 11.78 req/s, Mooncake 대화 2.20 대 1.93). 남은 차이는 공유 prefill 큐와 `optimal`의 고정 가중 분할의 차이입니다.
  **혼합 노드에서는 이제 역할 내 혼합이 카드당 선택도 바꿉니다**(보정 전에는 그대로였음). 다른 카드 집합은 그대로입니다.
- 혼합 행은 RNGD → A100 KV를 `shm`으로 가정하는데 이를 제공하는 ai-rm 전송은 아직 없고, A100 수치는 일부 추정입니다. 한 프로파일 표
  아래의 배치 논리 비교이지 하드웨어 비교가 아닙니다.
- W6의 "GPU 전용 기준선 대비 optimal이 topology보다 카드당 우수"는 시뮬레이션에서 성립합니다. A100 4장에서 DistServe 방식 탐색과
  같거나 낫고, 모든 트레이스에서 topology보다 낫습니다.

## ✅ 검증

- 테스트 90개(topology, optimal과 역할 내 혼합, PD 풀 옆의 aggregated `serve` 풀, 재조정과 예측기, 상태·재배치, 적용, 시뮬레이터와 에피소드 재생, 기준선, 0.1과 같은 바이트의 문서), rm-core v0.1.2로
  `rm_core.conformance airm.placements topology optimal` PASS, CI에서 둘 다 실행.
- 실제 클러스터 읽기 전용 dry-run(2026-10-19, topology): shm 풀은 `etri-001/furiosa:0` + `furiosa:1`(end-to-end 실행에서 손으로 고정했던 배치와
  같음, cordon된 노드는 제외), p2p 풀은 RNGD 0 + ATOM 0, 1.
- RNGD+ATOM 노드에서 실제 실행(2026-10-19, [기준선](../../docs/ko/baselines.md)): `optimal`(`examples/optimal.yaml`, budget 6)이
  generation 2(prefill RNGD 2장, decode RNGD 1장, `shm`)를 쓰고, `--apply`가 annotation된 rngd-pd Deployment를 patch했습니다(replicas
  2와 1, node affinity, `accelerator-ids`). 파드는 결정한 노드에 결정한 카드 수로 올라왔고, PD 경로는 llm-d 게이트웨이를 거쳐
  `pd-smoke`를 통과했습니다. 어느 카드를 받는지는 여전히 device plugin이 정합니다. 보정한 프로파일로는 prefill 1장 / decode 2장을
  골랐고(generation 3), `--apply`가 Deployment를 그에 맞췄으며, 이 배치는 두 트레이스 모두 모든 요청에서 SLO를 지켰습니다.
- RNGD+ATOM 노드에서 rngd-pd 게이트웨이의 `airm_*` 지표로 `--rebalance --apply`를 실제로 돌림(2026-10-19): 한 시간에 P:D가 세 번
  바뀌었고 매번 부하가 걸린 역할 쪽으로 움직였습니다. 대화에서는 옳았고(달성률 약 10 % → 85 %) 코드 ×3에서는 틀렸습니다(63–68 % →
  45 %, 카드를 내준 역할의 손실을 모델링하지 않음). [기준선](../../docs/ko/baselines.md#w5-pd-재조정기-실제-실행) 참고.
- 예측 규칙(2026-10-20): 실제 실행의 신호에서 선형 규칙이 코드 ×3 이동을 한 자리에서는 유지하고(2:1은 decode 포화로 예측, 측정
  3.1–3.8), 대화 이동은 그대로 합니다. `python -m rm_controller.sim --episode`(W5의 교대 부하, 실제 Azure 도착 시각)로 재생하면
  선형 규칙은 8번 움직이며 코드 평균 74–76 %, 대화 56 %였고, 예측 규칙은 1P+2D를 유지했습니다(78 %, 99 %). 2P+1D에서 시작하면
  대화 이동만 했습니다. 실제 재확인(2026-10-19, 같은 부하와 카드, 2P+1D에서 50분): 대화 ×2 4분째에 2:1 → 1:2 한 번 이동하고,
  두 코드 ×3 구간 내내 1P+2D를 유지해 코드 실행마다 77–81 %를 달성했습니다(선형 규칙의 이동 뒤에는 40–45 %).
  [기준선](../../docs/ko/baselines.md#예측-규칙) 참고.

## 🗺 로드맵

- [x] 실시간 부하(대기열, TTFT/TPOT)와 워크로드 모양([트레이스](../../docs/ko/workload-traces.md))을 선택에 반영 (`--rebalance`, `optimal`)
- [x] 결정을 따르는 서빙 Deployment (`--apply`). chart가 `accelerator-ids`로 카드를 고정하는 일은 남음
- [x] `airm-placement` 형식을 rm-core 프로토콜에 규범화 (§5.4, v0.1.2)
- [x] 이미지(`ghcr.io/ai-computing/rm-controller`, [`Dockerfile`](Dockerfile))와 umbrella chart [`charts/ai-rm`](../../charts/ai-rm)의 Deployment
- [x] 실제 기준선에서 측정한 RNGD·ATOM decode 프로파일
- [ ] ATOM prefill·`p2p`·A100 측정, FASOP NPU 비용 모델(aicomp #50)
- [x] 역할 안에 장치 종류 혼합(`mixed_roles`), 종류별 가중치로 라우팅
- [ ] 종류를 넘는 공유(작업 보존) prefill 라우팅을 모델과 게이트웨이에, 종류 쌍마다 KV 링크
- [ ] `optimal`이 노드를 넘을 수 있도록 노드 간 KV 전송
- [x] `optimal`, `--apply`를 실제 클러스터에서 실행
- [x] `--rebalance`를 실제 클러스터에서 실행 ([기준선](../../docs/ko/baselines.md#w5-pd-재조정기-실제-실행))
- [x] 재조정기: 이동 뒤 두 역할의 압력을 예측(프로파일, admission 비용)하고, 더 나은 분할이 없으면 유지
- [ ] 재조정기: 이동 뒤 측정한 달성률로 이동을 검증(나빠졌으면 되돌림)

## 📄 라이선스

[ai-rm](../../LICENSE)과 같은 BSD-3-Clause.
