# 보안 규칙

ai-rm은 공개 저장소이고, 구성요소 repo는 비공개지만 언제든 공개될 수 있다고 보고 관리한다.

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
2. `git filter-repo --replace-text`로 과거 커밋에서도 지운 뒤 강제 push한다.
3. 그 repo를 받아 둔 모든 곳에서 `git fetch && git reset --mixed origin/<branch>`로 새 이력에 맞춘다.
