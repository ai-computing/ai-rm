# hetero-npu-p2p — L2 카드

> **Optimus Prime 전환 안내:** KV 전송 기술은 Optimus Prime의 모듈·연동으로 통합하는 방향이며 같은 호스트·ABI·완료 fence·명시적 경로를 유지합니다. 구현 완료를 뜻하지 않습니다. [통합 설계](../ko/engine-integration.md) · [English design](../engine-integration.md) · [계획 설정](../../config/engine-integration.yaml)

## 이번에 할 일
1. **`KVTransport` adapter** `hetero_p2p.airm:P2PTransport` (entry point `airm.kv_transports` 이름 `p2p`).
   - `supports`: RNGD 장치 메모리 → ATOM 장치 메모리(현재 검증된 ABI 범위)만 True.
   - `plan`: 기존 `layout`의 전송 계획을 감싸고, 범위·정렬 검사 실패는 `TransportError`.
   - `submit`/`wait`: 기존 completion-fenced 경로(`backend`, native helper)를 그대로 사용. `wait`는 완료 fence 이후에만 반환.
   - host staging으로 조용히 대체하지 않습니다(이미 이 라이브러리의 원칙).
   - `conformance_case()`: 이 장치에서 쓸 수 있는 실제 tier와 작은 layout을 돌려주고, 장치나 ABI가 맞지 않으면 `NoHardware`.
2. **llm-d stage 연동**(`llmd.py`)에서 KV 경로를 이름으로 받을 수 있게 합니다(기본 `p2p`).
3. **지표**: 전송마다 `kv_transfer_ms`(tag `kv_transport=p2p`), 가능하면 `kv_transfer_gbps`.
4. `ai-rm.yaml`: `protocol: "0.1"`, adapters, `metrics: [kv_transfer_ms, kv_transfer_gbps]`. chart는 없음(서빙 pod 안의 라이브러리).

## 완료 기준
- [ ] rebellion 노드에서 `python -m rm_core.conformance airm.kv_transports p2p` → PASS, 일반 PC에서는 SKIP
- [ ] 기존 unittest 75개 통과, check_sensitive clean
- [ ] 버전 태그 `v0.6.0` (adapter 추가)

## 하지 않을 것
- 전송 경로·배치 알고리즘 변경, 실험 중인 코드 수정 (codex가 같은 checkout에서 실험 중)
