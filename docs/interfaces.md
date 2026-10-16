# 계층 간 인터페이스 (초안)

구성요소를 하나로 합치지 않고 묶는 기준은 계층 사이의 **계약**이다. 아래는 각 계약의 최소 형태와,
이미 있는 코드 중 어디가 그 계약에 해당하는지다. 다음 단계에서 작은 `rm-core` 패키지(타입과 Protocol만,
표준 라이브러리 의존)로 코드화하고 각 구성요소가 adapter로 구현한다.

## Accelerator (L1)

장치 하나의 능력. 배치 정책(L4)과 KPI 계산(MFU의 분모, 전력효율)이 이 값을 쓴다.

```python
@dataclass
class Accelerator:
    id: str                      # "<node>/<vendor>:<index>"
    vendor: str                  # nvidia | furiosa | rebellions | cpu | nvidia-gb10
    model: str                   # A100 | RNGD | ATOM-CA22 | ...
    memory_bytes: int
    memory_kind: str             # hbm | gddr | dram | unified
    peak_tflops: dict[str, float]   # {"bf16": 256.0, "fp16": ...}; 출처를 함께 기록
    power_limit_w: float | None
    interconnect: list[str]      # ["pcie5", "p2p-dma", "nvlink-c2c"]
```

- 현재 구현: `rm_abstract_layer`의 `ResourceInfo`/`ResourceCapability`(`resources/base.py`)와 벤더 플러그인
  (`resources/npu/furiosa.py`, `resources/npu/rebellions.py`, `resources/gpu/nvidia.py`).
- 확장: `peak_tflops`(정밀도별), `memory_kind`, `interconnect`, 전력 정보. GB10 통합메모리 장치 모델 추가.

## MemoryTier / KVTransport (L2)

메모리 계층과 그 사이 이동. 같은 계약 아래에 서로 다른 경로가 들어간다.

```python
class MemoryTier(Protocol):
    name: str                    # "rngd-hbm" | "host-dram" | "gb10-unified" | ...
    capacity_bytes: int
    def bandwidth_to(self, other: "MemoryTier") -> float: ...   # bytes/s, 측정값

class KVTransport(Protocol):
    def plan(self, src: KVLayout, dst: KVLayout, tokens: range) -> TransferPlan: ...
    def submit(self, plan: TransferPlan) -> TransferHandle: ...   # 비동기, 완료 fence 필수
    def wait(self, handle: TransferHandle, timeout_s: float) -> TransferResult: ...
```

| 경로 | 구현 |
|---|---|
| NPU↔NPU P2P (RNGD→ATOM) | `hetero-npu-p2p`: `hetero_p2p.core`(소유권·범위 검사), `backend`/`native`(completion-fenced PDMA), `layout`(KV 배치) |
| llm-d stage 연동 | `hetero_p2p.llmd`(요청 ID·fingerprint·TTL 검사 broker), `rngd-pd`의 `connector/rngd_kv.py`(vLLM `KVConnectorBase_V1`) |
| NPU↔Host 오프로딩 | `npu-offload`(cold expert를 호스트에서 계산, PCIe로 activation만 이동) |
| CPU↔GPU 통합메모리 | `duet`(복사 없는 공유 코퍼스, CPU 순회 + GPU 거리 계산) |

## Workload / Placement (L3–L4)

어떤 작업을 어느 가속기에 둘지.

```python
@dataclass
class Workload:
    kind: str                    # prefill | decode | train | embed | search
    model: str
    slo: dict[str, float]        # {"ttft_p90_s": 4.0, "tpot_p90_ms": 100}
    batch_hint: int | None

class Placement(Protocol):
    def place(self, w: Workload, pool: list[Accelerator]) -> list[str]: ...   # Accelerator.id 목록
```

- 현재 구현: llm-d EPP 설정과 InferencePool(`llm-d-setup/manifests/epp/`), PD 분리 배치(`rngd-pd` serving).
- 다음 단계: 장치 능력(Accelerator)과 전력 지표를 읽는 EPP 플러그인으로 배치 정책을 코드화.

## Metrics (전 계층)

모든 구성요소가 같은 이름과 단위로 지표를 낸다. 연구 기록(`report.py --metric`, MLflow)도 같은 이름을 쓴다.

| 키 | 단위 | 의미 |
|---|---|---|
| `ttft_p50_ms`, `ttft_p90_ms`, `ttft_p99_ms` | ms | 첫 토큰 시간 |
| `tpot_p50_ms`, `tpot_p90_ms`, `tpot_p99_ms` | ms | 출력 토큰당 시간 |
| `tok_s` | tokens/s | 생성 처리량 (전체) |
| `req_s` | requests/s | 요청 처리량 |
| `power_w` | W | 측정 구간 평균 전력 (측정 범위를 태그로: card/node) |
| `gflops_per_w` | GFLOPS/W | 전력효율 |
| `mfu_pct` | % | 모델 FLOPs 활용률 (분모 peak의 출처를 태그로) |
| `kv_transfer_ms` | ms | 요청당 KV 이동 시간 |
| `accuracy_pct` | % | 정확도 (데이터셋을 태그로) |

Prometheus로 내보낼 때는 `airm_` 접두어를 붙인다(`airm_tpot_p90_ms`).
