[English](../security.md) · [한국어 문서 홈](README.md)

# 보안 규칙

ai-rm과 다수 구성요소는 공개 저장소입니다. 비공개로 유지하는 duet도 공개될 수 있다고 보고 비밀정보를 분리합니다. 실제 접근 상태는 [현재 상태](status.md)를 확인하세요.

## 넣지 않는 것

- 내부 IP 주소 (10.x, 172.16–31.x, 192.168.x, 기관 대역)
- 자격 증명: 비밀번호, API 토큰(GitHub, Hugging Face, 클라우드), kubeconfig 인증 정보, SSH/TLS 개인 키
- 비밀번호나 토큰이 들어간 URL
- 공개 전 성능 수치와 과제 증빙 (이 저장소에 한함)

## 대신 쓰는 것

| 대상 | 방법 |
|---|---|
| 노드·게이트웨이 주소, 포트 | 환경 변수. 키 목록은 `cluster.example.env`, 실제 값은 `cluster.local.env`(추적 안 함) |
| 문서의 주소 예시 | `<gateway-host>` 같은 자리표시자, RFC 5737 주소 `192.0.2.x` |
| 테스트용 가짜 토큰 | `hf_EXAMPLE...`처럼 가짜임이 드러나는 값. 불가피하면 `.sensitive-allow`에 그 줄의 정규식 |
| k8s 사이트 설정 | `deploy/clusters/<name>/`(추적 안 함). `deploy/clusters/example/`만 커밋 |

## 검사

- `make check`: ai-rm과 받아 둔 모든 구성요소의 추적 파일을 검사한다(`tools/check_sensitive.py`).
- 구성요소 repo에서는 `python3 .research/check_sensitive.py`를 push 전에 실행한다.
- GitHub Actions(`.github/workflows/check-sensitive.yml`)가 ai-rm의 push와 PR마다 같은 검사를 돌린다.

## 이미 들어간 경우

1. 현재 파일에서 값을 빼고(위 표), 그 값이 실제 자격 증명이면 **먼저 폐기·교체**한다.
2. 유지관리자와 과거 커밋·브랜치·태그·PR 참조의 정리를 조율한다. 이력 재작성과 강제 push는 변경 범위를 확인하고 진행한다.
3. 기존 체크아웃은 새 clone이나 신중한 rebase로 정리한다. 이전 이력을 merge하면 제거한 값이 재유입될 수 있으며 GitHub 캐시·PR 참조는 별도 조치가 필요할 수 있다.

검사 도구는 추적·stage된 현재 텍스트 파일을 검사합니다. 미추적 파일과 전체 Git 이력 검사는 별도이며, 공개 전환 전에는 과거 브랜치·태그도 검토해야 합니다. 이력 재작성은 커밋 해시 변경·강제 push·다른 체크아웃 정리가 필요하므로 유지관리자와 조율합니다.
