# 시작하기

[문서 홈](README.md) · [English](../getting-started.md)

**전환 중 범위:** 아래 명령은 기존 고정 소스를 사용합니다. [Optimus Prime + FASOP 계획](engine-integration.md)은 아직 활성 런타임이 아닙니다. 제안 브랜치는 미생성이고 계획 YAML은 CLI가 읽지 않습니다.

## 범위 선택

문서 탐색은 Git만 있으면 됩니다. CLI 탐색에는 Python, 구성요소 설치·검증에는 Python 3.8+와 PyYAML 및 각 저장소의 요구 사항이 필요합니다. 배포는 사용 권한이 있는 kubeconfig와 kubectl, 실제 매니페스트가 필요합니다. `duet`은 별도 비공개 접근 권한이 필요합니다.

아래 예시는 Linux/Bash 기준입니다. Windows에서 올바른 Python을 가리키는 `python` 명령으로 CLI를 읽을 수 있지만 구성요소 설치는 지원되는 Linux/WSL 환경에서 수행하세요. Bash 줄바꿈·`mkdir -p`·Make는 PowerShell 기본 문법이 아닙니다.

## 최상위 저장소 받기

```bash
git clone https://github.com/ai-computing/ai-rm.git
cd ai-rm
python3 tools/airm.py list
python3 tools/check_sensitive.py .
```

공개 구성요소만 사용한다면 `--recursive`를 붙이지 마세요. 비공개 `duet`까지 받으려 합니다.

## 공개 구성요소 선택 초기화

```bash
git submodule update --init -- \
  components/l1-accel/rm_abstract_layer \
  components/l2-memory/hetero-npu-p2p \
  components/l2-memory/npu-offload \
  components/l3-serving/rngd-pd \
  components/l3-serving/npu-lora \
  components/l4-cluster/llm-d-setup \
  components/l5-ops/lmd-top
```

목록에는 이력을 정리한 공개 `lmd-top`도 포함됩니다. 정리 이전 체크아웃이 있다면 [이력 전환 안내](status.md)를 확인하세요.

비공개 `duet` 권한이 있는 경우에만 추가합니다.

```bash
git submodule update --init -- components/l2-memory/duet
```

명령은 통합 저장소에 **고정된 커밋**을 받습니다. 통합 조합을 의도적으로 갱신하는 경우가 아니면 `--remote`를 붙이지 마세요.

## 요구 사항 확인·설치·검증

```bash
python3 -m pip install PyYAML
python3 tools/airm.py doctor
python3 tools/airm.py list
python3 tools/airm.py setup --layer l3-serving
python3 tools/airm.py test --layer l3-serving
```

`doctor`는 Git·Python·kubectl·Helm·Cargo·Docker를 찾습니다. 종료 코드만으로 전체 준비 상태를 보장하지 않으며 벤더 드라이버·SDK·모델 접근은 별도입니다. 받지 않은 구성요소는 건너뜁니다. `ai-rm.yaml`이 없어서 **0 steps**가 표시되면 테스트 통과가 아닙니다.

**`make setup`은 계층을 지정해도 먼저 `make init`으로 모든 서브모듈을 받습니다.** 공개 구성요소만 쓰는 경우 위 Python CLI를 사용하세요.

## 배포 설정

```bash
mkdir -p deploy/clusters/local
cp deploy/clusters/example/cluster.example.env deploy/clusters/local/cluster.local.env
# 추적되지 않는 파일에 사이트 값을 입력합니다.
python3 tools/airm.py deploy --cluster local --dry-run --layer l3-serving
```

배포 전에 kubeconfig context를 확인하세요. 환경 변수는 kubectl에 전달되며 임의 YAML에 자동 치환되지 않습니다. 현재 CLI는 `deploy.manifests`를 적용하고 사이트별 `<component>/` overlay가 있으면 Kustomize로 적용합니다. `deploy.chart`만 있어도 Helm을 실행하지는 않습니다. 매니페스트가 없으면 건너뜁니다. Client dry run도 적절한 Kubernetes 설정이 필요할 수 있습니다.

실제 적용할 리소스와 클러스터를 검토한 뒤 배포를 의도할 때만 `--dry-run`을 제거하세요. [배포 문서](../../deploy/README.ko.md)를 참고하세요.

## 자주 만나는 상황

| 상황 | 확인할 것 |
|---|---|
| `duet` clone 실패 | 재귀 clone 대신 공개 경로만 선택 초기화 |
| `not fetched` | 서브모듈 초기화 여부와 접근 권한 |
| PyYAML 오류 | CLI가 쓰는 Python 환경에 PyYAML 설치 |
| `0 steps` | 매니페스트 누락·빈 테스트인지 확인 |
| `no manifests` | 해당 고정 버전의 배포 자산과 작업 카드 확인 |
| P2P 미지원 | 같은 호스트·장치·ABI 조건 확인, staging은 명시적으로 선택 |
| 하드웨어 conformance SKIP | 이유와 함께 기록하며 하드웨어 PASS로 보고하지 않기 |
