# rm_abstract_layer — L1 카드

> **Optimus Prime 전환 안내:** L1 장치 탐지·능력 게시는 유지하고, 엔진 실행·백엔드 adapter는 Optimus Prime으로 통합하는 방향입니다. 구현 완료를 뜻하지 않습니다. [통합 설계](../ko/engine-integration.md) · [English design](../engine-integration.md) · [계획 설정](../../config/engine-integration.yaml)

## 이번에 할 일
1. **`AcceleratorProvider` adapter** `rm_abstract.airm:RmAbstractProvider` (entry point `airm.accelerator_providers` 이름 `rm-abstract`).
   - 기존 탐지(`resources/*`, `common/hardware_detector.py`)의 `ResourceInfo`를 `rm_core.Accelerator`로 변환합니다.
   - `id`는 `<노드 이름>/<vendor>:<index>`. 노드 이름은 `AIRM_NODE_NAME` 환경 변수, 없으면 hostname.
   - `peak_tflops`는 출처가 분명한 값만 넣고 `peak_source`를 적습니다(데이터시트 문서명 등). 모르면 비웁니다.
   - 장치가 없으면 `[]`를 돌려줍니다(예외 금지).
2. **노드 데몬** `python -m rm_abstract.airm.daemon`:
   - 주기적으로 `discover()` → `rm_core.k8s.accelerator_profile()`로 AcceleratorProfile을 만들어 apply,
     `rm_core.k8s.node_labels()`로 노드 레이블을 패치합니다(in-cluster ServiceAccount).
   - `--once --dry-run`이면 만들 객체를 출력만 합니다(테스트·시연용).
3. **chart** `deploy/helm/rm-abstract-node/`: DaemonSet + ServiceAccount/RBAC(acceleratorprofiles, nodes/patch).
4. `ai-rm.yaml`: `protocol: "0.1"`, adapters, `deploy.chart`, `metrics: [accelerators]`.

## 완료 기준
- [ ] `python -m rm_core.conformance airm.accelerator_providers rm-abstract` → PASS (장치 없는 PC에서도 `[]`로 PASS)
- [ ] GPU/RNGD/ATOM 노드에서 `--once --dry-run` 출력이 실제 장치 수·모델과 일치
- [ ] 기존 `pytest -m "not gpu and not slow" tests/unit` 통과, check_sensitive clean

## 하지 않을 것
- 기존 vLLM 호환 API(`from rm_abstract import LLM`) 동작 변경
- k8s 클라이언트 라이브러리를 필수 의존성으로 추가 (데몬용 extra `[k8s]`로)
