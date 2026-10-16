# ai-rm — AI 반도체 통합 자원관리

GPU, NPU(FuriosaAI RNGD, Rebellions ATOM), CPU, 통합메모리 시스템(GB10)이 섞인 클러스터에서
LLM 추론·학습 자원을 함께 관리하기 위한 소프트웨어 모음입니다. 기본 대상 환경은 **Kubernetes + llm-d**입니다.

이 저장소는 최상위 통합 repo입니다. 기술별 구현은 각자의 repo에 있고, 여기서는 계층별로 서브모듈로 묶어
아키텍처, 계층 간 인터페이스, 버전 조합, 셋업과 배포를 한곳에서 관리합니다.

```
 L5 관측·운영      lmd-top · rm-bench                         지표·에너지·KPI 측정, 운영 콘솔
 L4 클러스터       llm-d-setup                                k8s + llm-d, EPP/InferencePool, 모델 스토어, 모니터링 스택
 L3 실행·서빙      rngd-pd · npu-lora                         이종 가속기 PD 분리 서빙, NPU 학습
 L2 메모리·전송    hetero-npu-p2p · npu-offload · duet        NPU↔NPU KV 전송, NPU↔Host 오프로딩, CPU↔GPU 통합메모리
 L1 가속기 추상화  rm_abstract_layer                          장치 모델·탐지·플러그인 (GPU/NPU/CPU)
```

## 구성요소

| 계층 | 구성요소 | 종류 | 역할 |
|---|---|---|---|
| L1 | [rm_abstract_layer](components/l1-accel/) | library | 이종 가속기 통합 추상화 (장치 탐지, 엔진·자원 플러그인) |
| L2 | [hetero-npu-p2p](components/l2-memory/) | library | 같은 호스트의 이종 NPU 간 KV 전송 (completion-fenced P2P, llm-d stage 연동) |
| L2 | [npu-offload](components/l2-memory/) | service | MoE 전문가 오프로딩: hot expert는 NPU HBM, cold expert는 호스트 CPU |
| L2 | [duet](components/l2-memory/) | library | GB10 통합메모리에서 CPU 그래프 순회 + GPU 거리 계산 협업 벡터 검색 |
| L3 | [rngd-pd](components/l3-serving/) | service | RNGD prefill + ATOM decode PD 분리 서빙 (llm-d pod) |
| L3 | [npu-lora](components/l3-serving/) | workload | 추론 전용 NPU에서의 LoRA·full fine-tuning |
| L4 | [llm-d-setup](components/l4-cluster/) | cluster | 이종 가속기 k8s + llm-d 클러스터 구성, 모니터링 스택 |
| L5 | [lmd-top](components/l5-ops/) | tool | llm-d 클러스터 관측·운영 콘솔 (TUI) |
| L5 | [rm-bench](components/l5-ops/) | tool | trace 재생·합성 부하, TTFT/TPOT/E2E 측정 |

구성요소 repo는 비공개입니다. 서브모듈은 ai-computing 조직 멤버만 받을 수 있습니다.
각 구성요소는 루트에 [`ai-rm.yaml`](docs/component-contract.md)을 두고, 그 파일로 설치·테스트·배포 방법을 선언합니다.

## 빠른 시작

```bash
git clone --recursive https://github.com/ai-computing/ai-rm.git   # 조직 멤버
cd ai-rm
make doctor          # git, python, kubectl, helm 등 사전 조건 확인
make list            # 구성요소, 계층, 버전, 배포 가능 여부
make setup           # 모든 구성요소 설치 (계층별: make setup LAYER=l2-memory)
make test            # 가속기 없이 도는 빠른 테스트
cp deploy/clusters/example/cluster.example.env deploy/clusters/local/cluster.local.env   # 사이트 값 입력
make deploy CLUSTER=local DRY_RUN=1   # k8s 배포 계획 확인 → DRY_RUN 빼고 실제 배포
make check           # 공개되면 안 되는 정보(내부 IP, 토큰, 키) 검사
```

사이트별 값(노드 주소, 게이트웨이 주소, 자격 증명)은 추적되지 않는 `cluster.local.env`에만 둡니다.
자세한 내용은 [deploy/README.md](deploy/README.md)와 [docs/security.md](docs/security.md)를 보세요.

## 문서

- [docs/architecture.md](docs/architecture.md) — 계층 구조와 k8s + llm-d 위에서의 동작 흐름
- [docs/interfaces.md](docs/interfaces.md) — 계층 간 인터페이스(계약) 초안
- [docs/component-contract.md](docs/component-contract.md) — 구성요소 repo가 지켜야 할 것 (`ai-rm.yaml`, README, 설정)
- [docs/kpi-map.md](docs/kpi-map.md) — 과제 성과지표와 구성요소·근거의 대응
- [docs/security.md](docs/security.md) — 공개 저장소 보안 규칙과 검사

## 이전 구조에서 바뀐 점 (2026-10)

- `rm_monitor`는 역할별로 나뉘었습니다. 모니터링 스택과 Grafana 대시보드는 `llm-d-setup/monitoring/`,
  trace 재생·부하 도구는 `rm-bench`, 운영 콘솔은 `lmd-top`이 맡습니다. `rm_monitor` 저장소는 보관(archive) 상태입니다.
- `rm_abstract_layer`는 `components/l1-accel/`로 옮겨졌습니다.

## License

BSD-3-Clause (각 구성요소의 라이선스는 해당 repo를 따릅니다).
