# lmd-top — L5 카드

lmd-top은 Rust라 rm-core를 import하지 않고, rm-core가 정한 **형식**을 읽습니다.

## 이번에 할 일
1. **AcceleratorProfile 읽기**: `airm.ai-computing.io/v1alpha1` `AcceleratorProfile`을 k8s API로 읽어 Devices 화면에
   벤더·모델·메모리·peak(출처 포함)를 표시. CRD가 없으면 지금처럼 동작(오류 없이 숨김).
2. **airm 지표 읽기**: Prometheus에서 `airm_*` 시리즈(이름·단위는 rm-core `metrics.py`의 표)를 우선 사용하고,
   없으면 기존 vendor 지표로 대체 표시. 표시 단위는 표와 같게.
3. **배치 결정 표시**(읽기 전용): ConfigMap `airm-placement`가 있으면 "배치 결정과 이유"를 보여주는 패널.
4. `ai-rm.yaml`: `protocol: "0.1"`, `metrics: []`(읽기만).

## 완료 기준
- [ ] `cargo test` 통과(CRD/지표 파싱 단위 테스트 포함, 가짜 값은 192.0.2.x)
- [ ] CRD·airm 지표가 없는 클러스터에서 회귀 없음
- [ ] check_sensitive clean

## 하지 않을 것
- 쓰기 동작(scale, drain 등)의 범위 변경
