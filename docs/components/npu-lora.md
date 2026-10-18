# npu-lora — L3 카드

## 이번에 할 일
1. **workload runner** `npu_lora.airm:train` (entry point `airm.workloads` 이름 `npu-lora`):
   `Workload(kind="train", model=...)`와 설정(데이터셋, LoRA rank, 백엔드 `rngd|cuda|cpu`)으로 기존 trainer 실행.
2. **지표**: 학습 처리량은 `tok_s`(tag `workload=train`), 정확도는 `accuracy_pct`(tag `dataset=nsmc|mmlu`),
   가능하면 `power_w`. step 시간이 꼭 필요하면 rm-core 이슈(후보 `step_ms`).
3. **chart** `deploy/helm/npu-lora/`: k8s Job(백엔드별 노드 선택은 airm 레이블), 데이터·체크포인트는 모델 스토어 PVC.
4. `ai-rm.yaml`: `protocol: "0.1"`, adapters, `deploy.chart`, `metrics`.

## 완료 기준
- [ ] `registry.load("airm.workloads","npu-lora")` 로드, CPU 백엔드로 아주 작은 설정의 runner 단위 테스트 통과
- [ ] `helm template deploy/helm/npu-lora` 성공, check_sensitive clean
- [ ] lmd-top이 vendoring한 사본(`lmd-top/assets/npu-lora`)과 달라지는 점을 PR에 적기

## 하지 않을 것
- 학습 알고리즘·컴파일 경로 변경
