[English](README.md) · [한국어 문서](../docs/ko/README.md)

# deploy

ai-rm의 기본 대상은 Kubernetes + llm-d 클러스터입니다. 클러스터 자체(k8s, llm-d, Gateway, EPP, 모델 스토어,
모니터링 스택)는 `components/l4-cluster/hetero-llm-d`가 만들고, 다른 구성요소는 그 위에 올라갑니다.

## 사이트 설정

```
deploy/clusters/
├─ example/                    커밋됨: 키 목록과 자리표시자
│  ├─ cluster.example.env
│  ├─ ai-rm.values.yaml        umbrella chart 사이트 값
│  └─ <component>.values.yaml  chart별 예시
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

## Umbrella chart

[`charts/ai-rm`](../charts/ai-rm)은 ai-rm 제어 경로를 `helm install` 한 번으로 설치합니다.

| 구성 | 출처 | 리소스 |
|---|---|---|
| L1 노드 데몬 | rm-accel chart `rm-abstract-node` (subchart, alias `node`, 고정된 서브모듈에서) | DaemonSet, ServiceAccount, ClusterRole; 이미지 `ghcr.io/ai-computing/rm-accel` |
| `AcceleratorProfile` CRD | rm-core v0.1.1 `k8s/`를 `charts/ai-rm/crds/`로 복사 | CRD (먼저 설치, Helm이 업그레이드·삭제하지 않음) |
| L4 rm-controller | [`packages/rm-controller`](../packages/rm-controller) | Deployment, spec ConfigMap(`controller.pools`), ClusterRole(프로파일, 노드), Role(`airm-placement`만); 이미지 `ghcr.io/ai-computing/rm-controller` |
| `airm-placement` | hetero-llm-d `deploy/airm/README.md` 형식 | 빈 v0.1 문서를 담은 ConfigMap. 없을 때만 만들고 업그레이드·삭제 시 유지, 내용은 rm-controller가 관리 |

```bash
git submodule update --init components/l1-accel/rm-accel
helm dependency update charts/ai-rm
mkdir -p deploy/clusters/local
cp deploy/clusters/example/ai-rm.values.yaml deploy/clusters/local/ai-rm.values.yaml   # 풀, 네임스페이스 수정
helm upgrade --install airm charts/ai-rm -n airm-system --create-namespace \
  -f deploy/clusters/local/ai-rm.values.yaml
make chart          # helm lint + template (기본값, sim 값)
```

`placementNamespace`는 EPP scorer와 lmd-top이 `airm-placement`를 읽는 네임스페이스(llm-d 네임스페이스)입니다.
hetero-llm-d의 `airm-install.sh`가 CRD나 ConfigMap을 이미 만들었다면 chart는 그대로 둡니다. 노드 데몬에는 이제
init container가 필요 없습니다. 이미지에 rm-abstract, rm-core, Kubernetes 클라이언트가 들어 있고 벤더 도구는 호스트
`/usr/bin`에서 마운트합니다(`node.hostBin`). 이미지는 이 저장소의 `.github/workflows/rm-controller-image.yml`과
rm-accel의 `Image` 워크플로가 배포합니다.

## 시뮬레이션 클러스터

같은 chart를 [kind](https://kind.sigs.k8s.io/)에서 rm-core의 `sim` 가속기 provider(노드마다 RNGD 1개와 ATOM 1개,
수치는 자리표시자), 소스에서 빌드한 이미지, PD 풀 대신 [`tools/fake_openai.py`](../tools/fake_openai.py)로 실행합니다.
CI가 모든 pull request에서 실행합니다(`.github/workflows/sim-e2e.yml`).

```bash
make up-sim         # kind 클러스터 airm-sim(노드 2개), 이미지 빌드·로드, charts/ai-rm + ci/sim-values.yaml
make e2e-sim        # rm-controller --once, airm-placement 확인, 가짜 풀에 rm-bench pd-smoke
make e2e-sim NO_CLUSTER=1   # 같은 확인을 프로세스 안에서, Docker·kind 없이
make down-sim
```

`e2e-sim`은 프로파일이 있고(노드당 2개), `charts/ai-rm/ci/sim-values.yaml`의 각 풀에 요청한 종류의 카드로 한
노드 안에 prefill·decode 결정이 있으며, 두 풀이 서로 다른 노드를 쓰고, `rm-bench`가 실패 요청 없이
`slo_attainment_pct` 100을 보고하면(`results/sim-e2e.json`) 통과합니다. Docker, kind, kubectl, Helm과
`pip install -e packages/rm-controller -e packages/rm-bench`가 필요합니다. 시뮬레이션은 제어 경로와 측정 경로를
확인하며 서빙 성능을 뜻하지 않습니다.

## 구성요소별 배포 상태

`make list`의 DEPLOY 열에서 확인합니다(✓ = 매니페스트 있음). 매니페스트가 없는 구성요소는 각 repo의
README `## ai-rm` 절에 무엇이 필요한지 적혀 있습니다.

## Optimus Prime 전환 경계

[통합 설계](../docs/ko/engine-integration.md)와 [계획 설정](../config/engine-integration.yaml)은 향후 엔진·FASOP 연결을 설명하며 현재 CLI가 실행하지 않습니다. 기존 소스 배포는 유지하고, 계획된 엔진이나 존재하지 않는 브랜치를 배포하는 것으로 해석하지 마세요. 현재 CLI는 deploy.manifests만 kubectl로 적용하며 deploy.chart를 자동 Helm 배포하지 않습니다(Helm은 위 umbrella chart를 사용). cluster.local.env는 kubectl 환경 변수로 전달되며 임의 YAML을 자동 치환하지 않습니다.
