# AI Accelerator Resource Management System

AI 가속기(GPU, NPU, CPU)를 위한 통합 자원 관리 시스템입니다.

---

## Submodules

| Submodule | Description |
|-----------|-------------|
| [furiosa-env-tools](furiosa-env-tools/) | FuriosaAI 드라이버/펌웨어/Runtime 자동 설치 CLI 도구 |
| [rm_abstract_layer](rm_abstract_layer/) | GPU/NPU/CPU 이기종 가속기 통합 LLM 추론 추상화 레이어 |
| [rm_monitor](rm_monitor/) | LLM 추론 모니터링 스택 (vLLM + Prometheus + Grafana) |
| [etri-zero](etri-zero/) | DeepSpeed 기반 대규모 분산 학습/추론 프레임워크 |

---

## 주요 기능

### RM Abstract Layer

- **Zero Code Change**: `from vllm import LLM` → `from rm_abstract import LLM`으로 변경만으로 다양한 디바이스 지원
- **Device Transparency**: GPU, NPU, CPU 간 런타임 전환 지원
- **Multiple Serving Engines**: vLLM, Triton, TorchServe 지원
- **Hardware Auto-Detection**: NPU > GPU > CPU 우선순위 자동 선택

### RM Monitor

- vLLM 메트릭 수집 (TTFT, TPOT, E2E, TPS)
- Prometheus + Grafana 대시보드
- Azure 트레이스 기반 트래픽 리플레이 도구

### Furiosa Env Tools

- FuriosaAI NPU 드라이버/펌웨어 자동 설치
- APT 레포 등록, 커널 헤더 설치, 검증까지 원클릭 수행

### ETRI-Zero (DeepSpeed Fork)

- 대규모 LLM 학습/추론 최적화
- ZeRO, 3D-Parallelism, MoE 지원

---

## Getting Started

```bash
# Clone with submodules
git clone --recursive https://github.com/ai-computing/ai-acc-rm.git
cd ai-acc-rm

# If already cloned
git submodule update --init --recursive
```

각 서브모듈의 상세 사용법은 해당 디렉토리의 README를 참조하세요.

---

## Repository Structure

```
.
├── furiosa-env-tools/    # FuriosaAI 환경 설정 도구
├── rm_abstract_layer/    # 이기종 가속기 추상화 레이어
├── rm_monitor/           # LLM 추론 모니터링 스택
├── etri-zero/            # DeepSpeed 기반 분산 학습 프레임워크
└── README.md
```

---

## License

각 서브모듈은 개별 라이선스를 따릅니다.

- rm_abstract_layer: MIT License
- etri-zero: Apache 2.0 License
