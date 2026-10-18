# 통합 가이드 (protocol v0.1)

구성요소를 ai-rm에 "연결"하는 방법입니다. 무엇을 지켜야 하는지는 [rm-core PROTOCOL.md](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md),
각 repo가 이번에 할 일은 [components/](components/)의 카드에 있습니다.

## 1. 연결 방식 한눈에 보기

```
 L5 관측  ── airm_* 지표 (rm_core.metrics) ─────────────────────────────┐
 L4 결정  ── Placement (airm.placements) + AcceleratorProfile 읽기        │
 L3 실행  ── workload runner (airm.workloads), KV 경로는 이름으로 선택      │ 같은 지표 이름
 L2 이동  ── KVTransport (airm.kv_transports)                             │ = 대시보드 = KPI
 L1 자원  ── AcceleratorProvider (airm.accelerator_providers) → k8s 프로파일 ┘
```

- 구성요소끼리 서로 import하지 않습니다. 각 repo는 **자기 기능을 rm-core 계약으로 감싼 작은 adapter**만 추가하고
  entry point로 등록합니다. 실행 시에는 설정의 이름(`kvTransport: p2p`)으로 구현을 고릅니다.
- 그래서 KV 경로를 P2P에서 host staging으로 바꾸거나, 배치 정책을 바꾸는 일이 코드 수정이 아니라 설정 변경이 됩니다.

## 2. 작업 순서 (모든 repo 공통)

1. **브랜치**: `airm/v0.1`에서 작업하고 PR을 올립니다. main에 직접 push하지 않습니다.
2. **의존성**: `pyproject.toml`(또는 requirements)에 추가합니다.
   ```toml
   dependencies = ["rm-core @ git+https://github.com/ai-computing/rm-core@v0.1.0"]
   ```
   Python 패키지가 아닌 repo(Rust, C++, 매니페스트 전용)는 adapter를 작은 Python 모듈로 두거나,
   카드에 적힌 대로 rm-core가 정의한 **형식**(지표 이름, AcceleratorProfile)만 따릅니다.
3. **adapter**: 패키지 안에 `airm.py`(또는 `airm/` 패키지)를 만들고 계약을 구현합니다.
   - 기존 코드를 **감싸기만** 합니다. 로직을 옮기거나 리팩터링하지 않습니다.
   - 하드웨어가 필요한 adapter는 `conformance_case()`를 구현하고, 장치가 없으면 `NoHardware`를 냅니다.
   - 실패를 다른 경로로 조용히 대체하지 않습니다(PROTOCOL §4.5).
4. **entry point 등록**:
   ```toml
   [project.entry-points."airm.kv_transports"]
   p2p = "hetero_p2p.airm:P2PTransport"
   ```
5. **지표**: 이 구성요소가 내는 수치를 `rm_core.metrics.METRICS`의 이름·단위로 맞춥니다.
   - Prometheus로 낼 때는 `airm_<name>` 시리즈, 태그는 `TAG_KEYS`만.
   - 연구 보고(`report.py --metric`)도 같은 이름을 씁니다(`tok_s`, `tpot_p90_ms`, `power_w` …).
   - 필요한 지표가 표에 없으면 임의로 만들지 말고 rm-core에 이슈를 올립니다(카드에 후보를 적어 두세요).
6. **k8s(해당하는 경우)**: Helm chart를 `deploy/helm/<component>/`에 둡니다(아래 §3).
7. **`ai-rm.yaml` 갱신**: 아래 필드를 추가합니다.
   ```yaml
   protocol: "0.1"
   adapters:                       # 등록한 entry point
     - group: airm.kv_transports
       name: p2p
   deploy:
     target: llm-d
     chart: deploy/helm/hetero-npu-p2p   # 없으면 null
   metrics: [kv_transfer_ms, kv_transfer_gbps]   # 이 구성요소가 내는 지표
   ```
8. **검증** (모두 통과해야 PR):
   ```bash
   python -m pip install -e .
   python -m rm_core.conformance            # 내 adapter가 PASS(하드웨어 없으면 SKIP)
   <repo의 기존 테스트>
   python3 .research/check_sensitive.py .   # clean
   ```
9. **PR 본문**: 무엇을 감쌌는지, 등록한 entry point, conformance 결과(PASS/SKIP 이유), 내는 지표,
   카드의 완료 기준을 하나씩 어떻게 만족했는지.

## 3. Helm chart 규칙

ai-rm의 umbrella chart(`charts/ai-rm`)가 각 구성요소 chart를 subchart로 묶습니다. 그래서 모양을 맞춥니다.

```
deploy/helm/<component>/
  Chart.yaml        # name: <component>, version: 구성요소 버전, appVersion
  values.yaml       # 아래 키 사용, 사이트 값 없음
  templates/
```

```yaml
# values.yaml 공통 키
enabled: true
image: {repository: "", tag: ""}
airm:
  kvTransport: ""          # 이 pod가 쓸 KV 경로 이름 (entry point 이름)
  placement: ""            # 배치 정책 이름 (L4가 쓰는 경우)
  metricsPort: 9400        # airm_* 지표를 내보내는 포트 (/metrics)
nodeAffinity: {}           # airm.ai-computing.io/<vendor>.<model> 레이블 존재로 노드 선택
resources: {}
```

- 노드 선택은 IP나 호스트명이 아니라 `airm.ai-computing.io/<vendor>.<model>` 레이블로 합니다.
- 사이트 값(주소, 자격 증명)은 values에 넣지 않습니다. ai-rm `deploy/clusters/<name>/`의 override로 들어옵니다.
- 지표 포트에는 Prometheus가 수집하도록 `airm.ai-computing.io/scrape: "true"` 어노테이션을 답니다.

## 4. 하지 않는 것

- 다른 구성요소 repo의 코드를 import하거나 복사하기 (계약을 통해서만)
- 실험 로직·커널·성능 경로 변경 (이번 단계는 연결만)
- 지표 이름을 구성요소마다 새로 짓기
- 내부 주소, 자격 증명을 코드·values·문서에 넣기

## 5. agent에게 주는 지시 (템플릿)

```
ai-rm protocol v0.1 통합 작업이다.
1) https://github.com/ai-computing/rm-core 의 PROTOCOL.md 와 README
2) ai-rm docs/integration-guide.md
3) ai-rm docs/components/<component>.md (이 repo의 카드)
를 읽고 카드의 "이번에 할 일"을 하라. 완료 기준은 카드의 체크리스트와 conformance 통과다.
브랜치 airm/v0.1 에서 작업하고 PR을 올려라. main에 push하지 말고, 다른 agent가 작업 중일 수 있으니
git add 는 바꾼 경로만. 끝나면 report.py --task <ID> --result "<PR 링크, conformance 결과>" --done --label infra.
```

## 6. 통합 이후 (ai-rm 쪽에서 하는 일)

PR이 머지되면 ai-rm에서 서브모듈을 올리고(`make bump`), umbrella chart와 시뮬레이션 클러스터(`make up-sim`)에서
L1 → L5 전체 흐름을 확인합니다. 그 조합이 `compatibility.yaml`에 기록되는 통합 버전입니다.
