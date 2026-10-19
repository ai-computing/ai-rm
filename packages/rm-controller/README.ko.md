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

정책 `optimal`, entry point `airm.placements:optimal`(spec의 `placement: optimal`). prefill 장치 종류, decode 장치 종류, 각각의
인스턴스 수, 노드, KV 링크를 골라 **SLO를 지키는 카드당 goodput**을 최대로 합니다. 입력:

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
| 제약 | 역할마다 장치 종류 하나(역할별 Deployment 하나), 인스턴스의 카드는 한 노드, host 범위 링크(`shm`, `p2p`)는 풀을 한 노드에, 역할별 인스턴스 ≥ 1, 카드 ≤ budget |
| 목적 | 도착률 없음: 카드당 goodput 최대, 다음 goodput. 도착률 있음: 감당하는 최소 카드. `objective: goodput`: goodput 최대 |
| 탐색 | 링크 × 노드 × 종류² × 인스턴스 수 완전 열거 (카드 32장에서 수천 후보) |
| 대체 | 빈 카드 종류에 프로파일이 없거나, `loopback`, 모르는 전송, SLO를 지키는 후보 없음 → spec의 개수로 `topology`, 이유에 기록. 선택지가 하나뿐인 풀은 topology와 같은 결과 |

`kv_transport: auto`는 구현된 링크 중에서 고릅니다. `p2p`는 검증된 RNGD → ATOM에만 제시합니다.
**프로파일 수치는 일부 추정치입니다.** 파일에 측정(measured)·유도(derived)·추정(estimate)을 표시했으며, FASOP NPU 비용 모델
([aicomp #50](https://github.com/ai-computing/aicomp/issues/50))이나 측정 sweep으로 바꿀 예정입니다.

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
profiles: my-profiles.yaml             # optimal / rebalance / apply: 처리량 표 (기본: 패키지 내장)
pools:
  - pool: ...
    kv_transport: auto                 # optimal 전용: 구현된 링크 중 선택
    workload: {trace: azure-conv}      # 또는 {mean_input_tokens, mean_output_tokens, rate_rps, peak_ratio}
    budget: 6                          # 이 풀의 최대 카드 수 (optimal, rebalance)
    rebalance: {metrics: http://<pod>:8000/metrics, band: 0.2, hold: 3, cooldown_s: 300}
```

예시: [`examples/spec.yaml`](examples/spec.yaml)(shm으로 RNGD+RNGD, rebalance 포함),
[`examples/hetero-p2p.yaml`](examples/hetero-p2p.yaml)(같은 호스트 P2P로 RNGD prefill, ATOM ×2 decode),
[`examples/optimal.yaml`](examples/optimal.yaml)(optimal, `kv_transport: auto`, budget 6).

## 🔁 제어 루프

**재배치 (W5).** 아직 유효한 결정은 유지하므로, 노드가 복구돼도 실행 중인 풀을 옮기지 않습니다. 배치된 카드가 사라지거나
비정상이 되거나 그 노드가 스케줄 불가가 되면 그 카드를 잃은 역할만 다시 배치합니다(KV 경로가 host-local이거나 인스턴스가 여러
카드면 같은 노드에서). 두 역할 모두 잃으면 풀을 새로 배치합니다. 바뀐 결정이 `generation`을 올리고, `reason`에 잃은 카드와
이유(`gone`, `unhealthy`, `node … unschedulable`)가 남습니다.

**P:D 재조정 (W5, `--rebalance`).** `rebalance:` 절이 있는 풀마다 카드 `budget`을 prefill과 decode 인스턴스로 나눌 목표를 계산합니다.

- 지표로: URL이나 파일의 Prometheus 텍스트(하나, 또는 `{prefill: …, decode: …}`). 역할별 `vllm:num_requests_waiting`
  (`role` / `llm-d.ai/role` 레이블), `vllm:time_to_first_token_seconds`·`vllm:time_per_output_token_seconds` 히스토그램
  (읽기 사이 구간), 또는 게이트웨이의 `airm_ttft_p90_ms` / `airm_tpot_p90_ms`. Optimus Prime이
  [aicomp #45](https://github.com/ai-computing/aicomp/issues/45)로 내보낼 이름입니다. 역할별 압력 = max(지연/SLO, 인스턴스당 대기/2),
  필요 인스턴스 = 현재 × 압력;
- 지표가 없으면 워크로드의 트레이스 통계와 프로파일로(peak 도착률 ÷ 인스턴스 하나의 용량).

히스테리시스: 두 압력이 모두 1 이하면 그대로 둡니다. 목표는 P:D 비율을 `band`보다 크게 바꿔야 하고, `hold`번 연속 제안되어야
하며, 마지막 변경 후 `cooldown_s`가 지나야 합니다(`--once`는 hold 1, cooldown 없음). 분할이, 따라서 결정이 바뀔 때만 새
generation을 씁니다. `topology`에서는 분할이 역할별 개수가 되고, `optimal`에서는 인스턴스 수를 고정한 채 종류·노드·링크를 고릅니다.

**적용 모드 (HUB-11, `--apply`).** `airm.ai-computing.io/pool: <pool>`과 `airm.ai-computing.io/role: prefill|decode|serve`
annotation이 있는 Deployment에 merge patch를 보냅니다: `spec.replicas`(카드 수 ÷ 인스턴스당 카드), 레이블
`airm.ai-computing.io/<vendor>.<model>`과 결정의 노드(`kubernetes.io/hostname`)에 대한 필수 node affinity, 장치를 고정하는
chart를 위한 pod template annotation `airm.ai-computing.io/accelerator-ids`. 이미 일치하는 Deployment는 patch하지 않고,
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
| azure-conv | 0.336 (0.168) | 0.046 (0.015) | 0.336 (0.168)<br>P 1x RNGD / D 1x RNGD, shm | 0.336 (0.168)<br>P 1x RNGD / D 1x RNGD, shm |
| azure-code | 0.133 (0.067) | 0.000 (0.000) | 0.133 (0.067)<br>P 1x RNGD / D 1x RNGD, shm | 0.133 (0.067)<br>P 1x RNGD / D 1x RNGD, shm |
| burstgpt | 0.026 (0.013) | 0.004 (0.001) | 0.026 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.026 (0.013)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-conv | 0.000 (0.000) | 0.000 (0.000) | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-tool | 0.037 (0.018) | 0.000 (0.000) | 0.037 (0.018)<br>P 1x RNGD / D 1x RNGD, shm | 0.037 (0.018)<br>P 1x RNGD / D 1x RNGD, shm |

**2 nodes: 2 x (2 RNGD + 4 ATOM)** — goodput req/s (카드당 req/s), optimal은 숫자 아래에 배치

| 트레이스 | topology RNGD/RNGD shm | topology RNGD/ATOM×2 p2p | optimal (per card) | optimal (max goodput) | optimal (max goodput, planned tcp) |
|---|--:|--:|--:|--:|--:|
| azure-conv | 0.336 (0.168) | 0.046 (0.015) | 0.336 (0.168)<br>P 1x RNGD / D 1x RNGD, shm | 0.336 (0.168)<br>P 1x RNGD / D 1x RNGD, shm | 0.730 (0.182)<br>P 3x RNGD / D 1x RNGD, tcp, 2 nodes |
| azure-code | 0.133 (0.067) | 0.000 (0.000) | 0.133 (0.067)<br>P 1x RNGD / D 1x RNGD, shm | 0.133 (0.067)<br>P 1x RNGD / D 1x RNGD, shm | 0.613 (0.153)<br>P 3x RNGD / D 1x RNGD, tcp, 2 nodes |
| burstgpt | 0.026 (0.013) | 0.004 (0.001) | 0.026 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.026 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.061 (0.015)<br>P 2x RNGD / D 2x RNGD, tcp, 2 nodes |
| mooncake-conv | 0.000 (0.000) | 0.000 (0.000) | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, shm |
| mooncake-tool | 0.037 (0.018) | 0.000 (0.000) | 0.037 (0.018)<br>P 1x RNGD / D 1x RNGD, shm | 0.037 (0.018)<br>P 1x RNGD / D 1x RNGD, shm | 0.379 (0.095)<br>P 3x RNGD / D 1x RNGD, tcp, 2 nodes |

이 프로파일로 보면:

- **노드 하나에서는 optimal이 RNGD/RNGD 풀**이며, Azure 대화와 BurstGPT에서 이종 RNGD/ATOM×2 풀보다 카드당 goodput이 약 10배입니다.
  ATOM decode는 KV 여유(가중치 옆 약 4K 토큰: 대화는 batch 2, Azure 코드·Mooncake 프롬프트 대부분은 들어가지 않음)에 묶이고,
  ATOM prefill은 TTFT SLO에 비해 느립니다.
- **노드 둘에서는 노드 간 KV 전송이 있어야만 이득**이 납니다. 아직 없습니다(표의 `tcp`는 0.5 GB/s로 추정한 계획 링크). 있으면
  goodput이 2.2배(Azure 대화)에서 10배(Mooncake tool-agent), 카드당 최대 5배이며, 대부분 길고 들쭉날쭉한 프롬프트를 위한 prefill
  서버 추가에서 옵니다.
- Mooncake 대화는 어디서도 불가능합니다(p90 프롬프트 27K 토큰 ≈ prefill 11초). optimal은 topology로 대체합니다.
- 절대값이 낮은 이유: 측정된 `shm` 경로가 0.6 GB/s(1K 토큰 프롬프트의 KV에 약 0.3초)이고, 용량을 트레이스별 60초 peak(BurstGPT
  69배)에 맞춰 잡기 때문입니다.
- `optimal`의 분석 모델은 시뮬레이션 goodput의 0.41–1.25배로 대부분 보수적입니다([컴포넌트 카드](../../docs/components/rm-controller.md)의
  "Model est." 열). 둘 다 같은 프로파일을 읽으므로 시뮬레이션은 대기열·burst·KV 적합·라우팅을 검증할 뿐, **일부 추정치인 프로파일
  수치 자체는 검증하지 않습니다**.

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
| azure-conv | 0.336 (0.168)<br>P 1x RNGD / D 1x RNGD, shm | 0.336 (0.168)<br>P 1x RNGD / D 1x RNGD, shm | 0.336 (0.168)<br>P 1x RNGD / D 1x RNGD, shm | 0.336 (0.168)<br>P 1x RNGD / D 1x RNGD, shm | 0.243 (0.061)<br>P 1x RNGD / D 1x RNGD+1x ATOM, shm |
| azure-code | 0.133 (0.067)<br>P 1x RNGD / D 1x RNGD, shm | 0.133 (0.067)<br>P 1x RNGD / D 1x RNGD, shm | 0.133 (0.067)<br>P 1x RNGD / D 1x RNGD, shm | 0.133 (0.067)<br>P 1x RNGD / D 1x RNGD, shm | 0.133 (0.067)<br>P 1x RNGD / D 1x RNGD, shm |
| burstgpt | 0.026 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.026 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.026 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.026 (0.013)<br>P 1x RNGD / D 1x RNGD, shm | 0.026 (0.004)<br>P 1x RNGD / D 1x RNGD+2x ATOM, shm |
| mooncake-conv | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>P 1x RNGD / D 1x RNGD, shm | 0.000 (0.000)<br>none feasible | 0.000 (0.000)<br>none feasible |
| mooncake-tool | 0.037 (0.018)<br>P 1x RNGD / D 1x RNGD, shm | 0.037 (0.018)<br>P 1x RNGD / D 1x RNGD, shm | 0.037 (0.018)<br>P 1x RNGD / D 1x RNGD, shm | 0.037 (0.018)<br>P 1x RNGD / D 1x RNGD, shm | 0.037 (0.018)<br>P 1x RNGD / D 1x RNGD, shm |

**Mixed: 1 node, 2 A100 + 2 RNGD + 4 ATOM** — goodput req/s (카드당 req/s), 숫자 아래에 배치

| 트레이스 | topology (shm) | optimal, per card | optimal, max goodput | distserve | hexgen2 |
|---|--:|--:|--:|--:|--:|
| azure-conv | 4.168 (2.084)<br>P 1x A100 / D 1x A100, shm | 4.218 (2.109)<br>P 1x A100 / D 1x A100, cuda-ipc | 4.218 (2.109)<br>P 1x A100 / D 1x A100, cuda-ipc | 4.218 (2.109)<br>P 1x A100 / D 1x A100, cuda-ipc | 6.244 (0.780)<br>P 2x RNGD+1x A100 / D 1x A100+2x ATOM, shm |
| azure-code | 1.034 (0.517)<br>P 1x A100 / D 1x A100, shm | 2.114 (0.705)<br>P 2x A100 / D 1x RNGD, shm | 2.145 (0.536)<br>P 2x A100 / D 2x RNGD, shm | 1.040 (0.520)<br>P 1x A100 / D 1x A100, cuda-ipc | 2.145 (0.536)<br>P 2x A100 / D 2x RNGD, shm |
| burstgpt | 0.162 (0.081)<br>P 1x A100 / D 1x A100, shm | 0.163 (0.082)<br>P 1x A100 / D 1x A100, cuda-ipc | 0.163 (0.082)<br>P 1x A100 / D 1x A100, cuda-ipc | 0.163 (0.082)<br>P 1x A100 / D 1x A100, cuda-ipc | 0.258 (0.032)<br>P 2x RNGD+1x A100 / D 1x A100+2x ATOM, shm |
| mooncake-conv | 0.389 (0.195)<br>P 1x A100 / D 1x A100, shm | 1.126 (0.282)<br>P 2x A100 / D 2x RNGD, shm | 1.126 (0.282)<br>P 2x A100 / D 2x RNGD, shm | 0.536 (0.268)<br>P 1x A100 / D 1x A100, cuda-ipc | 1.126 (0.282)<br>P 2x A100 / D 2x RNGD, shm |
| mooncake-tool | 0.763 (0.382)<br>P 1x A100 / D 1x A100, shm | 1.692 (0.564)<br>P 2x A100 / D 1x RNGD, shm | 1.703 (0.426)<br>P 2x A100 / D 2x RNGD, shm | 0.814 (0.407)<br>P 1x A100 / D 1x A100, cuda-ipc | 1.703 (0.426)<br>P 2x A100 / D 2x RNGD, shm |

이 프로파일로 보면:

- **GPU 전용**: `optimal`(per card)과 `distserve`는 모든 트레이스에서 같은 배치를, `optimal`(max goodput)과 `hexgen2`도 같은 배치를
  고릅니다. 동종 GPU에서는 P:D 분할 말고는 탐색할 것이 거의 없고 둘 다 이를 맞힙니다. topology의 고정 1:1 분할은 카드당 1.4–1.8배,
  전체 goodput 2–3.6배 뒤처집니다.
- **NPU 전용**: 모든 정책이 RNGD/RNGD를 고르고, `hexgen2`만 Azure 대화와 BurstGPT에서 흐름 용량을 늘린다는 이유로 ATOM decode를
  더합니다. 시뮬레이션에서는 이것이 goodput을 낮춥니다(max-flow 목적은 TTFT 대기와 느리고 KV에 묶인 ATOM decode를 보지 않음).
  이 노드에서 자체 추정은 시뮬레이션 값의 1.8–6배입니다.
- **혼합**: `optimal`은 A100 prefill과 RNGD decode를 짝지어 `distserve`보다 2.0–2.1배(Azure 코드, Mooncake) 높습니다. 동종 탐색으로는
  만들 수 없는 배치입니다. `hexgen2`는 세 종류를 역할에 섞어 Azure 대화와 BurstGPT에서 전체 goodput이 가장 높지만(6.24 대 4.22
  req/s, 0.258 대 0.163), 카드당 goodput은 2.6–2.7배 낮습니다. `optimal`은 역할마다 한 종류(역할마다 Deployment 하나)라 그 배치를
  표현하지 못합니다.
- W6의 "GPU 전용 기준선 대비 optimal이 topology보다 카드당 우수"는 시뮬레이션에서 성립합니다. A100 4장에서 DistServe 방식 탐색과
  같거나 낫고, 모든 트레이스에서 topology보다 낫습니다. 모든 행이 한 프로파일 표를 쓰므로 하드웨어가 아니라 배치 논리를 비교합니다.

## ✅ 검증

- 테스트 60개(topology, optimal, 재조정, 상태·재배치, 적용, 시뮬레이터, 기준선, 0.1과 같은 바이트의 문서), rm-core v0.1.2로
  `rm_core.conformance airm.placements topology optimal` PASS, CI에서 둘 다 실행.
- 실제 클러스터 읽기 전용 dry-run(2026-10-19, topology): shm 풀은 `npu-node-1/furiosa:0` + `furiosa:1`(end-to-end 실행에서 손으로 고정했던 배치와
  같음, cordon된 노드는 제외), p2p 풀은 RNGD 0 + ATOM 0, 1.
- 아직 클러스터에서 돌리지 않음: `optimal`, `--rebalance`(aicomp #45의 vLLM 지표나 게이트웨이 `airm_*` 필요), `--apply`(annotation된
  Deployment 필요). 가짜 클러스터 IO와 시뮬레이터로만 검증했습니다.

## 🗺 로드맵

- [x] 실시간 부하(대기열, TTFT/TPOT)와 워크로드 모양([트레이스](../../docs/ko/workload-traces.md))을 선택에 반영 (`--rebalance`, `optimal`)
- [x] 결정을 따르는 서빙 Deployment (`--apply`). chart가 `accelerator-ids`로 카드를 고정하는 일은 남음
- [x] `airm-placement` 형식을 rm-core 프로토콜에 규범화 (§5.4, v0.1.2)
- [x] 이미지(`ghcr.io/ai-computing/rm-controller`, [`Dockerfile`](Dockerfile))와 umbrella chart [`charts/ai-rm`](../../charts/ai-rm)의 Deployment
- [ ] 추정치 대신 측정 프로파일 (FASOP NPU 비용 모델, aicomp #50), (GPU 기준선용 A100 추가, 일부 추정)
- [ ] `optimal`이 노드를 넘을 수 있도록 노드 간 KV 전송
- [ ] `optimal`, `--rebalance`, `--apply`를 실제 클러스터에서 실행

## 📄 라이선스

[ai-rm](../../LICENSE)과 같은 BSD-3-Clause.
