# 아키텍처

## 목표

서로 다른 벤더의 가속기(GPU, FuriosaAI RNGD, Rebellions ATOM, CPU)와 통합메모리 시스템(GB10)을
하나의 클러스터 자원으로 다루고, LLM 요청과 학습 작업을 그 위에 효율적으로 배치·실행·관측한다.
기본 실행 환경은 Kubernetes + llm-d이며, 각 기술은 llm-d가 이미 정해 둔 확장 지점에 붙는다.

## 계층

| 계층 | 책임 | 구성요소 | llm-d / k8s 안의 자리 |
|---|---|---|---|
| L1 가속기 추상화 | 장치 탐지, 장치 능력 모델(메모리·대역폭·정밀도·전력), 엔진 플러그인 | rm_abstract_layer | 노드 레이블·장치 플러그인 정보의 출처, 모델 서버의 실행 엔진 선택 |
| L2 메모리·전송 | 메모리 계층(HBM, 호스트 DRAM, 통합메모리)과 그 사이 데이터 이동 | hetero-npu-p2p, npu-offload, duet | vLLM `KVConnector`, llm-d KV stage, 모델 서버 내부 오프로딩 |
| L3 실행·서빙 | 이종 가속기 위에서 prefill/decode/학습 실행 | rngd-pd, npu-lora | llm-d 모델 서버 pod(ModelService), 학습은 k8s Job |
| L4 클러스터 | 클러스터 구성, 라우팅·배치 정책, 모델 스토어, 모니터링 스택 | llm-d-setup | Gateway, InferencePool, EPP, 공유 모델 스토어, Prometheus/Grafana |
| L5 관측·운영 | 지표·에너지 수집, KPI 측정, 운영 콘솔 | lmd-top, rm-bench | Prometheus/k8s API를 읽는 콘솔, 엔드포인트 부하 생성 |

## 요청 흐름 (PD 분리 서빙 예)

```
client ──► Gateway ──► InferencePool / EPP ─── 배치 정책 (L4)
                              │  어느 가속기에 prefill/decode를 둘지
                 ┌────────────┴────────────┐
           prefill pod (RNGD)         decode pod (ATOM)        ← L3 rngd-pd
                 │   KV cache                ▲
                 └──── KVTransport (L2) ─────┘                  ← hetero-npu-p2p (P2P) 또는 host staging
                              │
                       지표: TTFT, TPOT, tok/s, W  ──► Prometheus ──► lmd-top / rm-bench (L5)
```

- L1은 각 pod가 쓰는 장치의 능력(메모리, 정밀도, peak 연산, 전력)을 제공하고, L4 배치 정책은 이 정보로 결정한다.
- L2는 계층 사이 데이터 이동을 맡는다. 같은 계약(`KVTransport`/`MemoryTier`) 아래에
  NPU↔NPU P2P(hetero-npu-p2p), NPU↔Host 오프로딩(npu-offload), CPU↔GPU 통합메모리(duet)가 들어간다.
- 모든 계층은 같은 이름·단위의 지표(`Metrics`)를 내보내고, L5와 연구 기록(MLflow)이 그것을 모은다.

## 저장소 구성 원칙

- **라이브러리와 연구 코드를 나눈다.** 다른 구성요소가 가져다 쓰는 것은 버전 태그·테스트·문서를 갖춘 라이브러리
  repo로, 실험 스크립트와 기록은 연구 repo에 둔다. 검증된 부분만 라이브러리로 올린다.
- **계약으로 묶는다.** 구성요소를 한 repo로 합치지 않는다. [interfaces.md](interfaces.md)의 계약을 구현하고,
  [component-contract.md](component-contract.md)의 `ai-rm.yaml`로 자신을 선언한다.
- **버전 조합은 ai-rm이 고정한다.** 서브모듈 커밋이 "이 시점의 통합 버전"이다. 릴리스할 때 ai-rm에 태그를 붙인다.
- **사이트 값은 코드 밖에 둔다.** 주소·자격 증명은 추적되지 않는 `cluster.local.env`에서 읽는다.

## 현재 상태와 다음 단계

| 항목 | 상태 |
|---|---|
| 계층 구조, 서브모듈, 셋업 도구(`make setup/test/check`) | 이번 개편에서 도입 |
| 구성요소별 `ai-rm.yaml` | 각 repo에 추가 중 |
| k8s 배포 매니페스트 | llm-d-setup, rngd-pd 보유. 나머지는 추가 필요 |
| 계층 간 인터페이스 | 초안(문서). 다음 단계에서 `rm-core` 패키지로 코드화 |
| `rm_abstract_layer`의 NPU/GB10 장치 모델 확장 | 다음 단계 |
