# npu-offload — L2 카드

전문가 오프로딩은 KV가 아니라 가중치·activation을 계층 사이로 나누는 기술이라, v0.1에서는 `KVTransport`를
구현하지 않습니다. 대신 **실행 단위(workload runner)와 메모리 계층 선언, 지표**로 연결합니다.

## 이번에 할 일
1. **workload runner** `moe_offload.airm:serve` (entry point `airm.workloads` 이름 `npu-offload`):
   `Workload(kind="serve" | "decode", model=...)`와 설정(키는 README에 명시)을 받아 기존 serve 모드/게이트웨이를 기동.
2. **메모리 계층 선언**: 사용하는 tier(`device-hbm` RNGD, `host-dram`)를 `rm_core.MemoryTier`로 만들어 시작 로그와
   `/metrics` info에 남깁니다(용량은 실제 값).
3. **지표**: `tok_s`, `tpot_p50_ms`/`tpot_p90_ms`, 가능하면 `power_w`(scope 태그) — `airm_` Prometheus 시리즈와 `report.py --metric` 둘 다.
4. **chart** `deploy/helm/npu-offload/`: llm-d ModelService로 붙는 serve 모드(노드 선택은 `airm.ai-computing.io/furiosa.RNGD` 레이블).
5. `ai-rm.yaml`: `protocol: "0.1"`, adapters, `deploy.chart`, `metrics`.

## 완료 기준
- [ ] `registry.load("airm.workloads","npu-offload")`가 import 오류 없이 로드됨 (실행은 장치 필요)
- [ ] `helm template deploy/helm/npu-offload` 렌더링 성공, 사이트 값 없음
- [ ] 기존 selftest 통과, check_sensitive clean

## 하지 않을 것
- 오프로딩 정책·커널 변경, 진행 중인 `moe_offload/deploy/` 작업 덮어쓰기
- 새 지표 이름 만들기 (필요하면 rm-core 이슈: 후보 `expert_hit_pct`)
