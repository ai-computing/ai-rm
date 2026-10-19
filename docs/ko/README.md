# 문서

[AI-RM 첫 화면](../../README.ko.md) · [English](../README.md)

AI-RM은 이종 자원 연구, 클러스터 통합, 재현 가능한 평가를 연결합니다. **처음 방문했다면** [프로젝트 개요](project-overview.md)에서 시작해 [아키텍처](architecture.md)를 살펴보세요.

## 목적별 안내

| 목적 | 시작 문서 | 이어서 읽기 |
|---|---|---|
| **프로젝트 이해** | [프로젝트 개요](project-overview.md) | [연구 시나리오](research-scenarios.md) · [용어집](glossary.md) |
| **현재 구성요소 실행** | [시작하기](getting-started.md) | [배포](../../deploy/README.ko.md) · [현재 상태·접근 권한](status.md) · [로드맵](roadmap.md) |
| **통합 엔진 구현** | [Optimus Prime + FASOP 설계](engine-integration.md) | [엔진 카드](../components/optimus-prime.md) · [FASOP 카드](../components/fasop.md) |
| **구현 연결** | [통합 가이드](integration-guide.md) | [인터페이스](interfaces.md) · [구성요소 계약](component-contract.md) |
| **결과 평가** | [성과지표·증빙](kpi-map.md) | [end-to-end 실행](e2e.md) · [워크로드 트레이스](workload-traces.md) · [측정 정의](interfaces.md) |
| **기여** | [기여 안내](../../CONTRIBUTING.md) | [보안](security.md) · [시각 자료](../assets/README.md) |

## 참조

- [구성요소 디렉터리](../components/README.md) — 역할, 소스 저장소, 통합 작업 카드.
- [아키텍처](architecture.md) — 5계층 구조, 요청 흐름, 메모리 경로.
- [계획 설정](../../config/engine-integration.yaml) — 엔진 소유권과 이전 완료 기준. 실행 설정은 아닙니다.
- [rm-core 규범 문서](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md) — 인터페이스 정의.

엔진 통합은 계획 단계입니다. 현재 구현 경계와 접근 권한은 [상태 문서](status.md)에서 확인하세요. 구성요소 작업 카드는 요구 사항이며 완료 증빙이 아닙니다. 기존 소스별 상세 작업 카드는 한국어로 유지합니다.
