# 실제 클러스터 end-to-end 실행

[문서](README.md) · [English](../e2e.md) · [현재 상태](status.md)

2026-10-19, 모든 계층을 Kubernetes + llm-d 클러스터에서 처음으로 함께 실행했습니다. L1이 탐지한 장치가 L3 서빙 파드를
배치하고, 요청은 llm-d 게이트웨이와 EPP로 들어오며, KV는 이름으로 고른 L2 전송으로 이동하고, L5가 rm-core 이름만으로
측정·표시합니다.

**범위.** Llama-3.1-8B-Instruct, 한 노드에서 RNGD prefill + RNGD decode, KV는 `shm`, 역할별 1개(배치 1). 연결을
확인하는 smoke 워크로드이며 성능 벤치마크가 아닙니다. Optimus Prime 엔진은 포함하지 않았습니다.

## 실행 구성

| 계층 | 구성요소 (고정 버전) | 클러스터에서 |
|---|---|---|
| L1 | rm-accel v0.4.1, chart 0.4.2 | DaemonSet `airm-system/rm-abstract-node`. etri-001에 `AcceleratorProfile` 7개(RNGD 3 + ATOM 4), etri-esc8000-e11에 2개. 노드 레이블 `airm.ai-computing.io/<vendor>.<model>` |
| L4 | hetero-llm-d | CRD v0.1.1, `ScrapeConfig airm-pods`, `airm-placement` ConfigMap, airm 대시보드. 기존 Gateway → `llama8b-pd-pool` → EPP |
| L3 | rngd-pd | 릴리스 `airm-e2e`: 게이트웨이(`app: llama8b-pd`로 풀에 합류), RNGD 0에 prefill, RNGD 1에 decode. 파드는 L1 레이블(`furiosa.RNGD`와 `rebellions.ATOM`이 모두 있는 노드)로 배치 |
| L2 | rngd-pd `shm` 전송 (`airm.kv_transports:shm`) | 8B 요청당 KV 67 MB가 `/dev/shm`으로 이동 |
| L5 | rm-bench, lmd-top | llm-d 게이트웨이를 거쳐 `rm-bench e2e --scenario pd-smoke --api completions`. lmd-top Infra ▸ Devices에 프로파일·`airm_*`·배치 표시 |

## 결과

`pd-smoke`: 요청 32개(poisson 8 rps, 동시성 8, 프롬프트 16–128 토큰, 출력 16 토큰).

| 관점 | TTFT p90 | TPOT p90 | 처리량 | KV 전송 p90 | SLO |
|---|---|---|---|---|---|
| 클라이언트 (rm-bench, llm-d 경유) | 2350 ms | 208 ms | 53.9 tok/s | — | PASS, 32/32 |
| 서버 (PD 게이트웨이 `airm_*`, Prometheus) | 282 ms | 19.5 ms | — | 112 ms | — |

클라이언트 수치에는 대기가 포함됩니다. 동시 요청 8개가 한 번에 하나씩 처리하는 배치에 몰리므로, 사용자가 겪는 지연은
prefill·decode 자체보다 대기가 대부분입니다. 단일 요청 "The three primary colors are"에 " red, blue, and yellow. …"로
응답했습니다(cold TTFT 1.7 s, TPOT 15.8 ms).

## 실제 트레이스

rm-bench로 공개 운영 트레이스를 실제 도착 시각·길이 그대로 재생합니다(`rm-bench traces fetch`, 데이터는 저장소에 넣지 않음).
트레이스 특성 전체와 각 트레이스가 NPU 환경에 요구하는 것은 [워크로드 트레이스](workload-traces.md)에 정리했습니다.

| 트레이스 (전체) | 요청 | 평균 / 60초 피크 rps | 입력 p50 / p90 | 출력 p50 | prefix 블록 재사용 | S=512에 맞는 비율 |
|---|---|---|---|---|---|---|
| Azure 2023 대화 | 19,366 / 1시간 | 5.5 / 8.5 | 1041 / 2221 | 217 | — | 32 % |
| Azure 2023 코드 | 8,819 / 1시간 | 2.6 / 10.5 | 1425 / 5479 | 13 | — | 22 % |
| BurstGPT (실패 제외 1) | 140만 / 61일 | 0.27 / 18.3 | 472 / 1360 | 362 | — | 62 % |
| Mooncake 대화 | 12,031 / 1시간 | 3.4 / 4.1 | 8039 / 30220 | 364 | 28 % | 0 % |
| Mooncake tool-agent | 23,608 / 1시간 | 6.7 / 7.8 | 6402 / 18998 | 30 | 49 % | 0 % |

S=512로 컴파일한 RNGD PD는 실제 대화 트래픽의 1/4–1/3만 처리할 수 있고 Mooncake의 긴 문맥 요청은 처리하지 못합니다.
실제 길이로 평가하려면 더 긴 시퀀스로 컴파일해야 합니다.

**PD 경로에서 Azure 대화 재생** (트레이스 처음 120초, 입력+출력 ≤ 511인 요청만(33 %), PD 한 쌍에 맞게 시간을 5배 늘림:
600초 동안 152개, 평균 0.25 rps, 피크 0.33):

| 관점 | TTFT p90 | TPOT p90 | 처리량 | KV 전송 p90 | 결과 |
|---|---|---|---|---|---|
| 클라이언트 (rm-bench, llm-d 경유) | 188 ms | 78.9 ms | 34.0 tok/s | — | SLO PASS, 오류 0, 요청의 97.4 %가 SLO 충족 |
| 서버 (PD 게이트웨이 `airm_*`) | 179 ms (구간 최대 1535 ms) | 17.3 ms | — | 111 ms | — |

