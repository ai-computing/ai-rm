# AI-RM 한국어 문서

[프로젝트 첫 화면](../../README.ko.md) · [English documentation](../README.md)

**「AI 반도체 통합 자원관리 기술 개발」 과제의 버전 관리되는 문서·지식 베이스입니다.** GitHub에서 위키처럼 탐색하고 체크아웃과 함께 읽을 수 있습니다. 별도 GitHub Wiki 초기화는 필요하지 않습니다.

**현재 설계 방향:** AI-RM은 자원·클러스터·증빙을 연결하고, `aicomp`의 **[Optimus Prime + FASOP](engine-integration.md)**을 통합 엔진으로 둡니다. [계획 설정](../../config/engine-integration.yaml)은 이전 책임과 전환 기준을 기록하며 새 런타임을 활성화하지 않습니다.

![AI-RM 5계층 아키텍처](../assets/architecture.svg)

| 읽는 분 | 시작 문서 | 이어서 읽기 |
|---|---|---|
| 과제 방문자·검토자 | [프로젝트 개요](project-overview.md) | [연구 시나리오](research-scenarios.md) · [성과지표](kpi-map.md) |
| 연구자 | [아키텍처](architecture.md) | [인터페이스](interfaces.md) · [구성요소](../components/README.md) |
| 엔진 구현 담당자 | [Optimus Prime 통합 설계](engine-integration.md) | [FASOP 카드](../components/fasop.md) · [엔진 카드](../components/optimus-prime.md) |
| 통합 개발자 | [시작하기](getting-started.md) | [통합 가이드](integration-guide.md) · [구성요소 계약](component-contract.md) |
| 운영자 | [현재 상태·접근 권한](status.md) | [배포](../../deploy/README.ko.md) · [보안](security.md) |
| 문서 기여자 | [기여 방법](../../CONTRIBUTING.md) | [시각 자료·프롬프트](../assets/README.md) · [용어집](glossary.md) |

인터페이스의 규범 정의는 [rm-core PROTOCOL.md](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md)입니다. 구성요소 작업 카드는 통합 요구 사항이며 완료 증빙은 아닙니다. 실제 준비 상태는 고정된 커밋의 구현과 검증 결과를 확인하세요.
