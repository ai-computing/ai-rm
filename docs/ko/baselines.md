# RNGD+ATOM 노드의 같은 예산 기준선

[문서](README.md) · [English](../baselines.md) · [end-to-end 실행](e2e.md) · [로드맵](roadmap.md)

로드맵 W5(컨트롤러가 서빙 파드를 배치하고 옮김, P:D 재조정기), W6(`optimal` 정책의 측정 프로파일), W7(벤더 엔진을 포함해 에너지까지 잰
같은 예산 기준선)의 실제 증빙입니다. 2026-10-19, RNGD와 ATOM 카드를 함께 가진 노드에서 실행했습니다(시작 시 RNGD 3장·ATOM 4장이 비어 있었고, RNGD가
있는 다른 노드는 cordon 상태). W2 절(두 모델 풀 동시 서빙, `tcp`로 노드 간 KV)은 같은 날 저녁 같은 노드에서 돌렸고, 두 번째
RNGD 노드는 여전히 cordon 상태였습니다. 2026-10-20에는 NPU 간 실행을 위해 두 번째 RNGD 노드를 열었습니다
([아래](#두-번째-npu-노드-2026-10-20)).

**범위.** Llama-3.1-8B-Instruct, 현재 rngd-pd가 컴파일한 그래프(S=512), 노드 하나, KV는 `shm`. 실제 트레이스 두 개를 S=512가 처리할
수 있는 요청으로 잘랐고, 실행당 요청 수백 개, 칸마다 한 번씩 실행했습니다. 이 엔진 세대의 기준선이며 하드웨어 성능 주장이
아닙니다.

## 요약

| | 결과 |
|---|---|
| W5 | `rm-controller` `optimal`이 `airm-placement`를 쓰고 `--apply`가 rngd-pd Deployment를 그에 맞췄습니다. 두 번 했습니다(기존 프로파일로 prefill 2 / decode 1 RNGD, 보정한 프로파일로 prefill 1 / decode 2). 파드는 결정한 노드에 결정한 카드 수로 떴고, llm-d 게이트웨이를 거친 `pd-smoke`가 32/32 통과했습니다. 파드가 어느 카드를 받는지는 결정이 아니라 device plugin이 정합니다. |
| W7 | **카드 2장:** 복제(카드 한 장짜리 `solo` 인스턴스 2개)가 카드당 goodput에서 PD 1P+1D를 이깁니다. Azure 대화 1.52 req/s에서 SLO 달성 100 %(카드당 0.75 req/s), 1P+1D는 87.7 %. 줄당 토큰(tok/J)은 1P+1D가 가장 높습니다(1.17 대 0.76). **카드 3장:** 보정한 `optimal` 배치 PD 1P+2D가 두 트레이스 모두 모든 요청에서 SLO를 지켰고(`solo` ×3과 같음) tok/J는 그 1.2배입니다. 기존 프로파일의 선택 2P+1D는 93.6 %와 77.5 %. **RNGD prefill → ATOM decode는 TPOT SLO 100 ms를 지킬 수 없습니다**: ATOM decode 그래프가 토큰당 108 ms입니다. |
| W6 | 프로파일 표가 2배 이상 틀렸습니다. 400 토큰 프롬프트의 RNGD prefill은 예전 유도값의 220 ms가 아니라 100 ms, batch 그래프의 RNGD decode는 batch와 무관하게 토큰당 30 ms(17–24 아님), ATOM decode는 카드 한 장에서 108 ms(두 장에서 40–52 아님). `profiles.yaml`을 측정값으로 바꾸자 `optimal`의 선택이 2P+1D에서 1P+2D로 바뀌었고, 클러스터에서도 1P+2D가 더 좋았습니다(100 % 대 93.6 %, 77.5 %). |
| W7 벤더 | **furiosa-llm 2026.3.0 집약 서빙**(replica 하나에 카드 한 장, FuriosaAI가 미리 컴파일한 Llama-3.1-8B)이 카드 2장과 3장 모두 두 트레이스의 모든 요청에서 SLO를 지켰습니다. 카드당 goodput(제공 부하에 묶임)과 tok/J(0.74 대 0.76)는 `solo`와 같고, TPOT p90은 17–19 ms로 rngd-pd의 30–69 ms보다 낮습니다. **furiosa-llm에는 PD 모드가 없습니다**(disaggregation 옵션도, KV 전송 코드도 없고 FuriosaAI llm-d 가이드도 미지원으로 적음). 그래서 벤더 PD 행은 없습니다. |
| W7 반복 | 대화 ×1을 배치마다 3–5번 다시 돌렸습니다([아래](#반복-실행-2026-10-2021-43)). **PD 1P+1D**는 98.0, 25.5, 94.3, 93.4, 96.7 %: 용량의 경계에서 돌고, 다섯 번 중 한 번은 엔진이 취소할 수 없는 backlog로 무너졌습니다. tok/J는 모든 실행에서 1.06(단일 실행은 1.17)으로 여전히 `solo` ×2의 1.3배, furiosa-llm ×2의 1.5배입니다. **`solo` ×2**: 97.1 ± 4.9 %, 카드당 0.73. **furiosa-llm ×2**: 모든 실행 100 %, 카드당 0.76. **PD 1P+2D**: 모든 실행 100 %, 0.67 tok/J. 단일 실행의 순서는 유지되지만 87.7 % 칸은 1P+1D를 설명하지 못합니다. 새로 뜬 rngd-pd 파드에는 유휴 측정 워밍업이 필요합니다: `pd-smoke`만 하면 1P+1D가 7 %로 떨어졌습니다. 같은 예산의 A100 행은 돌리지 못했습니다: 다른 프로젝트가 작업 내내 A100을 쓰고 있었습니다. |
| W5 재조정기 | 게이트웨이 `airm_*` 지표를 읽는 `rm-controller --rebalance --apply`가 한 시간에 P:D를 세 번 바꿨고, 매번 부하가 걸린 역할 쪽이었습니다(generation 5–7). 대화 ×2에서 decode로 카드를 옮기자 달성률이 약 10 %에서 85 %로 올랐습니다. 코드 ×3에서 prefill로 옮기자 63–68 %에서 45 %로 내려갔습니다. 규칙이 카드를 내준 역할의 손실을 모델링하지 않기 때문입니다. 예측 규칙(이동 뒤 두 역할을 예측)은 50분 실제 재확인에서 대화 이동만 하고 코드 ×3 동안 1P+2D를 유지했습니다(77–81 %). |
| W2 멀티 풀 | 두 모델을 겹치지 않는 카드에서 동시에 서빙하고 둘 다 `rm-controller`가 배치했습니다(`--apply`, PD 풀과 aggregated `serve` 풀). Llama-3.1-8B rngd-pd 1P+1D는 옆에서 Qwen3-4B(furiosa-llm, 카드 한 장)가 같은 부하를 받는 동안 Azure 대화 ×1의 97.6 %, 단독으로 98.0 %에서 SLO를 지켰고 Qwen은 둘 다 100 %. 한 풀의 spec만 바꿔(Llama decode RNGD → ATOM) 다시 실행하자 그 풀의 Deployment만 patch됐고 Qwen 파드는 손대지 않은 채 계속 돌았습니다. |
| W2 노드 간 KV | rngd-pd의 새 `tcp` 전송이 실제 prefill KV(요청당 67 MB)를 RNGD prefill 파드에서 CPU 노드의 relay 파드를 거쳐 RNGD decode 파드로 옮겼습니다. blob 2,112/2,112개가 바이트 단위로 같고, 출력 32/32개가 `shm`과 같습니다. 속도는 NPU 노드의 1 GbE 링크가 정합니다: 요청당 0.08–0.09 GB/s, 동시 8개면 방향마다 0.117 GB/s, 67 MB 구간마다 약 0.8초. `profiles.yaml`의 `tcp`는 이제 측정값(0.08 GB/s, 구현됨)이고, 그 값으로는 2노드 시뮬레이터 행이 한 노드보다 나아지지 않습니다(0.15–0.25 GB/s부터 나아짐). **두 NPU 노드 사이 NPU 간 전송(2026-10-20):** 한 NPU 노드의 RNGD prefill, 두 번째 NPU 노드의 RNGD decode, `tcp` 서버는 decode 옆. blob 2,112/2,112개가 바이트 단위로 같고 출력 32/32개가 `shm`과 같습니다. 링크를 건너는 것은 push뿐이고(요청당 p50 758 ms), decode의 로컬 pull은 세 번째 노드 relay를 거칠 때의 816 ms 대신 242 ms입니다. Azure 대화 ×0.5: SLO 달성률 **96.7 %**(TTFT p90 1.67초, TPOT p90 40 ms). relay를 거친 실행은 89.2 %, 한 노드 `shm`은 100 %입니다. |
| 발견 | rngd-pd 게이트웨이의 `airm_tpot_p90_ms`는 엔진 step이라 decode 대기를 보지 못했습니다([rngd-pd#7](https://github.com/ai-computing/rngd-pd/pull/7)). rm-bench 트레이스 프롬프트는 우연히 prefix를 공유했고(서로 다른 문장 72개), prefix cache가 이를 이용했습니다(여기서 고침). rngd-pd가 할당받은 카드를 호스트 번호로 불렀습니다(`npu3` → `rngd:3`, 범위 밖): [rngd-pd#5](https://github.com/ai-computing/rngd-pd/pull/5)에서 고침. `PD_PREFETCH=1`에서 continuous decode 워커는 대기 요청이 8개를 넘으면 영영 멈춥니다: [rngd-pd#4](https://github.com/ai-computing/rngd-pd/issues/4). Kubernetes 밖의 프로세스가 RNGD 카드 하나를 쓰고 있어, 그 카드를 할당받은 파드가 `EBUSY`로 실패했습니다. 두 번째 RNGD 노드에서는 호스트 프로세스가 두 카드를 모두 잡고 있는데도 device plugin과 AcceleratorProfile은 두 카드를 비어 있다고 보였습니다(allocatable 2, 할당 0). 스케줄러도 `rm-controller`도 그 사용을 볼 수 없습니다. |

## 구성

| | |
|---|---|
| 서빙 | rngd-pd `main` + [rngd-pd#5](https://github.com/ai-computing/rngd-pd/pull/5), chart `deploy/helm/rngd-pd`(kubelet 할당에서 카드를 고름, `--chip` 고정 없음) |
| RNGD prefill | `--backend rngd-full --C 512 --group 2`, bucket 32–512 |
| RNGD decode | `--backend rngd --B 8 --group 8 --sched continuous`(continuous batching, lane 8개) |
| ATOM decode | `--backend atom --B 4 --sched continuous`, artifact `decode_S512_B4_lm`(S=512로 컴파일된 최대 batch), 카드 한 장 |
| `solo` | `--role solo --C 512 --group 2 --decode-group 8 --B 8 --sched continuous`: 한 카드에서 prefill과 continuous decode. chart에 `solo` 역할이 없어 같은 이미지·마운트로 최소 Deployment(`airm-exp-solo`)를 만들고, replica N개를 targets 파일(`{model: {solo: <service>}}`)을 쓴 rngd-pd 게이트웨이 하나 뒤에 두었습니다. Service가 요청을 replica에 나눕니다 |
| furiosa-llm | `furiosaai/furiosa-llm:2026.3.0`, `serve furiosa-ai/Llama-3.1-8B-Instruct`(미리 컴파일된 artifact, 태그 `v2026.3`), replica 하나에 카드 한 장, Service 하나 뒤에 replica N개(`airm-exp-flm`), 서빙 기본값. 클라이언트 `--api completions-stream` |
| KV | `shm`(`/dev/shm` 경유), 보고한 모든 실행은 `PD_PREFETCH=0`([prefetch 실패](#prefetch를-켜면-부하에서-무너짐) 참고) |
| 부하 | rm-bench `e2e --api completions`, Azure 2023 트레이스를 처음부터 재생, 입력+출력 ≤ 511 토큰 요청만 유지(`--max-total-tokens 511`, skip 정책, `trace-*` 시나리오와 같음), 300초 일정, 동시성 64, timeout 300초 |
| 도착률 | 대화는 트레이스 속도(×1: 요청 455개, 1.52 req/s)와 그 절반(×0.5: 212개, 0.71 req/s), 코드는 트레이스 속도(×1: 222개, 0.74 req/s, 1초 안에 10 req/s 넘는 burst) |
| SLO | rm-controller 기준: 대화 TTFT p90 ≤ 2초, TPOT p90 ≤ 100 ms, 코드 TTFT p90 ≤ 4초, TPOT p90 ≤ 100 ms. 달성률은 요청별 판정 |
| 전력 | `--power prom`, Prometheus를 1초마다 조회: 파드가 할당받은 RNGD 카드의 `furiosa_npu_hw_power`(`label="rms"`), 사용 중인 ATOM 카드의 `RBLN_DEVICE_STATUS:CARD_POWER`. 카드 전력만(호스트 제외), 구성 밖의 유휴 카드는 넣지 않음 |
| 절차 | 실행마다 워커 파드를 재시작(엔진에 요청 취소가 없어 과부하 실행은 backlog를 남김, aicomp#43), 이어서 `pd-smoke` 예열과 유휴 측정 |

Goodput = 두 SLO를 모두 지킨 요청 수 ÷ 일정 시간(초), 카드당 = goodput ÷ 구성의 카드 수. tok/J = 출력 토큰 ÷ 실행 동안의 카드 에너지.

## W5: 컨트롤러가 배치하고 적용

```
rm-controller --spec examples/optimal.yaml --once --apply        # budget 6, kv_transport auto, mix azure-conv
rm-controller: 9 profiles, 2 decisions, generation 2 written; 2 deployment patch(es) applied
# decisions: prefill furiosa:0, furiosa:1; decode furiosa:3; shm; "est. 0.71 req/s (0.24/card) ... profiles partly estimated"
```

릴리스의 prefill·decode Deployment에 `airm.ai-computing.io/pool: llama8b-pd-pool`과 `role: prefill|decode`를 달았고, patch가
replicas 2와 1, 필수 node affinity(RNGD 레이블, 노드 hostname), `accelerator-ids` annotation을 넣었습니다. 파드 로그:

```
[decode]  [chip] allocated by k8s: [0] -> using rngd:0
[prefill] [chip] allocated by k8s: [1] -> using rngd:1
[prefill] [chip] allocated by k8s: [3] -> npu3, using rngd:2      # rngd-pd#5 이후. 이전에는 rngd:3, "device index out of range"
```

노드와 역할별 카드 수는 결정을 따르지만 카드 자체는 따르지 않습니다(결정은 decode에 `furiosa:3`을 적었고 device plugin은 decode에
`npu0`을 줌). 결정한 카드를 고정하려면 device plugin의 preferred-allocation hook이나 DRA가 필요합니다. rngd-pd는 이제 항상 kubelet이
할당한 카드를 쓰므로 둘이 부딪히지는 않습니다.

컨트롤러의 2P+1D 배치에서 llm-d 게이트웨이(Envoy → InferencePool → EPP → rngd-pd 게이트웨이)를 거친 `pd-smoke`:

| 실행 | TTFT p90 | TPOT p90 | tok/s | 결과 |
|---|--:|--:|--:|---|
| 2P+1D, decode B=8 continuous, prefetch 켬(이번) | 1815 ms | 59.6 ms | 84.5 | PASS, 32/32 |
| 1P+1D, decode B=1([end-to-end 실행](e2e.md)) | 2350 ms | 208 ms | 53.9 | PASS, 32/32 |

보정([W6](#보정-w6)) 후 같은 spec은 prefill 1 / decode 2를 골랐고(generation 3, `est. 1.52 req/s`), `--apply`가 prefill을 1, decode를
2로 맞췄습니다. 이 배치의 실행은 아래 표의 `PD 1P+2D`입니다.

## W5: P:D 재조정기, 실제 실행

`rm-controller --rebalance --apply`를 루프로 돌렸습니다(60초 라운드, hysteresis 기본값: band 0.2, hold 3, cooldown 300초).
대상은 `airm-e2e` rngd-pd Deployment, 예산은 RNGD 카드 3장, SLO는 TTFT p90 ≤ 2초·TPOT p90 ≤ 100 ms입니다. 입력은 rngd-pd
게이트웨이의 `airm_ttft_p90_ms` / `airm_tpot_p90_ms`(vLLM 히스토그램이 없을 때 쓰는 대체 경로, 최근 요청 512개)입니다. spec:
[`examples/rebalance-gateway.yaml`](../../packages/rm-controller/examples/rebalance-gateway.yaml). 부하는 Azure 코드 ×3(prefill
위주: 1.9 req/s, 출력 p50 14 토큰)과 Azure 대화 ×2(decode 위주: 2.3 req/s, 출력 약 119 토큰)를 번갈아 걸었고, 300초 재생을 이어
붙였습니다(`--api completions`, `PD_PREFETCH=0`). 두 도착률 모두 어떤 분할이든 카드 3장이 SLO 안에서 처리할 수 있는 양을 넘으므로,
역할마다 차례로 부하가 걸립니다.

| 시각 (UTC) | 부하 | 게이트웨이 TTFT / TPOT p90 | 압력 P / D | 결정 |
|---|---|--:|--:|---|
| 15:43 | 1P+2D(generation 4)에서 코드 ×3 시작 | 1,590 → 5,372 ms / 47 ms | 2.69 / 0.47 | 목표 2:1, 3 라운드 유지 |
| 15:51 | | 5,769 ms / 47 ms | 2.88 / 0.47 | **generation 5: P:D 1:2 → 2:1**, Deployment 두 개 patch |
| 16:09 | 2P+1D에서 대화 ×2 시작 | 815 ms / 159 → 557 ms | 0.25 / 5.57 | 목표 1:2, 3 라운드 유지 |
| 16:13 | | 326 ms / 557 ms | 0.25 / 5.57 | **generation 6: P:D 2:1 → 1:2** |
| 16:25 | 1P+2D에서 코드 ×3 시작 | 2,715 → 4,879 ms / 66 ms | 2.44 / 0.66 | 목표 2:1, 3 라운드 유지 |
| 16:29 | | 4,879 ms / 66 ms | 2.44 / 0.66 | **generation 7: P:D 1:2 → 2:1** |
| 16:31–16:40 | 2P+1D에서 코드 ×3 | 4,055–4,800 ms / 314–378 ms | 2.0–2.4 / 3.1–3.8 | 목표 2:1(두 역할 모두 1 초과, 2:1의 최악 need가 더 낮음), 변화 없음 |

변경은 부하가 바뀐 뒤 3.5–8분 안에 일어났습니다(라운드 세 번 일치, 요청 512개 창이 바뀌는 시간). 새 파드는 patch 약 2분 뒤부터
서빙했습니다. 300초 재생별 클라이언트 관점(rm-bench, 같은 SLO. 실행 중 분할이 바뀌면 없어지는 파드의 처리 중 요청을 잃습니다):

| 부하 | 분할 | SLO 달성률 | TTFT p90 | TPOT p90 | Goodput req/s |
|---|---|--:|--:|--:|--:|
| 대화 ×2 | 2P+1D(이동 없음: 지표가 못 봄, 아래 참고) | 7.7 % | 50.3초 | 1,089 ms | 0.17 |
| 대화 ×2 | 실행 중 2P+1D → 1P+2D | 10.7 % | 42.8초 | 525 ms | 0.25 |
| 대화 ×2 | **1P+2D** | **85.1 %, 85.5 %** | 447 ms, 440 ms | 128 ms, 134 ms | **1.95, 1.96** |
| 코드 ×3 | **1P+2D**(이동 전) | **62.9 %, 68.4 %** | 5.8초, 5.0초 | 69 ms, 67 ms | **1.22, 1.32** |
| 코드 ×3 | 실행 중 1P+2D → 2P+1D | 40.0 %, 41.2 % | 5.4초, 4.2초 | 337 ms, 366 ms | 0.77, 0.79 |
| 코드 ×3 | 2P+1D(이동 후) | 44.8 %, 45.5 % | 4.5초, 4.6초 | 334 ms, 336 ms | 0.86, 0.87 |

- **분할이 부하 구성을 따라갑니다.** 기본 hysteresis로 한 시간에 세 번, 매번 부하가 걸린 역할 쪽으로 바뀌었고(generation 5, 6, 7),
  한 구간 안에서는 오가지 않았습니다.
- **대화: 옳은 이동.** decode로 카드를 옮기자 같은 제공 부하에서 달성률이 약 10 %에서 85 %로, goodput이 0.2에서 1.95 req/s로 올랐습니다.
- **코드: 틀린 이동.** decode 카드를 prefill로 가져가자 TTFT p90은 약 15 % 줄었지만 TPOT p90은 다섯 배(67 → 335 ms)가 되었고,
  달성률은 63–68 %에서 45 %로 떨어졌습니다. 규칙은 카드를 내주는 역할을 지금 압력에서 선형으로 예측합니다(카드 2장에서 0.66인 decode
  → 1장이면 1.3). 실제로 1장에서는 3.1–3.8이었습니다. 답이 짧으면 decode admission마다 67 MB KV를 device lock 안에서 읽으므로
  (`PD_PREFETCH=0`), 코드 ×3의 요청을 모두 받는 decode 카드 한 장은 선형보다 훨씬 빨리 포화됩니다. 그러면 두 역할 모두 1을 넘고,
  선형 need를 비교하는 규칙은 2:1을 유지합니다. [예측 규칙](#예측-규칙)으로 고쳤습니다. 카드를 내주는 역할도 예측하므로
  여기서는 유지합니다.
- **발견: 게이트웨이 TPOT 지표가 decode 대기를 보지 못했습니다.** `airm_tpot_p90_ms`는 decode 워커의 그래프 step 중앙값(약 30 ms)이라
  요청이 lane을 기다리는 동안에도 평평했습니다. 첫 대화 구간에서 클라이언트 TPOT p90은 1,089 ms인데 지표는 30 ms였고, decode
  압력은 0.3으로 읽혀 아무것도 움직이지 않았습니다. [rngd-pd#7](https://github.com/ai-computing/rngd-pd/pull/7)에서 고쳤고(이제
  요청마다 (wall − TTFT) / (토큰 − 1), 클라이언트가 보는 값), 위의 대화 구간과 그 뒤는 이것으로 돌렸습니다. 여기서 함께 고친 것: 지표
  출처를 읽을 수 없을 때(게이트웨이가 아직 안 뜸) 컨트롤러 라운드가 실패하지 않고, 라운드마다 신호를 로그에 남깁니다.

### 예측 규칙

수정([`predict.py`](../../packages/rm-controller/rm_controller/predict.py), PR `rebalance-predict`): 재조정기는 이동 전에
`optimal`의 대기열 모델과 보정한 프로파일로 예산의 모든 분할에서 두 역할의 압력을 예측하고, 예측한 최악 역할 압력이 `margin`
(20 %)만큼 줄 때만 움직입니다. 아니면 유지하고 이유를 로그에 남깁니다. 모델에는 코드 ×3 이동이 부딪힌 것을 넣었습니다. `shm`
(프로파일의 `admit_blocking`)에서는 decode admission마다 67 MB KV 로드(1.6 GB/s로 42 ms) 동안 decode 루프가 멈추고, lane 대기는
TPOT에 들어가며, decode는 prefill이 통과시키는 만큼 받으므로 prefill 카드가 둘이면 burst가 decode 카드 한 장에 더 많이 넘어갑니다.
도착률은 현재 분할에 맞춥니다. SLO를 넘은 역할의 측정값을 모델이 재현하는 도착률이 풀의 실효 도착률이고(코드 ×3의 평균은
1.9 req/s지만 가장 바쁜 1초에 24개가 도착), 여유 있는 역할의 측정값은 그 역할의 예측 도착률에 상한을 둡니다. 지표나 워크로드
트레이스의 도착률과 평균 길이는 대체 경로입니다. hysteresis는 그대로입니다.

위 실행의 신호에서(실제처럼 spec에 `workload` 없음):

| 라운드(위 실제 실행) | 분할 | 압력 P / D | 선형 규칙 | 예측 규칙 |
|---|---|--:|---|---|
| 16:29, 코드 ×3 | 1P+2D | 2.44 / 0.66 | 2:1(카드 한 장 decode를 1.3으로 추정, 측정 3.1–3.8) | **유지**: 2:1은 P 0.12, D ∞(decode 포화)로 예측 |
| 16:13, 대화 ×2 | 2P+1D | 0.16 / 5.57 | 1:2 | **1:2**: P 0.13, D 0.33으로 예측 |
| 이동 뒤 대화 ×2 | 1P+2D | 0.22 / 1.31 | 1:2(유지) | 유지: 2:1은 D ∞ |
| 16:35, 코드 ×3 | 2P+1D | 2.2 / 3.46 | 2:1(유지) | 유지: 1:2는 P ∞(burst 때문인 TTFT를 prefill 포화에 가깝다고 읽음) |

두 부하의 트레이스 구성, 재생 구간 구성, 기본 구성 어느 것을 줘도 결정은 같습니다.

**시뮬레이션 재생**(`python -m rm_controller.sim --episode`, [`episode.py`](../../packages/rm-controller/rm_controller/episode.py)):
RNGD 3장, 재생 구간의 Azure 2023 도착 시각(코드 ×3: 300초에 579개, 가장 바쁜 1초 24개, 대화 ×2: 698개), 구간마다 300초 재생 3번,
재조정기는 60초마다 시뮬레이션 게이트웨이 지표를 읽고 실제와 같은 hysteresis를 씁니다. 이동 2분 뒤 파드가 준비되고, 옮기는 카드의
처리 중 요청은 잃습니다. 프로파일 위에 rm-bench의 동시 요청 64개, 루프 안의 KV 로드, Service로 무작위로 닿는 prefill 파드, 부하에서
유휴 프로파일의 1.5배인 prefill 시간을 넣었습니다(유휴 프로파일로는 코드 ×3 TTFT p90이 1.2초, 실제는 5.0–5.8초). 구간별 SLO 달성률:

| 실행 | 코드 ×3 | 대화 ×2 | 코드 ×3 | 대화 ×2 | 이동 |
|---|--:|--:|--:|--:|--:|
| 고정 1P+2D | 77.9 % | 99.1 % | 77.9 % | 99.1 % | – |
| 고정 2P+1D | 68.6 % | 3.0 % | 67.2 % | 3.0 % | – |
| 선형 규칙, 1P+2D에서(실제와 같음) | 74.4 % | 56.3 % | 75.8 % | 56.3 % | 8 |
| **예측 규칙, 1P+2D에서** | **77.9 %** | **99.1 %** | **77.9 %** | **99.1 %** | 0 |

| 실행 | 대화 ×2 | 코드 ×3 | 대화 ×2 | 코드 ×3 | 이동 |
|---|--:|--:|--:|--:|--:|
| 선형 규칙, 2P+1D에서 | 68.7 % | 75.6 % | 56.3 % | 75.5 % | 7 |
| **예측 규칙, 2P+1D에서** | **68.7 %** | **77.9 %** | **99.1 %** | **77.9 %** | 1(180초에 2:1 → 1:2) |

선형 규칙은 코드 이동을 하고(코드 구간마다 4분쯤 1:2 → 2:1), decode가 넘치는 것을 보고 되돌아가므로 대화 구간도 매번 틀린 분할로
시작합니다. 예측 규칙은 선형 규칙과 같은 라운드에 대화 이동을 하고 코드 이동은 하지 않습니다. prefill 배수에 대한 민감도: 1.0이면
코드 TTFT가 SLO 안이라 두 규칙 모두 코드에서 움직이지 않고 대화 이동만 합니다. 2.0이면 재생에서 코드에는 2P+1D가 더 낫고(71.9 %
대 50.6 %, 실제 실행과 반대), 예측 규칙은 거기서도 1P+2D를 유지합니다(그 이동을 놓침, 선형 규칙의 왕복은 57.5 %). CSV가 없으면
(60초 on/off burst만) 두 규칙 모두 대화 이동만 합니다.

**실제 재확인**(2026-10-19 17:37–18:30 UTC, 같은 노드·카드·Deployment, rngd-pd#7 게이트웨이, `PD_PREFETCH=0`, 위와 같은 부하,
컨트롤러 `adce9db`, 2P+1D에서 대화부터 시작):

| 실행 | 부하 | 분할 | SLO 달성률 | TTFT p90 | TPOT p90 | 위 실행, 같은 부하와 분할 |
|--:|---|---|--:|--:|--:|---|
| 1 | 대화 ×2 | 2P+1D → 1P+2D(17:43 이동) | 8.2 % | 50.5초 | 544 ms | 10.7 %(실행 중 이동) |
| 2 | 대화 ×2 | 1P+2D(17:45 파드 준비) | 76.4 % | 456 ms | 150 ms | |
| 3 | 대화 ×2 | 1P+2D | 80.4 % | 487 ms | 147 ms | 85.1 %, 85.5 % |
| 4–6 | 코드 ×3 | 1P+2D 유지 | 79.3 %, 78.4 %, 78.1 % | 5.2–5.3초 | 68–70 ms | 1P+2D에서 62.9 %, 68.4 %, 2P+1D로 옮긴 뒤 44.8 %, 45.5 % |
| 7–8 | 대화 ×2 | 1P+2D 유지 | 80.7 %, 84.8 % | 454 ms, 445 ms | 149 ms, 136 ms | 85.1 %, 85.5 % |
| 9–10 | 코드 ×3 | 1P+2D 유지 | 80.9 %, 77.2 % | 5.0초, 5.6초 | 70 ms | 4–6과 같음 |

- **50분 동안 한 번, 옳은 이동**: 첫 대화 구간의 네 번째 라운드에서 2:1 → 1:2(decode 압력 5.33, 1:2는 P 0.13 D 0.33으로 예측).
  두 코드 ×3 구간 내내 모든 라운드에서 1P+2D를 유지했습니다(P 2.4–2.7, D 0.69: "no split predicted better than now", 2:1은
  decode 포화로 예측).
- **코드 ×3 달성률 77–81 %**: 모든 실행에서. 위 실행의 같은 분할에서는 63–68 %, 선형 규칙의 이동 뒤에는 40–45 %였습니다. 분할은
  위 실행의 첫 코드 구간과 같으므로 차이의 일부는 실행 간 편차입니다(앞 실행은 대화 구간 직후 파드를 막 patch한 상태). 예측 규칙이
  피한 것은 45 % 수준입니다.
- **1P+2D의 대화 ×2: 76–85 %**, 앞과 같습니다(85 %). 코드 ×3의 TTFT는 5초로 2초 SLO를 넘습니다. 카드 3장으로는 어떤 분할도 코드 ×3을
  SLO 안에서 처리하지 못하고, 카드를 prefill로 옮기면 더 나빠집니다.
- 실제로 확인하지 못한 것: 모델이 이득으로 예측하는 코드 이동(이 부하와 카드 3장에서는 없음).

## W7: 같은 예산 기준선

### Azure 대화, ×0.5 (요청 212개, 0.71 req/s)

| 구성 | 카드 | SLO 달성 | TTFT p90 | TPOT p90 | Goodput req/s | 카드당 | 전력 W (최대) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD | 2 | 100.0 % | 246 ms | 33.1 ms | 0.70 | 0.35 | 155.9 (176) | 0.57 |
| 복제: `solo` ×2 RNGD | 2 | 100.0 % | 186 ms | 30.0 ms | 0.70 | 0.35 | 212.2 (250) | 0.42 |
| RNGD prefill → ATOM decode | 2 | 0.0 % (212개 중 70개 timeout) | 39,984 ms | 3,116 ms | 0.00 | 0.00 | 93.6 (104) | 0.38 |
| PD 2P+1D RNGD (optimal, 기존 프로파일) | 3 | 100.0 % | 158 ms | 34.2 ms | 0.70 | 0.23 | 193.1 (207) | 0.46 |
| PD 1P+2D RNGD (optimal, 보정) | 3 | 100.0 % | 192 ms | 33.1 ms | 0.70 | 0.23 | 242.4 (288) | 0.37 |
| 복제: `solo` ×3 RNGD | 3 | 100.0 % | 191 ms | 30.7 ms | 0.70 | 0.23 | 277.4 (350) | 0.32 |

### Azure 대화, ×1 (요청 455개, 1.52 req/s)

| 구성 | 카드 | SLO 달성 | TTFT p90 | TPOT p90 | Goodput req/s | 카드당 | 전력 W (최대) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD | 2 | 87.7 % | 289 ms | 110.4 ms | 1.32 | 0.66 | 153.7 (168) | **1.17** |
| 복제: `solo` ×2 RNGD | 2 | **100.0 %** | 186 ms | 32.1 ms | **1.51** | **0.75** | 236.1 (259) | 0.76 |
| 벤더: furiosa-llm ×2 RNGD (집약) | 2 | **100.0 %** | 102 ms¹ | 18.1 ms¹ | **1.51** | **0.76** | 243.0 (297) | 0.74 |
| RNGD prefill → ATOM decode | 2 | 0.0 % (455개 중 313개 timeout) | 135,915 ms | 3,390 ms | 0.00 | 0.00 | 92.3 (105) | 0.38 |
| PD 2P+1D RNGD (optimal, 기존 프로파일) | 3 | 93.6 % | 249 ms | 85.4 ms | 1.41 | 0.47 | 200.7 (221) | **0.89** |
| PD 1P+2D RNGD (optimal, 보정) | 3 | **100.0 %** | 336 ms | 38.7 ms | **1.51** | **0.50** | 257.7 (286) | **0.70** |
| 복제: `solo` ×3 RNGD | 3 | 100.0 % | 200 ms | 31.6 ms | 1.51 | 0.50 | 317.0 (372) | 0.57 |
| 벤더: furiosa-llm ×3 RNGD (집약) | 3 | 100.0 % | 91 ms¹ | 17.2 ms¹ | 1.51 | 0.50 | 319.4 (429) | 0.56 |

### Azure 코드, ×1 (요청 222개, 0.74 req/s, 짧은 답: p50 14 토큰)

| 구성 | 카드 | SLO 달성 | TTFT p90 | TPOT p90 | Goodput req/s | 카드당 | 전력 W (최대) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD | 2 | 84.7 % | 281 ms | 143.4 ms | 0.62 | 0.31 | 98.2 (170) | **0.19** |
| 복제: `solo` ×2 RNGD | 2 | **99.5 %** | 181 ms | 58.0 ms | **0.73** | **0.37** | 108.4 (208) | 0.17 |
| 벤더: furiosa-llm ×2 RNGD (집약) | 2 | **100.0 %** | 64 ms¹ | 18.9 ms¹ | **0.74** | **0.37** | 109.6 (201) | 0.17 |
| RNGD prefill → ATOM decode | 2 | 0.0 % | 239 ms | 4,225 ms | 0.00 | 0.00 | 78.4 (108) | 0.21 |
| PD 2P+1D RNGD (optimal, 기존 프로파일) | 3 | 77.5 % | 793 ms | 195.6 ms | 0.57 | 0.19 | 138.6 (195) | 0.14 |
| PD 1P+2D RNGD (optimal, 보정) | 3 | **100.0 %** | 1,675 ms | 69.2 ms | **0.74** | **0.25** | 144.0 (233) | **0.13** |
| 복제: `solo` ×3 RNGD | 3 | 98.2 % | 185 ms | 47.7 ms | 0.72 | 0.24 | 160.2 (323) | 0.12 |
| 벤더: furiosa-llm ×3 RNGD (집약) | 3 | 100.0 % | 52 ms¹ | 17.6 ms¹ | 0.74 | 0.25 | 152.8 (242) | 0.12 |

모든 구성이 같은 요청을 처리했습니다(timeout이 없으면 tok/s 열이 0.1 % 안에서 일치).

¹ furiosa-llm은 `--api completions-stream`으로 측정했습니다. TTFT는 클라이언트가 받은 첫 스트림 토큰(대기 포함), TPOT은 그
뒤의 간격입니다. rngd-pd 행은 `--api completions`(비스트리밍, TTFT는 서버 시간에서 계산하고 decode lane 대기는 TPOT에 들어감)
이므로 furiosa-llm 쪽이 더 엄격한 측정입니다. 대화 ×0.5 표에는 furiosa-llm 행이 없습니다(실행 안 함).

### 표가 말하는 것

- **카드 2장에서는 복제가 카드당 goodput에서 이깁니다.** `solo` 카드는 decode하는 카드에서 prefill하므로 요청이 KV 복사나 다른
  카드의 lane을 기다리지 않습니다. 대화 ×1에서 `solo` 2장은 모든 요청이 SLO를 지켰고, 같은 2장의 1P+1D는 12 %가 TPOT를
  넘었습니다. S=512 프롬프트의 prefill은 30–65 ms로, 토큰당 30 ms인 100 토큰 답에 비해 짧아서 단계를 나누는 이득이 작습니다.
- **에너지는 PD가 이깁니다.** 같은 부하에서 1P+1D는 카드 2장에 154 W, `solo` 2장은 236 W를 썼습니다. prefill 카드는 짧은
  prefill 사이에 쉬고 decode 카드는 고정 폭 그래프 하나를 돌립니다. 대화 ×1에서 줄당 출력 토큰 1.17로 `solo` 쌍의 1.5배입니다.
- **PD가 시간을 잃는 곳.** `PD_PREFETCH=0`에서 decode 워커는 요청을 받을 때 67 MB KV를 `/dev/shm`에서 device lock 안에서
  적재하고(31–54 ms) 그동안 모든 활성 스트림이 기다립니다. Azure 코드는 답이 짧아 진입이 잦으므로 클라이언트 TPOT p90이
  143 ms(1P+1D)와 196 ms(진입이 더 잦은 2P+1D)로 올랐습니다. `--api completions`에서 클라이언트 TTFT는 서버의 prefill 시간이라
  decode 대기열은 TTFT가 아니라 TPOT에 나타납니다.
- **컨트롤러의 첫 선택 2P+1D는 decode가 병목**입니다. 대화 트레이스에 필요 없는 prefill 카드를 47 W 더 들여 추가했고(TTFT p90
  249 ms 대 289 ms) 코드에서는 도움이 되지 않았습니다.
- **보정 후의 선택 1P+2D가 카드 3장의 가장 좋은 PD 배치**입니다. 두 트레이스 모두 모든 요청이 SLO를 지켰고, 카드당 goodput은
  `solo` ×3과 같으며(0.50과 0.25 대 0.50과 0.24) tok/J는 그 1.2배입니다(대화 0.70 대 0.57). decode 카드가 둘이면 decode 워커당
  진입(그리고 lock 안의 KV 적재)이 절반이 되며, 2P+1D가 뒤처진 이유로 보입니다. prefill 카드 한 장의 한계는 코드의 burst에서
  보입니다(TTFT p90 1.7초, SLO 4초 이내).
- **RNGD → ATOM**은 끝까지 동작하지만(RNGD prefill, `shm` KV, ATOM 카드 한 장 decode) SLO를 지킬 수 없습니다. S=512 ATOM decode
  그래프는 batch 4까지 어디서나 토큰당 108 ms라 ATOM 한 장은 초당 약 37 토큰을 decode하는데, 이 실행들은 초당 90–180 토큰을
  요구합니다. 요청이 lane을 기다리며 쌓이고, 대화 ×1에서 455개 중 313개가 클라이언트 timeout 300초에 걸렸습니다. 배치 결과가
  아니라 엔진 한계(그래프 속도와 S=512의 B=4 상한)입니다.

### 반복 실행 (2026-10-20/21, [#43](https://github.com/ai-computing/ai-rm/issues/43))

위 표는 칸마다 한 번 실행한 결과입니다. 네 배치를 Azure 대화 ×1(요청 455개, 1.52 req/s)로 여러 번씩 다시 돌렸습니다.
카드 2장 배치 셋과, 보정한 카드 3장 PD 배치입니다. SLO, 클라이언트 옵션, `--power prom` 조회는 위 표와 같습니다.
나머지 구성도 W7과 같습니다: 노드, Deployment, rngd-pd `/app` 체크아웃(rngd-pd `main` + #5 + #4의 backlog 수정).
rm-bench는 위의 프롬프트 수정이 들어간 ai-rm `master`를 썼습니다. 요청마다 토큰 수는 바뀌지 않았습니다(Llama tokenizer로 확인).

절차:
- 라운드를 섞어 돌렸습니다: 1P+1D, 1P+2D, `solo` ×2, furiosa-llm ×2, 그다음 라운드.
- 실행마다 새로 만든 파드에서 시작했습니다.
- rngd-pd 배치의 워밍업: `pd-smoke`, 이어서 [유휴 측정](#유휴-측정-rngd-pd-게이트웨이의-서버-시간-3회-중앙값-ms)
  (16–480 토큰 요청 36개, decode 폭 1–8). furiosa-llm은 `pd-smoke`만 했습니다.
- 전력 조회는 실행마다 파드가 받은 카드를 파드에서 읽어 썼습니다.
- 둘째 날부터는 Kubernetes 밖의 프로세스가 RNGD 카드 세 장 중 하나를 잡고 있었습니다. device plugin이 그 카드에 올린 파드는 실행
  전에 지웠고, 배치가 빈 카드 두 장에서 돌 때까지 반복했습니다. 그 뒤로 카드 3장 배치는 다시 돌리지 않았지만, 그 세 번은 이미
  끝난 상태였습니다.
- 1P+2D의 2·3회차는 제어 호스트에 닿을 수 없을 때(파드 재시작 불가) NPU 노드에서 돌렸습니다. 2회차용으로 만든 파드를 그대로 써서
  3회차는 재시작 없이 돌았습니다. 2회차는 backlog를 남기지 않았습니다(455개 모두 응답).

| 구성 | 카드 | 실행 수 | SLO 달성 | TTFT p90 ms | TPOT p90 ms | 카드당 goodput | 전력 W | tok/J | W7 단일 실행: SLO / 카드당 / tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD | 2 | 5 | 81.6 % ± 31.4 (25.5–98.0) | 1,504 ± 2,743 (193–6,408) | 98.4 ± 62.8 (61.2–209.8) | 0.61 ± 0.24 (0.19–0.74) | 165 ± 8 (150–169) | 1.06 ± 0.00 (1.06–1.07) | 87.7 % / 0.66 / 1.17 |
| 복제: `solo` ×2 RNGD | 2 | 3 | 97.1 % ± 4.9 (91.4–100.0) | 240 ± 85 (189–338) | 52.5 ± 34.7 (32.4–92.6) | 0.73 ± 0.04 (0.69–0.75) | 222 ± 32 (185–243) | 0.82 ± 0.13 (0.74–0.97) | 100.0 % / 0.75 / 0.76 |
| 벤더: furiosa-llm ×2 RNGD¹ | 2 | 3 | 100.0 % ± 0.0 (100.0–100.0) | 103 ± 1 (102–104) | 17.8 ± 0.1 (17.7–17.9) | 0.76 ± 0.00 (0.76–0.76) | 251 ± 5 (246–257) | 0.72 ± 0.02 (0.70–0.73) | 100.0 % / 0.76 / 0.74 |
| PD 1P+2D RNGD (optimal, 보정) | 3 | 3 | 100.0 % ± 0.0 (100.0–100.0) | 358 ± 29 (336–391) | 38.5 ± 0.6 (38.1–39.2) | 0.50 ± 0.00 (0.50–0.50) | 268 ± 2 (267–270) | 0.67 ± 0.00 (0.66–0.67) | 100.0 % / 0.50 / 0.70 |

각 칸은 실행들의 평균 ± 표본 표준편차 (최소–최대)입니다. 카드당 goodput은 위와 같이 실행의 wall time으로 계산했습니다.
¹ 스트리밍 클라이언트(`--api completions-stream`), 위 벤더 행과 같음.

| 실행 | SLO 달성 | TTFT p90 ms | TPOT p90 ms | 카드당 | 전력 W | tok/J | 미응답 | 측정: prefill 다운로드 p90 / 최대 ms |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D, 1 | 98.0 % | 193 | 61.2 | 0.74 | 169 | 1.06 | 0 | 25 / 28 |
| PD 1P+1D, 2 | **25.5 %** | 6,408 | 209.8 | 0.19 | 150 | 1.06 | 46 | **118 / 198** |
| PD 1P+1D, 3 | 94.3 % | 274 | 80.4 | 0.71 | 168 | 1.07 | 0 | 73 / 99 |
| PD 1P+1D, 4 | 93.4 % | 416 | 76.5 | 0.70 | 169 | 1.06 | 0 | 65 / 197 |
| PD 1P+1D, 5 | 96.7 % | 228 | 64.1 | 0.73 | 168 | 1.07 | 0 | 44 / 188 |
| `solo` ×2, 1 | 91.4 % | 338 | 92.6 | 0.69 | 185 | 0.97 | 0 | |
| `solo` ×2, 2 | 100.0 % | 189 | 32.4 | 0.75 | 238 | 0.76 | 0 | |
| `solo` ×2, 3 | 100.0 % | 193 | 32.6 | 0.75 | 243 | 0.74 | 0 | |
| furiosa-llm ×2, 1–3 | 100.0 % ×3 | 102–104 | 17.7–17.9 | 0.76 | 246–257 | 0.70–0.73 | 0 | |
| PD 1P+2D, 1 | 100.0 % | 336 | 39.2 | 0.50 | 268 | 0.67 | 0 | 29 / 31 |
| PD 1P+2D, 2 | 100.0 % | 391 | 38.1 | 0.50 | 270 | 0.66 | 0 | 166 / 206 |
| PD 1P+2D, 3 | 100.0 % | 346 | 38.2 | 0.50 | 267 | 0.67 | 0 | 183 / 206 |

"미응답"은 일정이 끝났을 때 아직 열려 있던 요청 수입니다. "측정"은 실행 직전 유휴 측정에서 잰 prefill 출력의 device→host
다운로드입니다. PD prefill 가운데 계산이 아닌 부분이고, W6 측정에서는 약 25 ms였습니다.

**발견**
- **대화 ×1에서 PD 1P+1D는 용량의 경계에서 돕니다.** 한 번의 실행으로는 경계의 어느 쪽에 떨어질지 알 수 없습니다:
  - 다섯 번 실행: 98.0, 25.5, 94.3, 93.4, 96.7 %. W7 단일 실행은 87.7 %, W2 멀티 풀 실행은 98.0 %였습니다.
  - 네 번은 decode가 따라갔습니다(TPOT p90 61–80 ms).
  - 2회차는 대기열이 끝내 줄지 않았습니다: TTFT p90 6.4초, 끝날 때 46개가 열려 있었습니다.
  - 2회차 직전 측정에서 prefill 다운로드가 가장 느렸습니다(p90 118 ms, 다른 실행 직전은 25–73 ms). 엔진에는 cancel이 없어
    (aicomp#43) 초반에 생긴 backlog가 실행이 끝날 때까지 남습니다.
  - 1P+2D는 그만큼 느린 다운로드(p90 166–183 ms)에서도 모든 요청이 SLO를 지켰습니다. 두 번째 decode 카드가 여유입니다.
- **차가운 파드는 무너집니다.** 첫 라운드는 `pd-smoke`만으로 워밍업했습니다:
  - 결과: 1P+1D 7.0 %(미응답 107개, TTFT p90 68초), 1P+2D 55.4 %, `solo` ×2 89.0 %.
  - 새 파드의 첫 prefill들은 다운로드에 60–175 ms가 걸리고(데워진 뒤 약 25 ms), 초반 backlog가 풀리지 않습니다.
  - 측정으로 워밍업하자(W7 절차) 같은 배치가 위 표처럼 돌았습니다. 이 세 번의 차가운 실행은 통계에 넣지 않았습니다. 측정
    워밍업은 선택이 아니라 절차의 필수 단계입니다.
- **`solo` ×2: 세 번 중 두 번은 W7을 재현합니다**(100 %, TPOT p90 32 ms). 1회차는 91.4 %, TPOT p90 93 ms였고, 카드 전력이
  238–243 W가 아니라 185 W였습니다. Service는 요청이 아니라 연결을 나누므로, replica 하나가 부하 대부분을 진 경우와 맞습니다
  (파드별로 확인하지는 않음).
- **furiosa-llm ×2는 세 번 모두 같습니다**(100 %, TPOT p90 18 ms, 카드당 0.76, 0.70–0.73 tok/J).
- **PD 1P+2D는 세 번 모두 모든 요청이 SLO를 지켰습니다.** TTFT p90 336–391 ms, TPOT p90 38–39 ms, tok/J 0.66–0.67(W7: 0.70).

**단일 실행의 결론이 유지되는가?**

| 단일 실행의 결론 (W7) | 반복 실행 결과 |
|---|---|
| 카드 2장: 카드당 goodput은 복제가 PD 1P+1D보다 높다 | **유지, 더 강해짐.** 카드당 goodput: `solo` 0.73 ± 0.04, furiosa-llm 0.76, PD 1P+1D 0.61 ± 0.24(중앙값 0.71). 이 도착률에서 PD 1P+1D는 SLO를 안정적으로 지키지 못합니다. 다섯 번 중 한 번 무너졌습니다. |
| tok/J는 PD 1P+1D가 가장 높다 (1.17) | **유지, 값은 작아짐.** 모든 실행에서 1.06(단일 실행의 1.17은 10 % 높았음). `solo`(0.82 ± 0.13, 100 %인 두 번은 0.74–0.76)의 1.3배, furiosa-llm(0.72)의 1.5배입니다. |
| furiosa-llm은 카드당 goodput과 tok/J에서 `solo`와 같다 | **유지.** 카드당 0.76 대 0.73 ± 0.04, tok/J 0.72 대 100 %인 `solo` 실행들의 0.74–0.76. |
| 보정한 `optimal` 1P+2D는 카드 3장에서 SLO를 지킨다 | **유지**(3번 중 3번 100 %). tok/J는 0.70이 아니라 0.67입니다. W7 `solo` ×3 단일 실행(0.57) 대비 1.17배이며, `solo` ×3은 반복하지 않았습니다. |
| 1P+1D의 87.7 %가 이 배치의 달성률이다 | **유지되지 않음.** 5번의 평균 81.6 ± 31.4 %, 중앙값 94.3 %. 결과는 정해진 숫자가 아니라 두 갈래로 나뉩니다. |

**같은 예산의 A100: 실행하지 않음.** 논문은 이 행을 빠진 항목으로 적고 있습니다. 이번 작업 내내 두 번째 NPU 노드의 A100 두 장은
다른 프로젝트의 학습 근거 실험이 쓰고 있었습니다:
- DCGM은 확인한 30분 구간마다 이용률이 100 %까지 올랐습니다.
- 마지막 확인 때 GPU 하나에 69 GB가 쓰이고 있었습니다.
- 그 프로젝트는 실험을 위해 노드의 cordon을 풀었고 아직 되돌리지 않았습니다.

작업 지침은 그 작업이 A100을 내줄 때까지 쓰지 않도록 했으므로 이 행은 여전히 비어 있습니다. 방법은 준비돼 있습니다: 기존
`vllm-a100-llama31-8b` Deployment를 replica 1과 2로, 같은 트레이스와 SLO, `--api completions-stream`, 사용 중인 GPU의 DCGM
`DCGM_FI_DEV_POWER_USAGE`([재현](#재현)).

### 벤더 단독 기준선: furiosa-llm (W7)

같은 카드에서 벤더 엔진을 돌렸습니다. 이미지 `furiosaai/furiosa-llm:2026.3.0`(클러스터의 k-exaone, qwen3-4b 배포가 쓰는 것),
`furiosa-llm serve furiosa-ai/Llama-3.1-8B-Instruct`, FuriosaAI가 Hugging Face에 올린 미리 컴파일된 BF16 artifact(릴리스 태그
`v2026.3`, 카드 한 장의 PE 8개에 tensor parallel), 서빙 이름은 `meta-llama/Llama-3.1-8B-Instruct`. replica 하나에 카드 한 장
(`furiosa.ai/rngd: 1`), `solo`처럼 Deployment(`airm-exp-flm`) replica N개를 Service 하나 뒤에 두었고, 나머지는 서빙 기본값(prefix
caching 켜짐, 기본 bucket)입니다. 트레이스, SLO, 전력 쿼리, 노드는 같고 클라이언트는 `--api completions-stream`입니다.

| | furiosa-llm ×2 | `solo` ×2 | furiosa-llm ×3 | `solo` ×3 | PD 1P+2D |
|---|--:|--:|--:|--:|--:|
| 대화 ×1: SLO / TTFT p90 / TPOT p90 | 100 % / 102 / 18.1 | 100 % / 186 / 32.1 | 100 % / 91 / 17.2 | 100 % / 200 / 31.6 | 100 % / 336 / 38.7 |
| 대화 ×1: W / tok/J | 243 / 0.74 | 236 / 0.76 | 319 / 0.56 | 317 / 0.57 | 258 / 0.70 |
| 코드 ×1: SLO / TTFT p90 / TPOT p90 | 100 % / 64 / 18.9 | 99.5 % / 181 / 58.0 | 100 % / 52 / 17.6 | 98.2 % / 185 / 47.7 | 100 % / 1,675 / 69.2 |
| 코드 ×1: W / tok/J | 110 / 0.17 | 108 / 0.17 | 153 / 0.12 | 160 / 0.12 | 144 / 0.13 |

- **이 도착률에서는 SLO를 지키는 2·3장 배치가 모두 제공 부하에 묶입니다.** goodput은 furiosa-llm, `solo`, PD 1P+2D 모두
  트레이스 속도(1.51, 0.74 req/s)라 카드당 goodput이 같습니다. 벤더 엔진이 앞서는 것은 이 goodput이 아니라 지연입니다.
  TPOT p90 17–19 ms(rngd-pd 그래프는 30–69 ms), 클라이언트에서 잰 TTFT p90 52–102 ms(rngd-pd는 서버 기준 181–336 ms,
  코드의 PD 1P+2D는 1,675 ms).
- **에너지는 `solo`와 같습니다**(카드 2장 0.74 대 0.76 tok/J, 3장 0.56 대 0.57). 둘 다 요청 전체를 한 카드가 처리해 모든
  카드가 바쁩니다. 카드 2장의 최고 에너지 효율은 여전히 PD 1P+1D의 1.17 tok/J입니다(달성률 87.7 %).
- **furiosa-llm PD는 없으므로 벤더 PD 행도 없습니다.** 2026.3.0 `serve` CLI에는 disaggregation, KV 전송, 역할 옵션이 없고
  (`furiosa-llm serve --help`), 설치된 패키지(`furiosa_llm`, `furiosa-llm-native`, `furiosa-native-llm-common`)에도
  disaggregation, NIXL, KV connector 코드가 없습니다. FuriosaAI의 llm-d 가이드("Deploying Furiosa-LLM with llm-d")는
  Furiosa-LLM이 prefill/decode disaggregation을 지원하지 않는다고 적고, values는 decode 파드만 띄웁니다(`prefill.create:
  false`, intelligent inference scheduling 경로). 벤더 단독 PD 기준선(W7)은 벤더 지원을 기다립니다.
- **도중에 찾은 프롬프트 문제.** 처음 furiosa-llm 실행에서 prefix cache 적중률이 70 %였는데, Azure 재생에는 공유 prefix가
  없습니다. rm-bench의 트레이스 프롬프트가 72단어 어휘를 affine 인덱스로 골라 서로 다른 프롬프트 문장이 72개뿐이었습니다. 이
  변경에서 고쳤고(해시 스트림에서 단어 선택, salt 2,000개가 서로 다른 8단어 머리 2,000개), 위 furiosa-llm 행은 다시 돌린
  결과입니다(적중률 약 10 %, 대부분 `pd-smoke` 예열). 공유 prefix가 있을 때 대화 TTFT p90은 102 ms가 아니라 66 ms였습니다.
  rngd-pd에는 prefix cache가 없어 그 행들은 영향이 없습니다.

### prefetch를 켜면 부하에서 무너짐

같은 2P+1D 배치, rngd-pd 기본값 `PD_PREFETCH=1`:

| 실행 | 보냄 | 실패 | SLO 달성 | tok/s |
|---|--:|--:|--:|--:|
| 대화 ×0.5 | 212 | 0 | 100.0 % | 89.5 |
| 대화 ×1 | 455 | 176 | 60.4 % | 67.7 |
| 코드 ×1 | 222 | 173 | 22.1 % | 2.4 |
| 대화 ×2, 이어서 코드 ×4(사이에 재시작 없음) | 698, 814 | 전부 | 0 % | 0 |

decode 로그에 `TimeoutError: pull timeout: <req>/layer.0/k`가 남습니다. prefetch 맵은 8개만 유지하는데, 밀려난 prefetch가 여전히
`/dev/shm`에서 요청의 KV를 가져가 버리고, 나중의 적재는 device lock 안에서 `PD_KV_PULL_TIMEOUT`(120초)을 기다리며, 대기열에서
이미 꺼낸 요청에는 끝내 응답하지 않습니다. 자세한 원인과 고칠 방법: [rngd-pd#4](https://github.com/ai-computing/rngd-pd/issues/4).
취소(aicomp#43)가 없어 backlog가 클라이언트보다 오래 남으므로, 파드를 재시작할 때까지 다음 실행도 실패합니다. 다른 실행은 모두
`PD_PREFETCH=0`입니다.

## 보정 (W6)

### 유휴 측정 (rngd-pd 게이트웨이의 서버 시간, 3회 중앙값, ms)

| 프롬프트 토큰 | 16 | 64 | 128 | 256 | 384 | 480 |
|---|--:|--:|--:|--:|--:|--:|
| RNGD prefill, PD(계산 + 내려받기 + KV 저장) | 67.5 | 68.4 | 78.0 | 89.4 | 98.2 | 181.2 |
| ↳ 그중 계산 | 36.2 | 36.1 | 39.8 | 51.6 | 64.5 | 73.4 |
| RNGD prefill, `solo`(decode 카드에서) | 31.1 | 31.2 | 38.8 | 43.1 | 63.5 | 64.5 |
| decode 진입 시 KV 적재, `shm`으로 67 MB | 33.0 | 32.8 | 50.6 | 51.3 | 31.0 | 32.2 |

| 동시 스트림 | 1 | 2 | 4 | 8 |
|---|--:|--:|--:|--:|
| RNGD decode, continuous B=8 그래프, 토큰당 ms | 29.8 | 30.1 | 30.2 | 30.3 |
| RNGD `solo`, 토큰당 ms | 29.0 | 27.6 | 28.2 | 26.2 |
| ATOM decode, B=4 그래프, 토큰당 ms | 108.2 | 108.1 | 108.6 | 108.6(4개씩) |

480 토큰의 prefill은 장치→호스트 내려받기(18–143 ms)에 따라 흔들립니다.

### 프로파일 전후

| `profiles.yaml` | 전 | 후 | 현재 출처 |
|---|--:|--:|---|
| RNGD `prefill_tok_s` / `prefill_overhead_ms` | 2500 / 60 (유도) | 12000 / 66 | 측정, 16–384 토큰 선형 맞춤 |
| RNGD `tpot_ms_b1` / `tpot_ms_bmax` | 17.0 / 24.0 (B=1 그래프 측정 / 추정) | 30.0 / 30.3 | 측정, continuous B=8 그래프 |
| RNGD `max_batch` | 8 (추정) | 8 | 측정 |
| ATOM `group` | 2 | 1 | 측정: fp16 decode artifact가 카드 한 장에서 동작 |
| ATOM `tpot_ms_b1` / `tpot_ms_bmax` | 40.0 / 52.0 (추정 / 유도) | 108.2 / 108.6 | 측정, S=512 B=4 그래프 |
| ATOM `max_batch` / `kv_tokens` | 8 / 4096 | 4 / 2048 | 측정 / 유도(4 × 512) |
| ATOM `prefill_tok_s` | 600 (추정) | 600 | 여전히 추정(실행 안 함) |
| `shm` `gb_s` | 0.6 | 1.6 | 측정: 진입 시 적재, `PD_PREFETCH=0`(end-to-end 실행의 p90 111 ms는 prefetch를 켠 값) |

### 시뮬레이션과 실행 비교

같은 S=512 잘린 구성(잘린 구간의 길이 분위수, 60초 peak/평균은 대화 1.8, 코드 4.0)으로 실행의 도착률에서
`python -m rm_controller.sim`을 돌렸습니다. 달성률 = 두 SLO를 모두 지킨 요청 비율:

| 배치, 트레이스, 도착률 | 측정 | 시뮬레이션, 기존 프로파일 | 시뮬레이션, 보정 |
|---|--:|--:|--:|
| 1P+1D RNGD, 대화 0.71 req/s | 100.0 % | 100 % | 100 % |
| 1P+1D RNGD, 대화 1.52 req/s | 87.7 % | 98.2 % | 78.8 % |
| 2P+1D RNGD, 대화 1.52 req/s | 93.6 % | 98.4 % | 79.0 % |
| 1P+1D RNGD, 코드 0.74 req/s | 84.7 % | 100 % | 100 % |
| 2P+1D RNGD, 코드 0.74 req/s | 77.5 % | 100 % | 100 % |
| 1P+2D RNGD, 대화 1.52 req/s | 100.0 % | 100 % | 100 % |
| 1P+2D RNGD, 코드 0.74 req/s | 100.0 % | 100 % | 100 % |
| RNGD → ATOM, 대화 0.71 req/s | 0.0 % | 92.2 % | 0 % |
| RNGD → ATOM, 코드 0.74 req/s | 0.0 % | 100 % | 0 % |

보정 후 시뮬레이터는 기존 표가 틀린 정성적 결론을 맞힙니다(ATOM decode 실패, 대화 ×1이 90 % 선 근처). 대화에서는 이제
비관적인데, decode 대기를 TTFT에 넣지만 `--api completions`의 클라이언트는 그 대기를 TTFT로 재지 않기 때문입니다. 짧은 답에서 PD를
해치는 것, 즉 진입할 때마다 decode 루프 안에서 하는 KV 적재는 여전히 모델에 없고, 여기서 이긴 카드 한 장(`solo`) 서빙도 모델이
없습니다. 둘 다 [컴포넌트 카드](../components/rm-controller.md)의 할 일입니다. [rm-controller README](../../packages/rm-controller/README.ko.md)의
시뮬레이션 표는 보정한 프로파일로 다시 돌렸습니다.

## W2: 한 노드의 두 모델 풀 (HUB-35)

RNGD+ATOM 노드에서 두 모델을 동시에 서빙하고, 풀마다 `rm-controller`가 따로 카드를 배치했습니다(2026-10-19,
19:10–19:50 UTC). **Llama-3.1-8B-Instruct**는 RNGD 위 rngd-pd PD 1P+1D(`llama8b-pd-pool`, `airm-e2e` 릴리스, llm-d
게이트웨이로 접근), **Qwen3-4B-FP8**은 furiosa-llm 2026.3.0 aggregated, RNGD 카드 한 장(`qwen3-4b-pool`, Deployment
`airm-exp-qwen`, 자체 Service로 접근)입니다. Qwen Deployment는 클러스터의 `serve-furiosa-ai-qwen3-4b-fp8`(읽기만 했고
replicas 0 그대로)을 복사했습니다. 이미지와 인자가 같고 FuriosaAI가 미리 컴파일한 아티팩트(`max_model_len` 40,960)를 쓰며,
풀/역할 annotation과 hostPath 모델 캐시만 더했습니다.

spec은 [`examples/multi-pool.yaml`](../../packages/rm-controller/examples/multi-pool.yaml)입니다(topology; `serve` 풀은 이
변경에서 더한 aggregated 종류):

```
rm-controller --spec multi-pool.yaml --once --apply
rm-controller: 9 profiles, 3 decisions, generation 4 written; 3 deployment patch(es) applied
#  llama8b-pd-pool prefill  <npu-node>/furiosa:0   topology: ... highest peak ... shm keeps prefill and decode on one node
#  llama8b-pd-pool decode   <npu-node>/furiosa:1   topology: ... most memory ...
#  qwen3-4b-pool   serve    <npu-node>/furiosa:3   topology: serve ... (furiosa.RNGD, 1 replica(s), aggregated)
```

**카드를 공유하지 않음.** patch가 replicas 1/1/1과 node affinity를 넣었고, device plugin은 Llama prefill·decode 파드에
`npu1`·`npu0`, Qwen 파드에 `npu3`을 줬습니다(컨테이너에는 `/dev/rngd/npu3*`만 보임). 동시 실행 2분째 `furiosa-smi`는
`npu0` 116 W / 사용률 57 %, `npu1` 56 W, `npu3` 82 W, 메모리 47.5 GiB 중 46.7 GiB 사용(furiosa-llm의 KV 풀)이었습니다. W5처럼
결정의 카드 이름은 device plugin의 이름과 다릅니다.

**두 풀에 동시에 부하.** Azure 대화 ×1(요청 455개, 1.52 req/s, 입력+출력 ≤ 511 토큰, 300초)을 두 풀에 동시에 재생하고,
이어서 각 풀에 따로 재생했습니다. SLO TTFT p90 ≤ 2초, TPOT p90 ≤ 100 ms. 전력은 풀마다 자기 카드만(`--power prom`,
`device=~"npu0|npu1"`, `"npu3"`). Llama는 llm-d 게이트웨이로 `--api completions`, Qwen은 Service로 `--api completions-stream`
(W7 벤더 행과 같음):

| 풀 | 실행 | 카드 | SLO 달성 | TTFT p90 | TPOT p90 | Goodput req/s | 카드당 | 전력 W (최대) | tok/J |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|
| Llama-3.1-8B, rngd-pd PD 1P+1D | **두 풀 동시** | 2 | 97.6 % | 243 ms | 61.8 ms | 1.47 | 0.74 | 162.8 (182) | 1.10 |
| Llama-3.1-8B, rngd-pd PD 1P+1D | 단독 (파드 재시작) | 2 | 98.0 % | 198 ms | 61.4 ms | 1.48 | 0.74 | 162.1 (178) | 1.11 |
| Qwen3-4B-FP8, furiosa-llm ×1 | **두 풀 동시** | 1 | 100.0 % | 120 ms¹ | 24.3 ms¹ | 1.51 | 1.51 | 80.8 (95) | 2.23 |
| Qwen3-4B-FP8, furiosa-llm ×1 | 단독 | 1 | 100.0 % | 64 ms¹ | 20.4 ms¹ | 1.51 | 1.51 | 74.2 (81) | 2.43 |

¹ 스트리밍, 클라이언트에서 측정(W7 각주 참고). 모든 실행에서 요청 455개가 모두 끝났고 실패는 없었습니다.

- **두 풀 모두 옆 풀이 있어도 SLO를 지킵니다.** Llama의 달성률·TPOT·goodput은 Qwen 부하가 있든 없든 실행 간 잡음 안에서
  같습니다(97.6 % / 98.0 %). Qwen은 어느 쪽이든 모든 요청이 SLO를 지켰습니다. 같은 Llama 배치·부하의 W7 칸은 87.7 %였습니다(다른
  날의 파드). 오늘의 98 %는 단일 실행의 편차 안입니다.
- **공유하는 것은 호스트입니다.** Llama가 돌 때 Qwen의 클라이언트 TTFT p90이 두 배(64 → 120 ms), TPOT p90이 4 ms 늘었습니다.
  카드는 겹치지 않으므로 가속기가 아니라 함께 쓰는 호스트(CPU, PCIe root, 클라이언트 머신)가 원인일 가능성이 큽니다. 둘 다
  SLO 안쪽에 넉넉히 있습니다.
- Qwen3-4B 카드 한 장이 Llama-3.1-8B PD 카드 두 장과 같은 요청 흐름을 풀당 전력 절반 정도(81 W 대 163 W)로 처리합니다. 모델이
  다르므로 엔진 비교는 아닙니다.

**spec을 바꾸면 그 풀만 움직입니다.** spec을 Llama decode를 ATOM에서 하도록 바꾸고(`decode: {accelerator: rebellions.ATOM}`)
컨트롤러를 한 번 다시 실행했습니다. Llama decode 역할은 장치 종류마다 Deployment를 하나씩 두었습니다(`accelerator:
furiosa.RNGD` annotation을 단 `airm-e2e-decode`, W7 RNGD → ATOM 릴리스의 ATOM decode 설정을 쓴 `airm-exp-decode-atom`, 둘 다
`airm-e2e-decode` Service 뒤):

```
rm-controller: 9 profiles, 3 decisions, generation 5 written; 2 deployment patch(es) applied
#  patch airm-e2e-decode       replicas 1 -> 0   decode of llama8b-pd-pool: no furiosa.RNGD cards in the decision
#  patch airm-exp-decode-atom  replicas 0 -> 1   decode of llama8b-pd-pool: 1 replica(s) on <npu-node>
#  airm-e2e-prefill            up to date
#  airm-exp-qwen               up to date
```

| Deployment | generation 4 | generation 5 |
|---|---|---|
| `airm-e2e-prefill` (Llama prefill) | 1 × `furiosa:0` | 그대로 (patch 없음) |
| `airm-e2e-decode` (Llama decode, RNGD) | 1 × `furiosa:1` | replicas 0 |
| `airm-exp-decode-atom` (Llama decode, ATOM) | replicas 0 | 1 × `rebellions:0`, patch 51초 뒤 ready |
| `airm-exp-qwen` (Qwen) | 1 × `furiosa:3` | 그대로: 같은 파드, 19:11:43 UTC 시작, 전후 모두 재시작 0 |

이동 중에 두 풀에 `pd-smoke`를 동시에 걸었습니다. Qwen은 32/32 SLO 안. Llama는 ATOM decode 파드가 32/32를 처리했고(고정
프롬프트에서 RNGD와 같은 텍스트) smoke SLO는 넘었습니다(TPOT p90 377 ms: ATOM S=512 그래프 토큰당 108 ms에 lane 4개로 요청
8개, W7과 같음). 여기서는 바뀐 역할이 다른 풀이 쓰지 않는 장치 종류로 갔습니다. 새 규칙이 실제로 필요한 경우(decode가
ATOM → RNGD로 옮기는데 Qwen 풀이 RNGD 카드를 쥐고 있어서 새로 배치하면 그 카드를 가져갈 때)는
`test_changed_spec_moves_only_that_pool`이 다룹니다.

## W2: tcp를 통한 노드 간 KV (HUB-34)

**구성.** rngd-pd의 `tcp` 전송(이 변경, [rngd-pd#9](https://github.com/ai-computing/rngd-pd/pull/9)): prefill 워커가 층마다
K와 V(bf16 wire, 1 MiB blob 64개, S=512에서 요청당 67.1 MB)를 연결을 재사용하는 TCP로 `TcpKVServer`에 밀어 넣고 decode
워커가 거기서 가져갑니다. blob마다 CRC-32를 달아 서버와 수신 측이 확인합니다. 서버는 **CPU만 있는 노드의 relay 파드**로
돌렸고(chart 옵션 `kvRelay`, 이미지 `python:3.11-slim`, ConfigMap으로 넣은 표준 라이브러리 전용 `tcpkv.py`), prefill(RNGD)과
decode(RNGD) 파드는 NPU 노드에 있었으므로 **KV의 모든 바이트가 네트워크를 두 번 건넜습니다**: NPU 노드 → relay 노드 → NPU
노드. 릴리스 `airm-exp-xnode`(rngd-pd chart, `airm-e2e` values에 `airm.kvTransport: tcp`, decode `--B 8 --sched continuous`,
`PD_PREFETCH=0`), 자체 게이트웨이 Service(llama8b-pd InferencePool에는 넣지 않음). NPU 노드는 다른 노드와 **1 GbE**
인터페이스로 연결되며(노드 간 RTT 0.22 ms), 아래 모든 수치의 한계는 전송이 아니라 이 링크입니다.

**바이트 단위 일치.** `AIRM_KV_TCP_LOG=1`이면 워커가 밀어 넣거나 가져간 blob마다 크기와 SHA-256을 남깁니다. 요청 33개(1 +
순차 16 + 동시 8로 16): prefill의 push와 decode의 pull 사이에서 **blob 2,112개 중 2,112개가 같았고**(2.215 GB), relay는
세션 전체(벤치마크 포함 blob 26,112개, 27.4 GB)에서 CRC 오류 0을 셌습니다.

**토큰 단위 일치.** 고정 프롬프트 16개(8–479 토큰, 출력 32 토큰, greedy)를 순차로, 그리고 동시 8로 같은 릴리스에 보내고
`airm.kvTransport`만 `tcp`와 `shm`으로 바꿨습니다(파드 재시작, 같은 카드): **출력 32개 중 32개가 같았습니다**(텍스트와 토큰
수). 감사 로그를 켜고 끄고 두 번 했습니다.

**서빙에서의 요청당 시간** (rngd-pd 게이트웨이의 `pd` 시간, 프롬프트 16개. save = prefill 계산이 끝난 뒤에도 남은 push,
load = decode admission 때의 pull):

| | `tcp` 순차 | `shm` 순차 | `tcp` 동시 8 | `shm` 동시 8 |
|---|--:|--:|--:|--:|
| KV save, p50 / p90 | 678 / 724 ms | 1.4 / 4.6 ms | 3,266 / 4,304 ms | 1.7 / 4.0 ms |
| admission 때 KV load, p50 / p90 | 816 / 896 ms | 31 / 45 ms | 1,305 / 1,378 ms | 30 / 36 ms |
| 서버 TTFT, p50 / p90 | 778 / 839 ms | 104 / 112 ms | 3,330 / 4,766 ms | 318 / 782 ms |

**링크 측정** (prefill 파드 안에서 `bench/kv_tcp_bench.py`, S=512 모양의 bf16 KV를 relay로 push한 뒤 다시 pull, 동시 요청 N개.
요청당 한 방향 시간과 GB/s):

| 동시 요청 | Push p50 (GB/s) | Pull p50 (GB/s) | 양방향 합, GB/s | 바이트 일치 |
|--:|--:|--:|--:|---|
| 1 | 758 ms (0.089) | 832 ms (0.081) | 0.084 | 예 |
| 2 | 1,182 ms (0.057) | 1,243 ms (0.054) | 0.111 | 예 |
| 4 | 2,330 ms (0.029) | 2,290 ms (0.029) | 0.115 | 예 |
| 8 | 4,427 ms (0.015) | 4,515 ms (0.015) | 0.117 | 예 |
| 1, CRC 끔 | 622 ms (0.108) | 707 ms (0.095) | 0.101 | 예 |
| 8, CRC 끔 | 4,592 ms (0.015) | 4,472 ms (0.015) | 0.117 | 예 |

요청 하나는 방향마다 0.08–0.09 GB/s로 움직입니다. 여러 개가 동시에 있으면 1 GbE 인터페이스가 0.117 GB/s(940 Mbit/s)에서
포화되고 요청당 시간이 선형으로 늘어납니다. CRC는 단일 흐름에서 약 15 %, 링크가 꽉 차면 비용이 없습니다.

**그 위의 실제 트레이스.** Azure 대화 ×0.5(요청 212개, 0.71 req/s)를 relay를 거치는 KV로 `airm-exp-xnode`에 보냈고(먼저
파드 재시작), 같은 배치의 W7 `shm` 칸과 비교했습니다:

| 배포 | 카드 | SLO 달성 | TTFT p90 | TPOT p90 | Goodput req/s | 카드당 | 전력 W (최대) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD, relay 노드를 거치는 KV `tcp` | 2 | 89.2 % | 1,727 ms | 83.3 ms | 0.62 | 0.31 | 151.7 (165) | 0.59 |
| PD 1P+1D RNGD, KV `shm` (W7) | 2 | 100.0 % | 246 ms | 33.1 ms | 0.70 | 0.35 | 155.9 (176) | 0.57 |

요청 212개가 모두 끝났습니다. admission마다 약 0.8초 걸리는 pull이 decode 루프를 멈추고(`PD_PREFETCH=0`) TPOT에 드러나며,
push의 꼬리는 TTFT에 들어갑니다. `pd-smoke`(4초에 요청 32개)는 32개를 모두 처리했지만 TTFT p90이 17.9초였습니다. 8 req/s ×
67 MB는 링크가 나르는 양의 4.6배입니다. 측정한 링크를 넣은 시뮬레이터는 이 배치를 100 %(TTFT p90 983 ms, TPOT 30 ms)로
예측합니다. 재생이 admission 때의 로드를 TPOT에 넣지 않기 때문에(에피소드 재생은 넣음) 여기서는 낙관적이며, 짧은 답의
`shm`에서와 같습니다.

**프로파일과 2노드 행.** `profiles.yaml`의 `tcp`: `gb_s` 0.08(추정 0.5였음), `latency_ms` 14(왕복 64번 × 0.22 ms),
`min_bytes` 67,108,864(S=512 버퍼 전체를 보냄), `admit_blocking: true`, `implemented: true`, `source: measured`, scope
`cluster`. `python -m rm_controller.sim --compare --requests 4000`을 다시 돌리면 2노드에서 `optimal`(카드당, 최대 goodput)은
이제 모든 트레이스에서 `shm`으로 한 노드에 머물고(Azure 대화 0.813 req/s, 코드 0.943, 한 노드와 같음), `tcp`로 제한한 최선의
계획에는 SLO를 지키는 배치가 없습니다(goodput 0). 0.5 GB/s 추정일 때 2노드 열은 0.087–2.724 req/s(한 노드의 2.0–3.5배)였습니다.
대역폭을 바꿔 보면 2노드 배치는 0.15–0.25 GB/s 사이에서 돌아오고, 0.8 GB/s에서 2.73(대화, P 1 / D 3 RNGD)과 2.39 req/s(코드,
P 3 / D 1)에 이릅니다. 즉 2노드 이득에는 NPU 노드 사이에 2.5 GbE 이상의 링크가 필요합니다. `python -m rm_controller.baselines
--compare --requests 4000`은 그대로입니다(카드 집합이 모두 단일 노드). 표: [rm-controller README](../../packages/rm-controller/README.ko.md#-시뮬레이션-topology-대-optimal),
[컴포넌트 카드](../components/rm-controller.md).

### 두 번째 NPU 노드 (2026-10-20)

**배치.** 릴리스 `airm-exp-xnode`(rngd-pd `main` chart, relay 실행의 values, `PD_PREFETCH=0`): 게이트웨이와 RNGD prefill은
RNGD+ATOM 노드(npu-node-1)에, RNGD decode(`--B 8 --sched continuous`)와 `kvRelay` 파드는 두 번째 RNGD 노드(npu-node-2)에
두었습니다. prefill 워커는 요청마다 KV를 1 GbE 링크 너머의 relay로 push하고, decode 워커는 자기 노드의 relay에서 pull합니다.
두 번째 노드는 실행 동안만(08:17–08:44 UTC) 열었고, 실험 파드만 견디는 임시 `airm.ai-computing.io/experiment=true:NoSchedule`
taint를 건 뒤였으며, 끝나고 다시 cordon했습니다. 워커의 호스트 런타임(Python 패키지, furiosa venv, 컴파일된 그래프 캐시,
rngd-pd `main`, 22 GB)은 두 번째 노드에 설치되어 있지 않아 실행용 임시 디렉터리로 복사했습니다(188초). 노드 배치와
toleration은 Deployment마다 patch했습니다. chart의 `nodeAffinity`는 모든 역할에 하나이고 toleration이 없으며, `rm-controller`는
prefill과 decode를 특정 노드에 두라고 지정할 수 없습니다(측정된 `tcp` 링크로는 `optimal`이 SLO를 만족하는 2노드 배치를 찾지
못해 `topology`로 물러나고, `topology`는 노드를 고르지 않음). decode는 두 번째 노드의 첫 카드에서 167초에 떴습니다.

**바이트 단위 일치.** `AIRM_KV_TCP_LOG=1`로 요청 33개(1 + 순차 16 + 동시 8로 16): prefill의 push와 decode의 pull에서
**blob 2,112개 모두**(2.215 GB) 크기와 SHA-256이 같습니다. relay의 CRC 오류는 0입니다.

**토큰 단위 일치.** 같은 프롬프트 16개(5–479 토큰, 출력 32 토큰, greedy)를 순차와 동시 8로 보낸 뒤, decode를 RNGD+ATOM
노드로 옮기고 릴리스를 `shm`으로 바꿔(파드 재시작) 다시 보냈습니다: **출력 32/32개가 텍스트와 토큰 수 모두 같습니다**.

**서빙 중 요청당 시간** (rngd-pd 게이트웨이 `pd` 시간, 프롬프트 16개. save = prefill 계산 뒤에도 남은 push, load = decode
admission 때의 pull):

| | NPU→NPU `tcp`, 서버는 decode 옆 | CPU relay 노드 경유 (2026-10-19) | `shm`, 한 노드 (같은 날) |
|---|--:|--:|--:|
| 순차: KV save p50 / p90 | 758 / 795 ms | 678 / 724 ms | 1.6 / 6.7 ms |
| 순차: admission 때 KV load p50 / p90 | **242 / 272 ms** | 816 / 896 ms | 28 / 42 ms |
| 순차: 서버 TTFT p50 / p90 | 844 / 900 ms | 778 / 839 ms | 97 / 128 ms |
| 동시 8: KV save p50 / p90 | 3,527 / 4,252 ms | 3,266 / 4,304 ms | 1.9 / 7.1 ms |
| 동시 8: KV load p50 / p90 | **295 / 340 ms** | 1,305 / 1,378 ms | 35 / 43 ms |
| 동시 8: 서버 TTFT p50 / p90 | 3,738 / 4,764 ms | 3,330 / 4,766 ms | 407 / 821 ms |

**링크 측정** (`bench/kv_tcp_bench.py`, S=512 모양의 bf16 KV, 단계마다 요청 8개, 모든 단계에서 바이트 단위 일치):

| | 동시 1개 | 동시 8개, 양방향 |
|---|--:|--:|
| 호스트: 두 노드 모두 1 GbE NIC(두 번째 노드의 포트는 1 Gb/s로 연결, 다른 포트는 링크 없음), RTT 0.175 ms, 원시 TCP | 방향마다 0.1176 GB/s | 방향마다 0.117 GB/s |
| prefill 파드 → 두 번째 NPU 노드의 relay → 다시 prefill 파드(두 구간 모두 링크를 건넘) | push 768 ms(0.087 GB/s), pull 824 ms(0.081 GB/s) | 0.119 GB/s |
| decode 파드 → 같은 노드의 relay(로컬) | push 120 ms(0.56 GB/s), pull 153 ms(0.44 GB/s) | 1.67 GB/s |

노드 간 수치는 CPU relay 실행과 2 % 안에서 같으므로 `tcp` 프로파일(0.08 GB/s, 14 ms)은 NPU 간 풀에도 맞고 `profiles.yaml`은
바꾸지 않았습니다. 서버를 decode 옆에 두면 네트워크 구간 둘 중 하나가 빠집니다. admission마다 decode 루프가 기다리는 load가
~0.8초에서 ~0.25초(로컬 구간과 역직렬화)로 줄고, TTFT를 정하는 push는 그대로입니다.

**그 위의 실제 트레이스.** Azure 대화 ×0.5(요청 212개, 0.71 req/s). 먼저 파드 재시작(`AIRM_KV_TCP_LOG=0`), `pd-smoke`
warm-up, 전력은 Prometheus에서 사용 중인 카드 두 장(한 노드의 prefill 카드, 다른 노드의 decode 카드):

| 배포 | 카드 | SLO 달성률 | TTFT p90 | TPOT p90 | Goodput req/s | 카드당 | 전력 W (최대) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD, **decode는 두 번째 NPU 노드**, KV `tcp`, 서버는 decode 옆 | 2 | **96.7 %** | 1,673 ms | 40.5 ms | 0.68 | 0.34 | 148.1 (166) | 0.60 |
| PD 1P+1D RNGD, CPU relay 노드를 거친 KV `tcp` (2026-10-19) | 2 | 89.2 % | 1,727 ms | 83.3 ms | 0.62 | 0.31 | 151.7 (165) | 0.59 |
| PD 1P+1D RNGD, 한 노드, KV `shm` (같은 날, 같은 릴리스) | 2 | 100.0 % | 151 ms | 33.8 ms | 0.70 | 0.35 | 156.7 (171) | 0.57 |
| PD 1P+1D RNGD, 한 노드, KV `shm` (W7) | 2 | 100.0 % | 246 ms | 33.1 ms | 0.70 | 0.35 | 155.9 (176) | 0.57 |

모든 실행에서 요청 212개가 모두 끝났습니다. Issue의 가설(달성률이 relay의 89.2 % 근처)은 TPOT 쪽에서 반박됩니다. pull이 로컬이라
admission마다 decode 루프가 ~0.8초 대신 ~0.25초 멈추고, TPOT p90이 83 ms에서 40 ms로 내려갑니다. 남은 미달(212개 중 7개)은
TTFT로, 트레이스의 burst에서 0.76초 push와 그 뒤의 대기가 2초 SLO에 닿습니다. `pd-smoke`(4초에 요청 32개)는 여전히 TTFT p90
16.7초입니다: 8 req/s × 67 MB는 링크의 4.6배입니다. tok/J는 잡음 안에서 같습니다(0.60 대 0.57).

**시뮬레이터와 비교.** 측정 프로파일로 `rm_controller.sim.simulate`, 이 배치(한 노드의 P 1 RNGD, 다른 노드의 D 1 RNGD,
`tcp`), 재생한 요청의 길이 분위수(입력 p50/p90 203/399, 출력 132/217), 0.71 req/s: 달성률 100 %, TTFT p90 983 ms, TPOT p90
30 ms(한 노드 `shm` 배치는 100 %, 172 ms, 30 ms). SLO 안의 최고 rate는 1.57 req/s, 한 노드는 1.76입니다. 측정값: 96.7 %,
1,673 ms, 40.5 ms. relay 실행 때처럼 시뮬레이터가 낙관적입니다. 도착이 트레이스의 burst보다 고르고, 요청마다 KV 시간을 한 번
(0.85초) 매기지만 실제로는 push가 링크에서 서로 뒤에 줄을 서며, 재생에서 admission load를 TPOT에 넣지 않습니다. push(네트워크)와
admission load(로컬, 여기서는 ~0.25초)를 나누는 링크 모델이면 이 배치를 설명할 수 있습니다. 그 변경은 여기서 하지 않았습니다.

**같은 날 첫 시도(00:00 UTC): 막힘.** 다른 프로젝트가 두 번째 노드의 호스트에서 직접 돌린 학습 프로세스 두 개가 decode 파드가
시작되기 1분 전에 그 노드의 RNGD 카드 두 장을 열었고, decode는 `Npu npu0pe0-3: EBUSY`로 실패했습니다. device plugin은 여전히
두 카드를 비어 있다고 알렸습니다. 그 시도는 링크만 쟀고(위 수치와 1 % 안에서 같음) 중단·정리했습니다. 이번 실행에서는 rm-accel
v0.5.0이 그런 카드를 표시합니다(`airm.ai-computing.io/host-held`). 시작 때 label은 0이었지만 호스트 프로세스 하나가 08:13:59 UTC부터
두 번째 카드를 잡고 있었습니다(label은 2분 안에 따라잡았고 그 프로세스는 08:23에 끝남). decode 파드는 비어 있는 카드를
받았습니다. Kubernetes 밖의 카드 사용은 rm-accel에서 추적합니다.

NIXL: NPU 노드에 설치된 `nixl_cu12` wheel에는 `libplugin_UCX.so`가 있고 `UCX_TLS=tcp`로 UCX agent가 생성되지만, 여기서
NIXL-over-UCX KV 경로를 만들거나 재지는 않았습니다. rngd-pd의 `nixl` 전송은 같은 호스트의 HETERO_NPU 경로 그대로입니다
([rngd-pd#8](https://github.com/ai-computing/rngd-pd/pull/8)).

## 주의할 점

- **노드 하나, 엔진 한 세대.** RNGD 3장과 ATOM 4장, S=512 그래프, batch 최대 8(RNGD)과 4(ATOM). 트레이스는 511 토큰에 들어가는
  요청만 남겼으므로(재생 구간에서 대화 2,872개 중 698개, 코드 1,491개 중 366개) 짧은 문맥의 결과입니다.
- **작은 실행.** 300초 일정에 요청 212–455개(트레이스의 처음 몇 분), 칸마다 한 번. 몇 % 차이는 실행 간 잡음 안입니다. 대화 ×1은
  네 배치를 3–5번씩 반복했습니다([반복 실행](#반복-실행-2026-10-2021-43)). 거기서 PD 1P+1D는 몇 %가 아니라 25.5–98.0 %로 흔들리고,
  다른 배치는 0–9 %p 안입니다.
- **클라이언트 관점.** `--api completions`는 스트리밍이 아닙니다. TTFT는 서버 시간에서 유도하므로 decode lane 대기를 포함하지 않고,
  그 대기는 TPOT에 나타납니다(스트리밍은 aicomp#41).
- **전력**은 exporter의 카드 전력을 Prometheus 마지막 수집값에서 1초마다 읽은 것입니다. 호스트 CPU·메모리와 구성 밖의 유휴 카드는
  빠졌습니다. `solo` ×3은 바쁜 카드 3장, PD 1P+1D는 2장입니다.
- **공유 노드.** 다른 에이전트가 Kubernetes 밖 호스트에서 RNGD 한 장과 ATOM 한 장으로 NIXL 전송 벤치마크를 돌렸습니다. 그 RNGD를
  할당받은 첫 prefill 파드는 `EBUSY`로 실패했고 벤치마크가 끝난 뒤 다시 돌렸습니다. ATOM 전력 조회의 카드는 `rbln-stat`(사용 중인
  메모리)로 정했습니다.
- **라우팅.** rngd-pd 게이트웨이 하나 뒤의 여러 prefill·decode 파드와 `solo` replica는 Kubernetes Service(연결 단위 분산)로
  닿습니다. 부하를 보는 라우팅은 없었습니다.
- **실행하지 않음:** ATOM prefill, 실제 서빙에서 `p2p`·`nixl` 전송(`nixl`은 서빙 밖에서 바이트·토큰 일치를 확인,
  [rngd-pd#8](https://github.com/ai-computing/rngd-pd/pull/8)), B > 8 RNGD decode, GPU(같은 예산의 A100 행은
  A100이 비기를 기다림, [반복 실행](#반복-실행-2026-10-2021-43) 참고).
- **벤더 행**은 클라이언트 API(스트리밍 completions)와 엔진 기본값(prefix caching 켜짐)이 다릅니다. 표의 각주 참고. rngd-pd 행 뒤에 같은
  카드에서 같은 날 오후에 돌렸습니다.
- **W2 실행**도 한 번씩입니다. 멀티 풀 부하는 두 풀 모두 클라이언트 호스트 하나에서 보냈습니다. 노드 간 경로는 세 번째 노드의
  relay를 거쳤고(요청마다 네트워크 구간 둘, 서버가 decode 옆이면 하나), 링크는 1 GbE, 두 NPU 워커는 한 NPU 노드에 있었습니다.
  두 번째 NPU 노드가 cordon 상태였기 때문입니다. 2026-10-20 NPU 간 실행은 런타임을 실행용으로 복사한 두 번째 NPU 노드를
  썼습니다. 그 22 GB 때문에 노드 디스크가 kubelet 축출 임계에 한 번 닿았습니다(08:20 UTC DiskPressure, 그 노드에서 축출된
  것은 없이 풀림). 이런 실행에 쓸 노드에는 런타임을 설치하거나(또는 런타임을 담은 이미지) 두어야 합니다.
- **재조정기 실행**은 한 번의 순서(코드 ×3, 대화 ×2, 코드 ×3)이고 일부러 용량을 넘겼습니다. 첫 대화 구간은 옛 TPOT 지표로 돌았으며
  그 발견을 위해서만 보고합니다.

## 클러스터에서 바꾼 것

| 대상 | 변경 | 남긴 상태 |
|---|---|---|
| `llm-serving/airm-e2e` (Helm) | rngd-pd `main` chart와 이 값으로 upgrade(`--chip` 고정 없음, decode B=8 continuous, #5를 넣은 rngd-pd 클론을 `/app`에), prefill·decode에 `--apply`용 annotation, 게이트웨이 env `PD_PREFETCH=0`, replicas는 `--apply`와 `kubectl scale`, 실행 사이 재시작 | Deployment 모두 0으로 scale, 이전 값 저장 |
| `llm-serving/airm-placement` | `rm-controller` generation 2(P 2 / D 1), 이어서 3(P 1 / D 2, 보정 프로파일) | generation 3(이전 `manual` 문서 저장) |
| `airm-exp-solo`, `airm-exp-solo-gw` (Deployment, Service) | 복제 실행용으로 생성 | 삭제 |
| `llm-serving/airm-exp-hetero` (Helm) | RNGD prefill + ATOM decode 릴리스 | uninstall |
| `airm-exp-flm` (Deployment, Service) | 벤더 기준선용 furiosa-llm replica, 모델 캐시는 `/var/tmp` 아래 hostPath | 삭제, 캐시 디렉터리 제거 |
| `airm-exp-flm-probe`, `airm-exp-cleanup` (Pod) | furiosa-llm CLI·패키지 확인, 캐시 제거 | 삭제 |
| `llm-serving/airm-e2e` (재조정기 실행) | 게이트웨이를 1로 scale, `PD_PREFETCH=0`, 후반에는 rngd-pd#7을 넣은 이 실행의 rngd-pd 체크아웃을 `/app`에 마운트. prefill·decode replica, affinity, `accelerator-ids`, generation annotation은 `--apply`가 patch(generation 4–7), 파드 한 번 재시작 | 모두 0으로 scale, 게이트웨이 마운트와 `PD_PREFETCH=1` 복원, annotation은 generation 3의 카드로 복원 |
| `llm-serving/airm-placement` | 재조정기가 generation 4–7 기록 | generation 3 문서를 바이트 그대로 복원 |
| `llm-serving/airm-e2e`, `airm-placement` (예측 규칙 재확인, 17:37–18:30 UTC) | 재조정기 실행과 같음: 게이트웨이 1, `PD_PREFETCH=0`, rngd-pd#7 체크아웃을 `/app`에. `--apply`로 generation 4(2P+1D), 5(1P+2D) | 저장한 객체로 Deployment와 ConfigMap을 replace(모두 0 replicas, generation 3 문서 바이트 그대로) |
| `airm-exp-nixl-check` (Pod) | `nixl` 전송 검사용 RNGD 2장 + ATOM 1장(rngd-pd#8) | 삭제 |
| `llm-serving/airm-e2e` (W2 멀티 풀, 19:10–19:50 UTC) | 게이트웨이를 1로 scale, `PD_PREFETCH=0`. decode에 `accelerator: furiosa.RNGD` annotation. prefill·decode replica, affinity, annotation은 `--apply`가 patch(generation 4, 5), prefill·decode 파드 한 번 재시작 | 저장한 객체로 Deployment와 `airm-placement`를 replace(모두 0 replicas, generation 3 문서 바이트 그대로) |
| `airm-exp-qwen` (Deployment, Service) | 두 번째 풀의 furiosa-llm Qwen3-4B-FP8, `serve-furiosa-ai-qwen3-4b-fp8`(읽기만 함)의 복사본. 모델 캐시는 `/var/tmp` 아래 hostPath(5.4 GB) | 삭제, 캐시 제거(`airm-exp-cleanup` Pod, 삭제) |
| `airm-exp-decode-atom` (Deployment) | Llama 풀의 ATOM decode, generation 5로의 이동 | 삭제 |
| `llm-serving/airm-exp-xnode` (Helm) | rngd-pd#9의 rngd-pd chart: NPU 노드의 RNGD prefill + RNGD decode, CPU 전용 노드의 `kvRelay` 파드, 자체 게이트웨이 Service. `tcp`와 `shm` 사이를 바꾸고 실행 사이 재시작 | uninstall |
| 두 번째 RNGD 노드 (2026-10-19 23:55 – 10-20 00:08 UTC, 막힘; 2026-10-20 08:17–08:44 UTC, NPU 간 실행) | taint `airm.ai-computing.io/experiment=true:NoSchedule` 후 uncordon, 끝에 다시 cordon | taint 제거, cordon: spec·label·annotation이 기록한 것과 같음(`unschedulable` taint의 `timeAdded`만 새 값) |
| `llm-serving/airm-exp-xnode` (Helm, 2026-10-20, 두 번) | prefill + 게이트웨이는 RNGD+ATOM 노드, decode + `kvRelay`는 두 번째 RNGD 노드(affinity와 toleration은 Deployment마다 patch). `shm` 비교에서는 decode를 RNGD+ATOM 노드로 옮기고 `AIRM_KV_TRANSPORT=shm`, 실행 사이 재시작 | uninstall |
| `airm-exp-xnode-probe`, `-xfer`, `-cleanup` (Pod), `airm-exp-xnode-xfer` (ConfigMap) | 읽기 전용 호스트 확인, 링크 측정, 두 번째 RNGD 노드의 `/var/tmp`로 워커 런타임 복사와 그 삭제 | 삭제, 두 노드의 임시 디렉터리 제거 |
| `llm-serving/airm-e2e` (반복 실행, 2026-10-20 09:16 – 10-21 02:06 UTC) | 게이트웨이 env `PD_PREFETCH=0`. prefill/decode/게이트웨이를 실행마다 1/1/1 또는 1/2/1로 scale하고 다시 0으로. 호스트가 잡은 카드에 올라간 파드는 실행 전에 삭제(10-21). 제어 호스트에 닿지 못한 동안(10-20 10:54 – 10-21 00:00 UTC) 1P+2D 파드가 떠 있었고 리드가 0으로 scale | 실행 전에 저장한 객체로 Deployment를 replace(모두 0 replicas, `PD_PREFETCH=1`). `airm-placement`는 건드리지 않음(generation 3, 바이트 그대로) |
| `airm-exp-solo`, `airm-exp-solo-gw`, `airm-exp-flm` (Deployment, Service, 반복 실행) | W7 manifest로 실행마다 다시 생성 | 삭제, `/var/tmp` 아래 furiosa-llm 모델 캐시 제거(`airm-exp-cleanup` Pod, 삭제) |
| `vllm-a100-llama31-8b` | 상태 기록(0 replicas). A100을 다른 프로젝트가 쓰고 있어 scale하지 않음 | 그대로 |

다른 Deployment나 EPP는 건드리지 않았고, 2026-10-20 실행(마지막 행들)을 빼면 어떤 노드도 cordon·uncordon하거나 이름으로 지정하지 않았습니다. cordon된 RNGD
노드는 그대로였고 그 위에는 아무것도 스케줄하지 않았습니다. 원시 결과는(`results/`는 이 저장소에서 추적하지 않음) 노드의 실험 로그와 함께
있습니다.

## 재현

```bash
# W5: 배치와 적용 (Deployment에 airm.ai-computing.io/pool, /role annotation)
rm-controller --spec packages/rm-controller/examples/optimal.yaml --once --apply
rm-bench e2e --scenario pd-smoke --api completions --gateway http://<llm-d gateway>/rngd/llama8b-pd/completions

# W7: 한 칸 (구성의 게이트웨이 Service, 먼저 파드 재시작)
rm-bench e2e --scenario <SLO 2 s / 100 ms인 대화 시나리오> --api completions --gateway http://<gateway> \
  --speedup 1 --max-total-tokens 511 --duration 300 --deployment pd-1p1d-rngd --cards 2 \
  --power prom --power-url http://<prometheus> \
  --power-query 'sum(furiosa_npu_hw_power{label="rms",device=~"npu0|npu1"})'
rm-bench compare results/*.json

# W7 벤더: Service 하나 뒤 furiosa-llm replica(각 카드 한 장), 스트리밍 completions
rm-bench e2e --scenario <대화 시나리오> --api completions-stream --gateway http://<furiosa-llm service>:8000   --speedup 1 --max-total-tokens 511 --duration 300 --deployment flm-agg-x2-rngd --cards 2 --power prom ...

# W7 반복: 실행마다 새 파드, 워밍업은 pd-smoke와 유휴 측정 둘 다(측정 없이 차가운 rngd-pd 파드는 풀리지 않는 backlog로
# 실행을 시작할 수 있음). 배치를 섞어 돌리고 실행들의 평균 ± 표준편차를 보고
# A100 행(아직 실행 안 함): vllm-a100-llama31-8b를 replica 1과 2로, --api completions-stream,
#   --power-query 'sum(DCGM_FI_DEV_POWER_USAGE{gpu=~"<사용 중인 GPU>"})'

# W5 재조정기: --apply 루프, 그리고 rngd-pd 게이트웨이로 부하 구성을 번갈아
rm-controller --spec packages/rm-controller/examples/rebalance-gateway.yaml --rebalance --apply --interval 60
rm-bench e2e --scenario <코드 시나리오> --api completions --speedup 3 ...    # 다음은 대화 --speedup 2

python -m rm_controller.sim --episode     # 같은 에피소드 재생, 선형 규칙 대 예측 규칙

# W6: 실행과 비교한 시뮬레이션, README 표
python -m rm_controller.sim --compare --requests 4000

# W2 멀티 풀: 풀 둘(PD + aggregated serve), Deployment에 pool/role annotation. 이어서 풀 하나만 바꾸고 다시 실행
rm-controller --spec packages/rm-controller/examples/multi-pool.yaml --once --apply
rm-bench e2e ... --gateway http://<llm-d gateway>/rngd/llama8b-pd/completions --api completions &        # 둘을 동시에
rm-bench e2e ... --gateway http://<qwen service>:8000 --model furiosa-ai/Qwen3-4B-FP8 --api completions-stream &

# W2 노드 간 KV: CPU 노드에 relay를 둔 rngd-pd chart (rngd-pd#9)
helm install <release> deploy/helm/rngd-pd -f <site values> --set airm.kvTransport=tcp --set kvRelay.enabled=true \
  --set kvRelay.nodeSelector.kubernetes\\.io/hostname=<cpu node> --set env.AIRM_KV_TCP_LOG=1    # 감사 로그: blob마다 크기 + sha256
python bench/kv_tcp_bench.py --server <release>-kv-relay:5577 --concurrency 1,2,4,8     # prefill 파드 안에서
# 2026-10-20: decode와 relay를 두 번째 RNGD 노드에(kvRelay.nodeSelector, 임시 taint용 toleration은 decode와 relay
# Deployment에 patch). 같은 벤치가 NPU 노드 간 링크를 잰다
```
