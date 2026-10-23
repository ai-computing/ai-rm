[English](../component-contract.md) · [한국어 문서 홈](README.md)

# 구성요소 계약

[Optimus Prime 계획 설정](../../config/engine-integration.yaml)은 구성요소 `ai-rm.yaml`과 별개인 비실행 설계 문서입니다. FASOP과 런타임은 같은 `aicomp` 소스를 사용하며 중복 서브모듈로 만들지 않습니다. 미구현 adapter의 설치·배포 명령을 있는 것처럼 선언하지 않고, 구현·검토·고정 이후 실제 엔진 매니페스트를 추가합니다. [통합 설계](engine-integration.md)를 참고하세요.

ai-rm에 들어가는 모든 repo는 아래를 지킨다. `make list/setup/test/deploy`는 이 약속만 보고 동작한다.

## 1. `ai-rm.yaml` (repo 루트)

```yaml
name: hetero-npu-p2p
layer: l2-memory              # l1-accel | l2-memory | l3-serving | l4-cluster | l5-ops
kind: library                 # library | service | workload | cluster | tool
summary: 같은 호스트의 이종 NPU 간 KV 전송
maturity: experimental        # experimental | prototype | stable
hardware: [RNGD, ATOM]
install:                      # repo 루트에서 실행
  - python -m pip install -e .
test:                         # 가속기 없이 도는 빠른 검사
  - PYTHONPATH=src python -m unittest discover -s tests
deploy:
  target: llm-d               # llm-d | k8s | none
  manifests: null             # kustomize 디렉터리(또는 매니페스트 디렉터리), 없으면 null
  image: null
config:
  env_example: cluster.example.env   # 사이트 값이 없으면 null
interfaces:
  provides: [KVTransport]
  uses: [Accelerator, Metrics]
kpi: [전력효율, SLO]
# protocol v0.1부터 (docs/integration-guide.md §2.7)
protocol: "0.1"               # 구현한 rm-core protocol 버전
adapters:                     # 등록한 entry point
  - group: airm.kv_transports
    name: p2p
metrics: [kv_transfer_ms, kv_transfer_gbps]   # 내보내는 rm-core 지표
# deploy.chart: deploy/helm/<component>  (Helm chart가 있으면)
```

선택한 구성요소에 `deploy.chart`가 있으면 umbrella deploy는 매니페스트를 적용하기 전에
멈추고 `helm upgrade --install` 명령을 출력한다. 출력된 namespace와 site values 자리표시자를
실제 설정으로 바꿔 실행한다. `--dry-run`은 Helm client dry run 옵션을 붙인다.
차트가 없는 구성요소는 `deploy.manifests`를 kubectl로 적용한다.

## 2. README의 `## ai-rm` 절

계층과 역할, k8s + llm-d에 붙는 방식(아직이면 무엇이 빠졌는지), 설치·테스트 명령,
제공·사용하는 인터페이스, 관련 성과지표, 필요한 `cluster.local.env` 변수.

## 3. 사이트 값과 비밀 정보

- 노드 주소, 게이트웨이 주소, 포트, 자격 증명은 코드·문서·매니페스트에 쓰지 않는다.
- 코드는 환경 변수로 읽는다. 키 목록은 `cluster.example.env`(자리표시자, 커밋)로 알리고,
  실제 값은 추적되지 않는 `cluster.local.env`(`.gitignore`)에 둔다.
- 필요한 값이 없으면 분명한 오류로 멈춘다. 내부 주소를 기본값으로 숨겨 두지 않는다.
- 문서 예시는 `<gateway-host>` 같은 자리표시자나 RFC 5737 주소(`192.0.2.x`)를 쓴다.
- push 전에 `python3 .research/check_sensitive.py`(또는 ai-rm의 `make check`)가 `clean`이어야 한다.

## 4. 버전

- 라이브러리는 의미 있는 변경마다 태그(`vX.Y.Z`)를 붙인다.
- ai-rm은 서브모듈 커밋으로 통합 버전을 고정한다. 구성요소를 올릴 때는 `make bump COMPONENT=<name>`로
  포인터를 갱신하고 ai-rm에 커밋한다.
