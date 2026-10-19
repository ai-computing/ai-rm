# RNGD+ATOM 노드의 같은 예산 기준선

[문서](README.md) · [English](../baselines.md) · [end-to-end 실행](e2e.md) · [로드맵](roadmap.md)

로드맵 W5(컨트롤러가 서빙 파드를 배치하고 옮김), W6(`optimal` 정책의 측정 프로파일), W7(에너지를 포함한 같은 예산 기준선)의
실제 증빙입니다. 2026-10-19, RNGD와 ATOM 카드를 함께 가진 노드에서 실행했습니다(시작 시 RNGD 3장·ATOM 4장이 비어 있었고, RNGD가
있는 다른 노드는 cordon 상태).

**범위.** Llama-3.1-8B-Instruct, 현재 rngd-pd가 컴파일한 그래프(S=512), 노드 하나, KV는 `shm`. 실제 트레이스 두 개를 S=512가 처리할
수 있는 요청으로 잘랐고, 실행당 요청 수백 개, 칸마다 한 번씩 실행했습니다. 이 엔진 세대의 기준선이며 하드웨어 성능 주장이
아닙니다.

## 요약

| | 결과 |
|---|---|
| W5 | `rm-controller` `optimal`이 `airm-placement`를 쓰고 `--apply`가 rngd-pd Deployment를 그에 맞췄습니다. 두 번 했습니다(기존 프로파일로 prefill 2 / decode 1 RNGD, 보정한 프로파일로 prefill 1 / decode 2). 파드는 결정한 노드에 결정한 카드 수로 떴고, llm-d 게이트웨이를 거친 `pd-smoke`가 32/32 통과했습니다. 파드가 어느 카드를 받는지는 결정이 아니라 device plugin이 정합니다. |
| W7 | **카드 2장:** 복제(카드 한 장짜리 `solo` 인스턴스 2개)가 카드당 goodput에서 PD 1P+1D를 이깁니다. Azure 대화 1.52 req/s에서 SLO 달성 100 %(카드당 0.75 req/s), 1P+1D는 87.7 %. 줄당 토큰(tok/J)은 1P+1D가 가장 높습니다(1.17 대 0.76). **카드 3장:** 보정한 `optimal` 배치 PD 1P+2D가 두 트레이스 모두 모든 요청에서 SLO를 지켰고(`solo` ×3과 같음) tok/J는 그 1.2배입니다. 기존 프로파일의 선택 2P+1D는 93.6 %와 77.5 %. **RNGD prefill → ATOM decode는 TPOT SLO 100 ms를 지킬 수 없습니다**: ATOM decode 그래프가 토큰당 108 ms입니다. |
| W6 | 프로파일 표가 2배 이상 틀렸습니다. 400 토큰 프롬프트의 RNGD prefill은 예전 유도값의 220 ms가 아니라 100 ms, batch 그래프의 RNGD decode는 batch와 무관하게 토큰당 30 ms(17–24 아님), ATOM decode는 카드 한 장에서 108 ms(두 장에서 40–52 아님). `profiles.yaml`을 측정값으로 바꾸자 `optimal`의 선택이 2P+1D에서 1P+2D로 바뀌었고, 클러스터에서도 1P+2D가 더 좋았습니다(100 % 대 93.6 %, 77.5 %). |
| 발견 | rngd-pd가 할당받은 카드를 호스트 번호로 불렀습니다(`npu3` → `rngd:3`, 범위 밖): [rngd-pd#5](https://github.com/ai-computing/rngd-pd/pull/5)에서 고침. `PD_PREFETCH=1`에서 continuous decode 워커는 대기 요청이 8개를 넘으면 영영 멈춥니다: [rngd-pd#4](https://github.com/ai-computing/rngd-pd/issues/4). Kubernetes 밖의 프로세스가 RNGD 카드 하나를 쓰고 있어, 그 카드를 할당받은 파드가 `EBUSY`로 실패했습니다. |

## 구성

| | |
|---|---|
| 서빙 | rngd-pd `main` + [rngd-pd#5](https://github.com/ai-computing/rngd-pd/pull/5), chart `deploy/helm/rngd-pd`(kubelet 할당에서 카드를 고름, `--chip` 고정 없음) |
| RNGD prefill | `--backend rngd-full --C 512 --group 2`, bucket 32–512 |
| RNGD decode | `--backend rngd --B 8 --group 8 --sched continuous`(continuous batching, lane 8개) |
| ATOM decode | `--backend atom --B 4 --sched continuous`, artifact `decode_S512_B4_lm`(S=512로 컴파일된 최대 batch), 카드 한 장 |
| `solo` | `--role solo --C 512 --group 2 --decode-group 8 --B 8 --sched continuous`: 한 카드에서 prefill과 continuous decode. chart에 `solo` 역할이 없어 같은 이미지·마운트로 최소 Deployment(`airm-exp-solo`)를 만들고, replica N개를 targets 파일(`{model: {solo: <service>}}`)을 쓴 rngd-pd 게이트웨이 하나 뒤에 두었습니다. Service가 요청을 replica에 나눕니다 |
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
| RNGD prefill → ATOM decode | 2 | 0.0 % (455개 중 313개 timeout) | 135,915 ms | 3,390 ms | 0.00 | 0.00 | 92.3 (105) | 0.38 |
| PD 2P+1D RNGD (optimal, 기존 프로파일) | 3 | 93.6 % | 249 ms | 85.4 ms | 1.41 | 0.47 | 200.7 (221) | **0.89** |
| PD 1P+2D RNGD (optimal, 보정) | 3 | **100.0 %** | 336 ms | 38.7 ms | **1.51** | **0.50** | 257.7 (286) | **0.70** |
| 복제: `solo` ×3 RNGD | 3 | 100.0 % | 200 ms | 31.6 ms | 1.51 | 0.50 | 317.0 (372) | 0.57 |

### Azure 코드, ×1 (요청 222개, 0.74 req/s, 짧은 답: p50 14 토큰)

| 구성 | 카드 | SLO 달성 | TTFT p90 | TPOT p90 | Goodput req/s | 카드당 | 전력 W (최대) | tok/J |
|---|--:|--:|--:|--:|--:|--:|--:|--:|
| PD 1P+1D RNGD | 2 | 84.7 % | 281 ms | 143.4 ms | 0.62 | 0.31 | 98.2 (170) | **0.19** |
| 복제: `solo` ×2 RNGD | 2 | **99.5 %** | 181 ms | 58.0 ms | **0.73** | **0.37** | 108.4 (208) | 0.17 |
| RNGD prefill → ATOM decode | 2 | 0.0 % | 239 ms | 4,225 ms | 0.00 | 0.00 | 78.4 (108) | 0.21 |
| PD 2P+1D RNGD (optimal, 기존 프로파일) | 3 | 77.5 % | 793 ms | 195.6 ms | 0.57 | 0.19 | 138.6 (195) | 0.14 |
| PD 1P+2D RNGD (optimal, 보정) | 3 | **100.0 %** | 1,675 ms | 69.2 ms | **0.74** | **0.25** | 144.0 (233) | **0.13** |
| 복제: `solo` ×3 RNGD | 3 | 98.2 % | 185 ms | 47.7 ms | 0.72 | 0.24 | 160.2 (323) | 0.12 |

모든 구성이 같은 요청을 처리했습니다(timeout이 없으면 tok/s 열이 0.1 % 안에서 일치).

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

## 주의할 점

- **노드 하나, 엔진 한 세대.** RNGD 3장과 ATOM 4장, S=512 그래프, batch 최대 8(RNGD)과 4(ATOM). 트레이스는 511 토큰에 들어가는
  요청만 남겼으므로(재생 구간에서 대화 2,872개 중 698개, 코드 1,491개 중 366개) 짧은 문맥의 결과입니다.
- **작은 실행.** 300초 일정에 요청 212–455개(트레이스의 처음 몇 분), 칸마다 한 번, 반복 없음. 몇 % 차이는 실행 간 잡음 안입니다.
- **클라이언트 관점.** `--api completions`는 스트리밍이 아닙니다. TTFT는 서버 시간에서 유도하므로 decode lane 대기를 포함하지 않고,
  그 대기는 TPOT에 나타납니다(스트리밍은 aicomp#41).
- **전력**은 exporter의 카드 전력을 Prometheus 마지막 수집값에서 1초마다 읽은 것입니다. 호스트 CPU·메모리와 구성 밖의 유휴 카드는
  빠졌습니다. `solo` ×3은 바쁜 카드 3장, PD 1P+1D는 2장입니다.
- **공유 노드.** 다른 에이전트가 Kubernetes 밖 호스트에서 RNGD 한 장과 ATOM 한 장으로 NIXL 전송 벤치마크를 돌렸습니다. 그 RNGD를
  할당받은 첫 prefill 파드는 `EBUSY`로 실패했고 벤치마크가 끝난 뒤 다시 돌렸습니다. ATOM 전력 조회의 카드는 `rbln-stat`(사용 중인
  메모리)로 정했습니다.
- **라우팅.** rngd-pd 게이트웨이 하나 뒤의 여러 prefill·decode 파드와 `solo` replica는 Kubernetes Service(연결 단위 분산)로
  닿습니다. 부하를 보는 라우팅은 없었습니다.
- **실행하지 않음:** ATOM prefill, 실제 서빙에서 `p2p` 전송, B > 8 RNGD decode, GPU.

## 클러스터에서 바꾼 것

| 대상 | 변경 | 남긴 상태 |
|---|---|---|
| `llm-serving/airm-e2e` (Helm) | rngd-pd `main` chart와 이 값으로 upgrade(`--chip` 고정 없음, decode B=8 continuous, #5를 넣은 rngd-pd 클론을 `/app`에), prefill·decode에 `--apply`용 annotation, 게이트웨이 env `PD_PREFETCH=0`, replicas는 `--apply`와 `kubectl scale`, 실행 사이 재시작 | Deployment 모두 0으로 scale, 이전 값 저장 |
| `llm-serving/airm-placement` | `rm-controller` generation 2(P 2 / D 1), 이어서 3(P 1 / D 2, 보정 프로파일) | generation 3(이전 `manual` 문서 저장) |
| `airm-exp-solo`, `airm-exp-solo-gw` (Deployment, Service) | 복제 실행용으로 생성 | 삭제 |
| `llm-serving/airm-exp-hetero` (Helm) | RNGD prefill + ATOM decode 릴리스 | uninstall |

다른 Deployment나 EPP는 건드리지 않았습니다. 원시 결과는(`results/`는 이 저장소에서 추적하지 않음) 노드의 실험 로그와 함께
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

# W6: 실행과 비교한 시뮬레이션, README 표
python -m rm_controller.sim --compare --requests 4000
```
