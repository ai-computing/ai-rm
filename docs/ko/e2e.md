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
| L1 | rm_abstract_layer v0.4.1, chart 0.4.2 | DaemonSet `airm-system/rm-abstract-node`. npu-node-1에 `AcceleratorProfile` 7개(RNGD 3 + ATOM 4), npu-node-2에 2개. 노드 레이블 `airm.ai-computing.io/<vendor>.<model>` |
| L4 | llm-d-setup | CRD v0.1.1, `ScrapeConfig airm-pods`, `airm-placement` ConfigMap, airm 대시보드. 기존 Gateway → `llama8b-pd-pool` → EPP |
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

## 실행 중 발견·수정한 문제

| 계층 | 발견 | 수정 |
|---|---|---|
| L1 | `rbln-stat`이 장치 그룹마다 NPU 번호를 다시 매겨 ATOM 4개 노드를 2개로 보고 | rm_abstract_layer 0.4.1: `rbln<N>`에서 번호 |
| L1 | 읽기 전용 루트에서 `rbln-stat`이 풀리지 못해 ATOM 미게시 | chart 0.4.2: 쓰기 가능한 `/tmp` |
| L1 | 파드가 ATOM을 반납한 뒤 드라이버가 다시 만든 장치가 데몬의 `/dev`에서 사라짐 | chart 0.4.2: `hostDev`로 호스트 `/dev`를 실시간 마운트(할당·반납 재현으로 확인) |
| L3↔L5 | PD 게이트웨이는 스트리밍 없는 `/v1/completions`만 제공, rm-bench는 스트리밍 chat만 전송 | rm-bench `--api completions`, 서버가 보낸 시간으로 TTFT 계산 |
| L4↔L5 | llm-d-setup은 `airm-placement`를 `decisions.json` 목록으로 문서화, lmd-top은 워크로드별 키를 `llm-d` 네임스페이스에서 읽음 | lmd-top이 두 형식을 모두 읽고 `LMD_AIRM_NS` 기본값을 `LMD_NS`로 |

## 남은 과제

- **배치는 수동입니다.** `airm-placement`를 쓰는 컨트롤러가 없어 이번에는 실제 배치를 `placement: "manual"`로 기록했습니다.
  참조 `greedy` 정책을 실제 프로파일에 돌리면 prefill과 decode를 cordon된 노드의 같은 카드에 `loopback`으로 둡니다. 실제
  컨트롤러는 `shm`일 때 P·D를 같은 노드에, 서로 다른 카드에 두고, cordon/NotReady 노드를 피하며 실제 전송을 골라야 합니다.
- **배치 ConfigMap 형식이 rm-core에 없습니다.** PROTOCOL.md §5.2는 `Placement` API만 정의합니다. llm-d-setup의 `decisions.json`
  형식이 사실상 표준이므로 규범으로 올려야 합니다.
- **rngd-pd 카드 선택.** `--chip -1`은 처음 보이는 카드를 쓰는데, `/dev/rngd`를 마운트한 privileged 파드는 모든 카드를 보므로
  카드를 고정하기 전까지 prefill과 decode가 충돌했습니다. device plugin이 할당한 카드를 써야 합니다.
- **chart 기본값.** rngd-pd decode 기본은 ATOM이며, map 병합으로 RNGD로 덮어쓰면 ATOM 요청이 남습니다(`rebellions.ai/ATOM: null`로 제거).
- **확인하지 않은 것:** RNGD→ATOM decode, 실제 버퍼 `p2p` 전송, GPU 노드(데몬 이미지에 `nvidia-smi` 없음), 배치 처리. 실행 중
  일부 노드는 NotReady, cordon 또는 디스크 부족 상태였습니다.

## 재현

사이트 값은 `deploy/clusters/<name>/`(추적 안 함)에 둡니다. [`deploy/clusters/example/`](../../deploy/clusters/example/)의
예시에서 시작해 `/path/to/...` 호스트 경로를 바꾸세요. 명령은 [영문 문서](../e2e.md#reproduce)와 같습니다.
