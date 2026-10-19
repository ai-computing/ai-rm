# rngd-pd — L3 카드

> **Optimus Prime 전환 안내:** PD 서빙과 NPU 백엔드 기술은 Optimus Prime 모듈로 통합하는 방향입니다. 아래는 전환 중 기존 소스의 계약·검증 기준입니다. 구현 완료를 뜻하지 않습니다. [통합 설계](../ko/engine-integration.md) · [English design](../engine-integration.md) · [계획 설정](../../config/engine-integration.yaml)

## 이번에 할 일
1. **기존 KV 경로를 `KVTransport`로**: `rngd_pd.connector.transport`(/dev/shm 세그먼트, bf16 wire)를 감싼
   `rngd_pd.airm:ShmTransport` (entry point `airm.kv_transports` 이름 `shm`). host staging 경로임을 README에 명시.
   `conformance_case()`는 같은 호스트의 shm 두 tier로 동작(장치 없이도 PASS 가능해야 함).
2. **KV 경로를 이름으로 선택**: connector(`connector/rngd_kv.py`)가 `AIRM_KV_TRANSPORT`(또는 chart 값 `airm.kvTransport`)로
   `rm_core.registry.load("airm.kv_transports", name)`을 써서 경로를 고르게 합니다. 기본값은 지금 동작과 같은 `shm`.
   `p2p`(hetero-npu-p2p)가 설치돼 있으면 설정만으로 바뀌어야 합니다.
3. **workload runner** `rngd_pd.airm:run` (entry point `airm.workloads` 이름 `rngd-pd`): prefill/decode pod 기동.
4. **지표**: `ttft_p90_ms`, `tpot_p90_ms`, `tok_s`, `kv_transfer_ms`(tag `kv_transport`), 가능하면 `power_w` —
   `airm_` 시리즈와 `bench/`의 결과 파일 둘 다 같은 이름으로.
5. **chart** `deploy/helm/rngd-pd/`: 기존 `deploy/k8s` 매니페스트를 chart로 옮기고 `airm.kvTransport` 값 추가.
   노드 선택은 `airm.ai-computing.io/furiosa.RNGD`, `airm.ai-computing.io/rebellions.ATOM` 레이블.
6. `ai-rm.yaml`: `protocol: "0.1"`, adapters, `deploy.chart`, `metrics`.

## 완료 기준
- [ ] `python -m rm_core.conformance airm.kv_transports shm` → PASS
- [ ] `AIRM_KV_TRANSPORT=shm`일 때 기존과 같은 출력(기존 선택 테스트 통과), 설정만으로 다른 이름이 선택됨을 단위 테스트로 확인
- [ ] `helm template deploy/helm/rngd-pd` 성공, 사이트 값 없음, check_sensitive clean

## 하지 않을 것
- 커널·엔진·배치 로직 변경. `tests/run_selftests.sh`의 경로 문제는 별도 작업(이미 등록됨)
