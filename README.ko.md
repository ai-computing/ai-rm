<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/wordmark-dark.svg">
    <img src="docs/assets/wordmark-light.svg" width="260" alt="AI-RM">
  </picture>
</p>

<p align="center"><strong>이종 AI 인프라를 위한 통합 자원관리.</strong></p>

<p align="center">
  <a href="README.md">English</a> · <strong>한국어</strong><br>
  <a href="docs/ko/README.md">문서</a> · <a href="docs/ko/getting-started.md">시작하기</a> · <a href="docs/ko/architecture.md">아키텍처</a> · <a href="docs/ko/engine-integration.md">Optimus Prime</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-BSD--3--Clause-64748b" alt="라이선스: BSD-3-Clause"></a>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/check-docs.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/check-docs.yml/badge.svg" alt="문서 검사"></a>
  <a href="docs/ko/status.md"><img src="https://img.shields.io/badge/Stage-Research%20%26%20integration-107e72" alt="단계: 연구·통합"></a>
</p>

AI-RM은 **「AI 반도체 통합 자원관리 기술 개발」 과제의 통합 허브**입니다. 공통 계약, 고정된 구성요소 버전, 재현 가능한 측정을 통해 **GPU·NPU·CPU·GB10 통합메모리 연구**를 **Kubernetes + llm-d** 환경에 연결합니다.

- **자원 표현** — 장치를 탐지하고 서로 다른 능력을 공통 모델로 표현합니다.
- **엔진 기술 통합** — 추론·KV 전송·전문가 offload를 Optimus Prime으로 모으고 FASOP을 내부 계획 요소로 둡니다.
- **관측과 평가** — 클러스터 운영, 워크로드 실측, 과제 증빙을 같은 체계로 연결합니다.

## 빠른 시작

가속기나 비공개 구성요소 권한 없이 저장소를 살펴볼 수 있습니다.

```bash
git clone https://github.com/ai-computing/ai-rm.git
cd ai-rm
python3 tools/airm.py list
```

구성요소 설치와 클러스터 준비는 [시작하기](docs/ko/getting-started.md)를 참고하세요. 공개 구성요소만 사용할 때는 [경로를 선택해 초기화](docs/ko/getting-started.md#공개-구성요소-선택-초기화)합니다. 재귀 clone은 비공개 `duet`도 받으려 합니다.

## 아키텍처

<picture>
  <source media="(max-width: 600px) and (prefers-color-scheme: dark)" srcset="docs/assets/overview-mobile-dark.svg">
  <source media="(max-width: 600px)" srcset="docs/assets/overview-mobile-light.svg">
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/overview-dark.svg">
  <img src="docs/assets/overview-light.svg" width="100%" alt="목표 구조: AI-RM은 자원·클러스터·운영 통합을 맡고, Optimus Prime은 추론 런타임과 FASOP 계획 요소를 포함하며, GPU·NPU·CPU·통합메모리 연구를 연결합니다.">
</picture>

**통합 진행 단계입니다.** [`aicomp`](https://github.com/ai-computing/aicomp)의 Optimus Prime을 통합 추론 엔진으로 두는 방향입니다. FASOP은 현재 학습 병렬화 전략을 탐색하며 추론용 계획은 후속 구현입니다. 기존 저장소는 고정된 이전 소스로 유지합니다. [5계층 아키텍처](docs/ko/architecture.md), [엔진 통합 설계](docs/ko/engine-integration.md), [현재 상태](docs/ko/status.md)를 참고하세요.

## 구성요소

| 영역 | 구성요소 |
|---|---|
| **엔진·계획** | `aicomp`의 [Optimus Prime · `opt_prime`](https://github.com/ai-computing/aicomp/tree/main/opt_prime), [FASOP · `fasop`](https://github.com/ai-computing/aicomp/tree/main/fasop) |
| **자원 탐지** | [rm_abstract_layer](https://github.com/ai-computing/rm_abstract_layer) |
| **이전 소스** | [rngd-pd](https://github.com/ai-computing/rngd-pd) · [hetero-npu-p2p](https://github.com/ai-computing/hetero-npu-p2p) · [npu-offload](https://github.com/ai-computing/npu-offload) |
| **클러스터 통합** | [llm-d-setup](https://github.com/ai-computing/llm-d-setup) · [rm-core 계약](https://github.com/ai-computing/rm-core) |
| **운영·측정** | [lmd-top](https://github.com/ai-computing/lmd-top) · [rm-bench](https://github.com/ai-computing/rm-bench) |
| **워크로드** | [npu-lora](https://github.com/ai-computing/npu-lora) · **duet** (비공개·선택 사항) |

역할, 소스 이전 방향, 통합 작업은 [구성요소 디렉터리](docs/components/README.md)에 정리했습니다.

## 문서

| 목적 | 안내 |
|---|---|
| **프로젝트 이해** | [개요](docs/ko/project-overview.md) · [아키텍처](docs/ko/architecture.md) · [연구 시나리오](docs/ko/research-scenarios.md) |
| **구현 연결** | [엔진 설계](docs/ko/engine-integration.md) · [인터페이스](docs/ko/interfaces.md) · [통합 가이드](docs/ko/integration-guide.md) |
| **실행과 평가** | [시작하기](docs/ko/getting-started.md) · [배포](deploy/README.ko.md) · [성과지표·증빙](docs/ko/kpi-map.md) |
| **진행 상태 확인** | [현재 상태](docs/ko/status.md) · [계획 설정](config/engine-integration.yaml) |

[전체 문서](docs/ko/README.md) · [English documentation](docs/README.md) · [용어집](docs/ko/glossary.md)

## 기여

구현 경계, 문서 작성, 검증 방법은 [기여 안내](CONTRIBUTING.md)를 확인하세요. 질문과 제안은 [GitHub Issues](https://github.com/ai-computing/ai-rm/issues)를 이용합니다. 사이트 설정과 자격 증명은 추적 파일에 넣지 않으며 [보안 안내](docs/ko/security.md)를 따릅니다.

## 라이선스

통합 저장소는 [BSD-3-Clause](LICENSE)를 따릅니다. 각 구성요소에는 해당 저장소의 라이선스가 적용됩니다.
