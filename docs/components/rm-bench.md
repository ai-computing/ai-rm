# rm-bench — L5 카드

> **Optimus Prime 전환 안내:** 부하·측정 책임은 유지하며 후속 작업에서 Optimus Prime 실행 실측과 FASOP 추정값을 구분해 비교합니다. 구현 완료를 뜻하지 않습니다. [통합 설계](../ko/engine-integration.md) · [English design](../engine-integration.md) · [계획 설정](../../config/engine-integration.yaml)

end-to-end 시나리오의 실행기가 됩니다.

## 이번에 할 일
1. **결과 형식**: 모든 도구의 결과를 rm-core `Measurement` 목록(JSON: `[{"name","value","tags"}]`)으로도 저장
   (`--out results/<run>.json`). 이름·태그는 `METRICS`/`TAG_KEYS`만, 저장 전에 `validate()`.
2. **e2e 시나리오 실행기** `rm-bench e2e --gateway $LLMD_GATEWAY_URL --scenario <name>`:
   - 시나리오 정의 `scenarios/<name>.yaml`: 요청 분포(trace 또는 합성), 동시성, 시간, SLO(`rm_core.workload.SLO_KEYS`).
   - 실행 후 SLO 판정과 `slo_attainment_pct`, `tok_s`, `ttft_p90_ms`, `tpot_p90_ms`를 Measurement로 출력.
   - 첫 시나리오 `pd-smoke`: 작은 요청 몇십 개로 PD 경로 전체가 응답하는지 확인.
3. entry point `airm.workloads` 이름 `rm-bench` (`Workload(kind="serve")`를 받아 시나리오 실행).
4. `ai-rm.yaml`: `protocol: "0.1"`, adapters, `metrics`(위 4개).

## 완료 기준
- [ ] 가짜 OpenAI 호환 서버(테스트 안에서 띄움)로 `e2e --scenario pd-smoke`가 Measurement JSON을 만들고 validate 통과
- [ ] check_sensitive clean

## 하지 않을 것
- 대상 주소를 코드나 시나리오 파일에 넣기 (`--gateway`/환경 변수로만)
