<div align="center">

<h1>rm-controller</h1>

<h3>이종 llm-d 풀을 위한 토폴로지 인지 배치</h3>

<p>
  <a href="README.md">English</a> · <strong>한국어</strong>
</p>

<p>
  <a href="https://github.com/ai-computing/ai-rm"><img src="https://img.shields.io/badge/ai--rm-L4%20cluster%20%26%20placement-fbbf24" alt="ai-rm L4 계층"></a>
  <a href="https://github.com/ai-computing/rm-core/blob/v0.1.1/PROTOCOL.md"><img src="https://img.shields.io/badge/protocol-v0.1-7c5cff" alt="프로토콜 v0.1"></a>
  <a href="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml"><img src="https://github.com/ai-computing/ai-rm/actions/workflows/packages.yml/badge.svg" alt="packages CI"></a>
  <img src="https://img.shields.io/badge/stage-first%20version-107e72" alt="단계: 1차 구현">
  <a href="../../LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-64748b" alt="라이선스: BSD-3-Clause"></a>
</p>

<p>
  <a href="#-빠른-시작"><b>빠른 시작</b></a> ·
  <a href="#-배치-정책"><b>정책</b></a> ·
  <a href="#-spec"><b>Spec</b></a> ·
  <a href="#-검증"><b>검증</b></a> ·
  <a href="#-로드맵"><b>로드맵</b></a>
</p>

</div>

---

**rm-controller**는 [ai-rm](https://github.com/ai-computing/ai-rm)의 L4 배치 컨트롤러입니다. L1이 게시한 가속기
(`AcceleratorProfile`)와 노드 상태를 읽고, spec이 요구하는 prefill/decode 풀을 배치하고, 결정을 ConfigMap `airm-placement`에
씁니다. EPP scorer와 lmd-top이 이 ConfigMap을 읽습니다(형식: llm-d-setup `deploy/airm/README.md`, 키 `decisions.json`).

<table>
<tr>
<td width="33%" valign="top">
<b>🧭 토폴로지 우선</b><br>
host-local KV 경로는 prefill과 decode를 한 노드의 서로 다른 카드에 둡니다. cordon·NotReady 노드는 고르지 않습니다.
</td>
<td width="33%" valign="top">
<b>🧮 파드가 아니라 풀 단위</b><br>
풀마다 P:D 1:N, 풀은 순서대로 배치하고 카드를 공유하지 않으며, 들어갈 곳이 없으면 이유와 함께 빈 결정을 남깁니다.
</td>
<td width="33%" valign="top">
<b>📝 바뀔 때만 기록</b><br>
결정이 바뀔 때만 문서의 <code>generation</code>이 올라가, 같은 내용을 다시 써서 읽는 쪽을 깨우지 않습니다.
</td>
</tr>
</table>

## 🚀 빠른 시작

```bash
pip install -e packages/rm-controller            # rm-core, PyYAML. [k8s]는 클러스터 안 클라이언트 추가
rm-controller --spec packages/rm-controller/examples/spec.yaml --dry-run   # 쓸 내용만 출력
rm-controller --spec spec.yaml --once            # 결정이 바뀌었으면 기록 (generation +1)
rm-controller --spec spec.yaml --interval 60     # 계속 배치
python -m rm_core.conformance airm.placements topology
```

파드 밖에서는 현재 kubeconfig로 `kubectl`을, 파드 안(`KUBERNETES_SERVICE_HOST` 있음)에서는 Python 클라이언트
(`pip install -e "packages/rm-controller[k8s]"`)를 씁니다. 종료 코드: 0 기록 또는 변경 없음, 1 배치하지 못한 풀이 있음(문서에 이유를
남김), 2 사용법·클러스터 오류.

## 🧭 배치 정책

정책 `topology`, entry point `airm.placements:topology`. 첫 end-to-end 실행에서 드러난 문제(ai-rm [e2e](../../docs/ko/e2e.md):
rm-core 참조 `greedy`가 cordon된 노드의 같은 카드에 prefill과 decode를 둠)를 바탕으로 만들었습니다.

| 규칙 | 이유 |
|---|---|
| `shm`, `p2p`, `loopback`은 prefill·decode를 **한 노드**에, `loopback`이 아니면 카드는 서로 다르게 | KV 경로가 호스트 안에 있음 |
| cordon·NotReady 노드 제외 | 그곳 배치는 실행될 수 없음 |
| prefill은 **최고 peak**(워크로드 정밀도 기준), decode는 **최대 메모리**, 동점은 낮은 카드 번호 | prefill은 연산, decode는 메모리가 좌우, 선택이 안정적 |
| 역할별 `count` | P:D 1:N |
| 풀은 순서대로, 카드 공유 없음 | 중복 배정 방지 |
| 들어갈 곳이 없으면 이유와 함께 빈 결정 | 오류로 멈추지 않고 이유가 남음 |

`place()`는 rm-core의 워크로드 단위 계약을 지키고(적합성 PASS), `place_pd()`는 prefill/decode 쌍을 함께 배치합니다.

## 📝 Spec

```yaml
namespace: llm-serving                 # airm-placement가 있는 네임스페이스 (llm-d 네임스페이스)
pools:
  - pool: llama8b-pd-pool              # InferencePool 이름
    model: meta-llama/Llama-3.1-8B-Instruct
    kv_transport: shm                  # airm.kv_transports 이름
    slo: {tpot_p90_ms: 100}
    prefill: {accelerator: furiosa.RNGD, count: 1}
    decode:  {accelerator: furiosa.RNGD, count: 1}
```

`accelerator`는 노드 레이블 `airm.ai-computing.io/<vendor>.<model>`과 같은 `vendor.model` 형식입니다. 예시:
[`examples/spec.yaml`](examples/spec.yaml)(shm으로 RNGD+RNGD), [`examples/hetero-p2p.yaml`](examples/hetero-p2p.yaml)
(같은 호스트 P2P로 RNGD prefill, ATOM ×2 decode).

## ✅ 검증

- 실제 클러스터 모양의 풀로 테스트 12개, `rm_core.conformance airm.placements topology` PASS, CI에서 둘 다 실행.
- 실제 클러스터 읽기 전용 dry-run(2026-10-19): shm 풀은 `npu-node-1/furiosa:0` + `furiosa:1`(end-to-end 실행에서 손으로 고정했던 배치와
  같음, cordon된 노드는 제외), p2p 풀은 RNGD 0 + ATOM 0, 1.

## 🗺 로드맵

- [ ] 실시간 부하(`airm_*` 대기열, TPOT)와 워크로드 모양([트레이스](../../docs/ko/workload-traces.md))을 선택에 반영
- [ ] 결정대로 움직이는 서빙 파드 (지금은 사이트 값이 같은 카드를 고정)
- [ ] 클러스터에 상주할 이미지와 chart (umbrella chart의 일부)
- [ ] `airm-placement` 형식을 rm-core 프로토콜에 규범화

## 📄 라이선스

[ai-rm](../../LICENSE)과 같은 BSD-3-Clause.
