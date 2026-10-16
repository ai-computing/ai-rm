# deploy

ai-rm의 기본 대상은 Kubernetes + llm-d 클러스터입니다. 클러스터 자체(k8s, llm-d, Gateway, EPP, 모델 스토어,
모니터링 스택)는 `components/l4-cluster/llm-d-setup`이 만들고, 다른 구성요소는 그 위에 올라갑니다.

## 사이트 설정

```
deploy/clusters/
├─ example/                    커밋됨: 키 목록과 자리표시자
│  └─ cluster.example.env
└─ <name>/                     추적 안 함: 실제 사이트 값
   ├─ cluster.local.env        노드·게이트웨이 주소, 자격 증명 위치
   └─ <component>/             (선택) 그 구성요소의 kustomize overlay
```

```bash
mkdir -p deploy/clusters/local
cp deploy/clusters/example/cluster.example.env deploy/clusters/local/cluster.local.env
$EDITOR deploy/clusters/local/cluster.local.env
make deploy CLUSTER=local DRY_RUN=1     # 무엇을 적용할지 확인
make deploy CLUSTER=local LAYER=l3-serving
```

`make deploy`는 각 구성요소의 `ai-rm.yaml`에 있는 `deploy.manifests`를 `kubectl apply`합니다.
`deploy/clusters/<name>/<component>/`에 overlay가 있으면 그것을 대신 적용합니다.
`cluster.local.env`의 값은 환경 변수로 전달됩니다.

## 구성요소별 배포 상태

`make list`의 DEPLOY 열에서 확인합니다(✓ = 매니페스트 있음). 매니페스트가 없는 구성요소는 각 repo의
README `## ai-rm` 절에 무엇이 필요한지 적혀 있습니다.
