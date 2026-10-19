# duet — L2 카드 (보류)

dgx_spark 노드 네트워크가 복구되고 노드 checkout을 정리된 이력으로 옮긴 뒤(Plane DUET-30) 진행합니다.

## 그때 할 일
1. 통합메모리 tier를 `MemoryTier(kind="unified")`로 선언하는 Python 바인딩 또는 얇은 adapter.
2. **workload runner** (entry point `airm.workloads` 이름 `duet`, `Workload(kind="search")`): 기존 `duet2_bench`/서버 모드 기동.
3. **지표**: 검색 처리량(`req_s`), 지연(`e2e_p90_ms`), 정확도(`accuracy_pct`, tag `dataset`).
   recall@k가 필요하면 rm-core 이슈(후보 `recall_at_10_pct`).
4. `ai-rm.yaml` 갱신, README `## ai-rm` 절 추가.

## 완료 기준
- [ ] runner 로드, 기존 `ctest` 통과, check_sensitive clean
