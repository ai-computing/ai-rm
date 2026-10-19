# duet — L2 카드 (보류)

> **Optimus Prime 전환 안내:** 선택적인 비공개 검색 workload로 유지하며 공개 Optimus Prime에 비공개 코드를 복사하지 않습니다. 구현 완료를 뜻하지 않습니다. [통합 설계](../ko/engine-integration.md) · [English design](../engine-integration.md) · [계획 설정](../../config/engine-integration.yaml)

dgx_spark 노드 네트워크가 복구되고 노드 checkout을 정리된 이력으로 옮긴 뒤(Plane DUET-30) 진행합니다.

## 그때 할 일
1. 통합메모리 tier를 `MemoryTier(kind="unified")`로 선언하는 Python 바인딩 또는 얇은 adapter.
2. **workload runner** (entry point `airm.workloads` 이름 `duet`, `Workload(kind="search")`): 기존 `duet2_bench`/서버 모드 기동.
3. **지표**: 검색 처리량(`req_s`), 지연(`e2e_p90_ms`), 정확도(`accuracy_pct`, tag `dataset`).
   recall@k가 필요하면 rm-core 이슈(후보 `recall_at_10_pct`).
4. `ai-rm.yaml` 갱신, README `## ai-rm` 절 추가.

## 완료 기준
- [ ] runner 로드, 기존 `ctest` 통과, check_sensitive clean
