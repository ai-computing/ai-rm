# rm-controller — L4 카드

> 위치: ai-rm [`packages/rm-controller`](../../packages/rm-controller) (in-tree). 정책 `airm.placements:topology`.

AcceleratorProfile(L1)과 노드 상태를 읽어 prefill/decode 풀을 배치하고, 결정을 ConfigMap `airm-placement`(hetero-llm-d
`deploy/airm/README.md`의 `decisions.json` 형식)에 씁니다. EPP scorer와 lmd-top이 이 ConfigMap을 읽습니다.

## 현재 (2026-10-19, 1차 구현)
- 정책 `topology`: host-local KV 경로(`shm`, `p2p`, `loopback`)는 prefill·decode를 한 노드에, 카드는 서로 다르게(`loopback` 제외).
  cordon·NotReady 노드 제외, prefill은 최고 peak, decode는 최대 메모리, 동점은 낮은 카드 번호. 역할별 `count`로 P:D 1:N.
  풀은 순서대로 배치하고 카드를 공유하지 않습니다. 들어갈 곳이 없으면 이유와 함께 빈 결정(종료 코드 1).
- `generation`은 결정이 바뀔 때만 증가합니다.
- 검증: 테스트 12개(실제 클러스터 모양의 풀), `rm_core.conformance airm.placements topology` PASS, 실제 클러스터 dry-run에서
  shm 풀 → `npu-node-1/furiosa:0` + `furiosa:1`(e2e 수동 배치와 동일), p2p 풀 → RNGD 0 + ATOM 0,1.

## 다음 할 일
1. `airm_*` 부하(대기열, TPOT)와 트레이스 특성을 선택에 반영 ([워크로드 트레이스](../workload-traces.md)).
2. 결정대로 서빙 파드를 구동: 지금은 사이트 값이 카드를 고정하므로 결정과 실제 배치가 같은지 확인만 가능합니다.
3. 클러스터 상주: 이미지와 chart(umbrella chart에 포함), in-cluster 클라이언트(`[k8s]`).
4. 배치 ConfigMap 형식을 rm-core PROTOCOL에 규범화(HUB-12).
