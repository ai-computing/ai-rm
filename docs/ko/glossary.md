# 용어집

[문서 홈](README.md) · [English](../glossary.md)

| 용어 | 의미 |
|---|---|
| Optimus Prime | aicomp의 통합 추론 엔진 목표, 현재 런타임 소스는 opt_prime/ |
| FASOP | 같은 제품의 계획·탐색 요소(aicomp/fasop), 현재 학습 비용 탐색과 향후 추론 계획을 구분 |
| Integration plan | 실행하지 않는 소유권·이전 registry, 실제 구성요소 매니페스트·배포 설정과 구분 |
| Accelerator abstraction | 하드웨어별 구현 위에서 장치 탐지·능력을 공통으로 표현하는 경계 |
| NPU | Neural Processing Unit, 실제 지원은 벤더·구성요소별 확인 |
| RNGD / ATOM | 이종 NPU 시나리오에 사용하는 FuriosaAI / Rebellions 장치 계열 |
| GB10 / 통합메모리 | 비공개 duet에서 CPU–GPU 협업 검색을 연구하는 시스템 환경 |
| HBM / Host DRAM | 장치 고대역폭 메모리 / 호스트 메모리 계층 |
| Prefill / Decode | 프롬프트 처리 / 반복적인 출력 토큰 생성 단계 |
| PD disaggregation | Prefill과 decode를 별도 실행 단계로 분리하는 서빙 |
| KV cache | 추론 중 재사용하는 attention key/value 상태 |
| P2P / Host staging | 지원 조건의 직접 peer 전송 / 명시적인 호스트 메모리 경유 |
| Completion fence | 수신 측 사용 전에 전송 완료를 보장하는 동기화 경계 |
| MoE / Expert offload | Mixture of Experts / 전문가 실행을 장치와 호스트에 분담 |
| LoRA | Low-rank adaptation, 효율적인 fine-tuning을 위한 접근 중 하나 |
| EPP / InferencePool | llm-d·Kubernetes 추론 라우팅 연결 지점, EPP는 Endpoint Picker 확장 |
| TTFT / TPOT / E2E | 첫 토큰 시간 / 출력 토큰당 시간 / 전체 요청 지연 |
| SLO | 주어진 워크로드의 서비스 수준 목표 |
| MFU | Model FLOPs Utilization, 정밀도와 peak 출처를 함께 해석 |
| Entry point / Adapter | 이름으로 등록하는 플러그인 / 구현을 공통 계약에 연결하는 wrapper |
| Conformance SKIP | 요구 조건이 없어 검증하지 못함, PASS와 구분 |
| 고정 서브모듈 | 통합 저장소가 기록한 정확한 구성요소 커밋 |
