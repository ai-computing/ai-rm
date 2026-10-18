# llm-d-setup — L4 카드

클러스터 쪽에서 계약이 "돌 자리"를 만듭니다.

## 이번에 할 일
1. **CRD 설치**: rm-core의 `k8s/acceleratorprofile.crd.yaml`을 클러스터 셋업 단계에 포함(버전 고정, 사본 대신 rm-core 태그에서 가져오는 스크립트).
2. **지표 수집**: Prometheus가 `airm.ai-computing.io/scrape: "true"` 어노테이션이 달린 pod의 `/metrics`를 수집하도록
   scrape 설정(또는 PodMonitor) 추가. 기존 대시보드 옆에 `airm_*` 지표 Grafana 대시보드 1장(`monitoring/grafana-dashboards/airm.json`).
3. **배치 결정 전달 지점**: placement controller(ai-rm, 다음 단계)가 결정을 쓰는 ConfigMap `airm-placement`
   (namespace는 llm-d)의 형식을 문서화하고, EPP 설정에서 이 값을 읽을 위치(scorer 자리)를 표시. v0.1은 문서·빈 ConfigMap까지.
4. **umbrella chart 기반 값**: ai-rm `charts/ai-rm`가 쓸 클러스터 공통 값(namespace, 모델 스토어 PVC 이름, Gateway 이름)을
   `deploy/helm/cluster-values.yaml`로 정리(사이트 값 없이, 키와 기본값만).
5. `ai-rm.yaml`: `protocol: "0.1"`, `deploy.manifests`(CRD·scrape 설정 디렉터리), `metrics: []`.

## 완료 기준
- [ ] dry-run(`kubectl apply --dry-run=server`)으로 CRD·scrape 설정 적용 확인
- [ ] 실제 클러스터에 CRD 설치(되돌리기 방법 README에 기록)
- [ ] check_sensitive clean

## 하지 않을 것
- 운영 중인 모델 서버·EPP 설정 변경 (전달 지점 문서화까지만)