이 속도에서는 클라이언트 TTFT가 서버와 같지만 클라이언트 TPOT은 서버의 4–5배입니다. 실제 도착이 겹치면 요청이 하나뿐인 decode를
기다리는데, 서버의 토큰당 수치에는 이 대기가 보이지 않습니다. 실행 중 burst 구간에서는 서버 TTFT p90도 1.5초까지 올라갑니다.

## 실행 중 발견·수정한 문제

| 계층 | 발견 | 수정 |
|---|---|---|
| L1 | `rbln-stat`이 장치 그룹마다 NPU 번호를 다시 매겨 ATOM 4개 노드를 2개로 보고 | rm-accel 0.4.1: `rbln<N>`에서 번호 |
| L1 | 읽기 전용 루트에서 `rbln-stat`이 풀리지 못해 ATOM 미게시 | chart 0.4.2: 쓰기 가능한 `/tmp` |
| L1 | 파드가 ATOM을 반납한 뒤 드라이버가 다시 만든 장치가 데몬의 `/dev`에서 사라짐 | chart 0.4.2: `hostDev`로 호스트 `/dev`를 실시간 마운트(할당·반납 재현으로 확인) |
| L3↔L5 | PD 게이트웨이는 스트리밍 없는 `/v1/completions`만 제공, rm-bench는 스트리밍 chat만 전송 | rm-bench `--api completions`, 서버가 보낸 시간으로 TTFT 계산 |
| L4↔L5 | hetero-llm-d는 `airm-placement`를 `decisions.json` 목록으로 문서화, lmd-top은 워크로드별 키를 `llm-d` 네임스페이스에서 읽음 | lmd-top이 두 형식을 모두 읽고 `LMD_AIRM_NS` 기본값을 `LMD_NS`로 |

## 다음 실행의 측정 (벤치마크 표면과 에너지)

이를 쓴 첫 실행(컨트롤러가 적용한 배치, 같은 예산의 기준선과 에너지): [기준선](baselines.md).

rm-bench는 이 스모크 테스트 이후 실행에 필요한 측정을 갖췄습니다
([packages/rm-bench](../../packages/rm-bench/README.ko.md#-에너지-표준-벤치마크-기준선-비교)):

- **PD 경로의 스트리밍 chat.** `--api chat`은 SSE chunk로 TTFT, TPOT, ITL을 잽니다(usage chunk, `[DONE]`, 비스트리밍 응답
  대응). 엔진이 스트리밍 chat을 제공하면(aicomp#41) PD 경로에서 `--api completions` 대신 씁니다. 그 전까지 PD 경로의 클라이언트
  TTFT는 서버 시간에서 계산합니다.
- **모든 실행에 에너지.** `--power prom`(DCGM 또는 NPU exporter query)이나 `--power cmd`(furiosa-smi처럼 와트를 출력하는 CLI)로
  실행마다 `scope`가 붙은 `power_w`/`energy_j`, 최대 W, tok/J를 남깁니다. 클러스터에서는 아직 돌려 보지 않았습니다.
- **표준 벤치마크.** `rm-bench import guidellm|mlperf`로 GuideLLM sweep과 MLPerf LoadGen(llama3.1-8b Server) 결과를 같은
  Measurement로 바꿔 같은 표에 넣습니다.
- **기준선.** `rm-bench compare`는 `--deployment`(같은 vendor PD, vendor 간 PD, 복제)로 라벨을 붙인 실행들의 SLO 달성률, 카드당
  goodput, tok/J를 한 표로 만듭니다.

## 남은 과제

- **배치는 수동입니다.** `airm-placement`를 쓰는 컨트롤러가 없어 이번에는 실제 배치를 `placement: "manual"`로 기록했습니다.
  참조 `greedy` 정책을 실제 프로파일에 돌리면 prefill과 decode를 cordon된 노드의 같은 카드에 `loopback`으로 둡니다. 실제
  컨트롤러는 `shm`일 때 P·D를 같은 노드에, 서로 다른 카드에 두고, cordon/NotReady 노드를 피하며 실제 전송을 골라야 합니다.
- ~~**배치 ConfigMap 형식이 rm-core에 없습니다.**~~ 해결: PROTOCOL.md §5.4와 `rm_core.placement`(rm-core v0.1.2)가
  `decisions.json` 문서를 규범으로 정했습니다.
- ~~**rngd-pd 카드 선택.**~~ 해결(rngd-pd #3): `--chip -1`이 kubelet device-plugin 체크포인트에서 파드의 할당을 읽으므로,
  모든 카드를 보는 privileged 파드도 할당받은 카드를 씁니다. 노드에서 확인: 카드 0·1·3이 보이는 상태에서 다른 파드가
  0번을 쓰는 동안 privileged 파드가 할당받은 1번을 골랐습니다.
- **chart 기본값.** rngd-pd decode 기본은 ATOM이며, map 병합으로 RNGD로 덮어쓰면 ATOM 요청이 남습니다(`rebellions.ai/ATOM: null`로 제거).
- **확인하지 않은 것:** RNGD→ATOM decode, 실제 버퍼 `p2p` 전송, GPU 노드(데몬 이미지에 `nvidia-smi` 없음), 배치 처리. 실행 중
  일부 노드는 NotReady, cordon 또는 디스크 부족 상태였습니다.

## 재현

사이트 값은 `deploy/clusters/<name>/`(추적 안 함)에 둡니다. [`deploy/clusters/example/`](../../deploy/clusters/example/)의
예시에서 시작해 `/path/to/...` 호스트 경로를 바꾸세요. 명령은 [영문 문서](../e2e.md#reproduce)와 같습니다.
