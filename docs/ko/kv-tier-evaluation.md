# KV 계층 평가: LMCache, Mooncake Store, llm-d, Dynamo KVBM

[문서](README.md) · [English](../kv-tier-evaluation.md) · [로드맵](roadmap.md) (W4) · [워크로드 트레이스](workload-traces.md)

로드맵 W4의 질문: [aicomp #52](https://github.com/ai-computing/aicomp/issues/52)의 host-DRAM KV 계층을 기존 시스템 중 하나로 할지,
직접 만들지. 이 문서는 각 시스템이 추론 엔진에 무엇을 요구하는지, 우리 NPU 엔진에서 돌 수 있는지, Mooncake 트레이스에서 DRAM
계층이 무엇을 주는지 비교합니다. 2026-10-19 조사, 버전과 링크는 그날 기준입니다.

## 결정

**Optimus Prime 안에 작은 엔진 로컬 DRAM 계층을 만든다(aicomp #52, 아래 인터페이스에 맞춰). 이를 위해 LMCache, Dynamo KVBM,
vLLM OffloadingConnector는 채택하지 않는다. 공유 계층(Mooncake Store)은 모델당 prefill 인스턴스가 여럿이고 노드 간 KV 전송이
생길 때까지 미룬다.** 벤더 엔진이 이미 계층을 제공하면 그것을 쓴다. furiosa-llm 2026.4에는 계층형 prefix caching(NPU → host →
선택적 Mooncake Store)이 있고, vllm-rbln master에는 RBLN LMCache connector와 RBLN NIXL connector가 있습니다.

이유:

1. **후보 모두 vLLM KV connector API나 CUDA 메모리를 전제로 합니다.** LMCache, KVBM, OffloadingConnector는
   `KVConnectorBase_V1`(scheduler·worker 두 부분, 레이어별 save/load hook, paged block table)에 붙고 CUDA/ROCm/XPU 복사로
   데이터를 옮깁니다. Optimus Prime은 vLLM이 아니고 그래프를 고정 시퀀스 길이로 미리 컴파일하므로, 이들을 올리려면 connector API를
   흉내 내야 합니다. 엔진 중립적인 것은 Mooncake Transfer Engine/Store뿐입니다(put/get과 등록된 메모리 세그먼트를 쓰는 C++/Python
   객체 저장소, host 메모리는 TCP 전송).
2. **우리 트레이스에서는 장치 메모리 prefix cache가 먼저입니다.** Mooncake tool-agent에서 4 GiB 캐시는 프롬프트 토큰의 27.5 %,
   16 GiB는 34.3 %를 아낍니다. HBM 4 GiB 뒤의 DRAM 계층은 64 GiB에서 7.8%p, 256 GiB에서 11.1%p를 더합니다. 즉 #52보다
   aicomp #46(HBM prefix 재사용)이 먼저입니다. DRAM 계층은 장치 메모리에 여유가 없을 때 가장 중요합니다. ATOM(가중치 옆 약 4K 토큰)은
   64 GiB host 계층으로 35.2 %, 없으면 0입니다.
3. **재적재 경로는 재계산보다 빠르기만 하면 되고, NPU에서는 기준이 낮습니다.** RNGD prefill 2,500 tok/s는 KV를 0.33 GB/s(2,500 ×
   128 KiB)로 만들어 내므로, 지금 측정된 host 경유 복사(0.6 GB/s)도 재계산보다 빠릅니다. A100은 KV를 약 1.3 GB/s로 만들어 같은
   0.6 GB/s 경로를 쓰면 캐시가 없을 때보다 느려집니다(평균 prefill 0.88 → 1.24초). 요청별 재적재·재계산 선택이 인터페이스에
   들어가야 합니다.
4. **공유 저장소는 prefill이 여러 인스턴스에 흩어지거나 재사용 거리가 한 호스트를 넘을 때 도움이 됩니다.** Mooncake 대화는 재사용이
   멀리 떨어져 있어 128 GiB 미만에서는 토큰의 5 % 미만, 256 GiB에서 8.9 %, 1 TiB에서야 27 %입니다. 클러스터 단위 저장소(Mooncake
   Store가 겨냥하는 곳)의 일이며, W3의 전송과 여러 prefill 인스턴스가 필요한데 둘 다 아직 없습니다.

## Mooncake 트레이스에서 DRAM 계층이 주는 것

`python3 packages/rm-bench/tools/kv_tier_curve.py ~/.cache/rm-bench/traces --format md`(`rm-bench traces fetch` 후). 모든 블록
접근의 LRU stack distance를 한 번 계산해 모든 캐시 크기의 적중률을 얻습니다. **prefix 적중**은 요청 안에서 그 앞 블록이 모두
캐시에 있을 때만 셉니다(prefill은 첫 미스에서 다시 시작하므로 엔진이 실제로 재사용할 수 있는 양). 블록은 Llama-3.1-8B bf16 KV
512토큰(64 MiB). 모든 prefill 앞에 캐시 하나를 가정합니다: 인스턴스 하나, 공유 저장소, 또는 보유자를 항상 찾는 라우터.

크기별 LRU prefix cache가 아끼는 프롬프트 토큰:

| 캐시 | 1 GiB | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 | 512 | 1024 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Mooncake tool-agent | 13.6 % | 21.3 | 27.5 | 32.0 | 34.3 | 34.9 | 35.2 | 35.9 | 38.5 | 45.4 | 51.6 |
| Mooncake 대화 | 2.3 % | 3.3 | 4.0 | 4.2 | 4.3 | 4.3 | 4.5 | 5.6 | 8.9 | 18.5 | 27.1 |

이 트레이스에서는 블록 적중과 prefix 적중이 같습니다(블록 해시가 앞부분 전체를 덮고, 부모는 항상 자식 바로 앞에 쓰이므로 LRU가
부모 없이 자식만 남기지 않음). [워크로드 트레이스](workload-traces.md)의 "4 GB에서 27 %"와 같은 수치입니다.

tool-agent에서 두 계층(HBM 앞, DRAM 뒤, 배타적, LRU 순서 하나). 요청당 평균 prefill 시간은 rm-controller 프로파일(RNGD 2,500 tok/s
+ 60 ms, 측정·유도; A100 10,000 tok/s + 20 ms, 추정)과 두 재적재 경로(측정된 host 경유 복사 0.6 GB/s, PCIe DMA 16 GB/s 추정)로
계산했습니다:

| HBM | DRAM | HBM에서 토큰 | DRAM에서 | RNGD, 0.6 GB/s | RNGD, 16 GB/s | A100, 0.6 GB/s | A100, 16 GB/s |
|--:|--:|--:|--:|--:|--:|--:|--:|
| 0 | 0 | 0 % | 0 % | 3.50초 | 3.50 | 0.88 | 0.88 |
| 0 | 64 GiB | 0 | 35.2 | 2.95 | 2.31 | 1.24 | 0.60 |
| 0 | 256 GiB | 0 | 38.5 | 2.90 | 2.20 | 1.27 | 0.58 |
| 4 GiB | 0 | 27.5 | 0 | 2.55 | 2.55 | 0.64 | 0.64 |
| 4 GiB | 64 GiB | 27.5 | 7.8 | 2.43 | 2.29 | 0.72 | 0.58 |
| 4 GiB | 256 GiB | 27.5 | 11.1 | 2.38 | 2.18 | 0.76 | 0.56 |
| 16 GiB | 0 | 34.3 | 0 | 2.32 | 2.32 | 0.59 | 0.59 |
| 16 GiB | 64 GiB | 34.3 | 1.0 | 2.30 | 2.29 | 0.60 | 0.58 |
| 16 GiB | 256 GiB | 34.3 | 4.6 | 2.25 | 2.17 | 0.63 | 0.55 |

우리 카드로 읽으면:

- **RNGD**(가중치 뒤 약 32 GB, 일부는 진행 중 KV에 필요): HBM 4–16 GiB prefix cache로 평균 prefill이 27–34 % 줄고, 뒤의 DRAM
  계층이 1–15 %를 더 줄입니다(16 GiB보다 4 GiB 뒤에서, 빠른 재적재 경로일수록 큼). 가치는 있지만 두 번째 순서입니다.
- **ATOM**(HBM 여유 없음): host 계층만이 재사용을 줍니다 — 토큰의 35 %. HBM 0 행(RNGD 속도)은 재적재 경로에 따라 prefill
  시간이 16–34 % 줄고, ATOM은 prefill이 느려 같은 재적재가 상대적으로 더 쌉니다. ATOM prefill은 지금 서빙 경로에 없으므로(`optimal`이
  고르지 않음), ATOM prefill이나 긴 문맥 ATOM decode가 생길 때 중요해집니다.
- **Mooncake 대화**는 수백 GiB–1 TiB가 필요합니다. 엔진별 계층이 아니라 클러스터 공유 저장소의 일입니다.
- 모델링하지 않은 것: 캐시를 모르는 라우터 뒤의 인스턴스별 캐시(적중 감소, W4의 EPP prefix scorer가 다룸), suffix prefill 중 캐시된
  prefix의 attention 비용, 컴파일 그래프 제약(RNGD/ATOM의 재사용 단위는 512토큰이 아니라 컴파일된 prefill chunk).

## 시스템별

| | LMCache | Mooncake Store + Transfer Engine | llm-d KV cache (indexer + tiered prefix cache) | Dynamo KVBM | vLLM OffloadingConnector |
|---|---|---|---|---|---|
| 정체 | vLLM(및 SGLang)용 KV 캐시 계층: CPU/디스크/원격 계층, NIXL로 P2P·PD, 비prefix 재사용 CacheBlend | 다중 전송 transfer engine 위의 분산 KV 객체 저장소(DRAM + SSD, 복제) | 어떤 pod가 어떤 계층에 어떤 블록을 가졌는지의 라우팅 측 색인 + vLLM(native 또는 LMCache)으로 offload하는 레시피 | NVIDIA 블록 관리자: G1 GPU, G2 host, G3 SSD, G4 원격 | vLLM 내장 GPU → pinned host(→ fs/obj/p2p) prefix cache 확장 |
| 엔진 인터페이스 | `LMCacheConnectorV1` / `LMCacheMPConnector` (vLLM `KVConnectorBase_V1`) | Python/C++ 클라이언트: 키 객체 put/get/remove, 등록 버퍼. vLLM `MooncakeConnector`/`MooncakeStoreConnector`, SGLang HiCache, LMCache backend, NIXL plugin | 엔진이 `BlockStored`/`BlockRemoved` 이벤트 발행(ZMQ 위 msgpack, topic `kv@<pod>@<model>`, 계층은 `medium` 필드). indexer는 토큰을 직접 해시(정규 CBOR `[parent, tokens, extra]`에 FNV-64a, vLLM `PYTHONHASHSEED`처럼 seed, 기본 블록 16) | vLLM / TensorRT-LLM / SGLang connector (scheduler leader + worker) | `--kv-transfer-config '{"kv_connector":"OffloadingConnector", ...}'`, `cpu_bytes_to_use`, 블록 크기는 GPU 블록의 배수 |
| 장치 의존 | CUDA 기준 커널. ROCm, XPU, MUSA, NPU 스택, Neuron(engine-driven만), HPU backend. 추가 = `DeviceSpec` + `DeviceOps`(torch op fallback) | host 메모리는 없음(TCP/RDMA). 장치 전송은 CUDA, HIP, Ascend, MUSA 등 | indexer는 없음. offload 레시피는 GPU 위 vLLM | CUDA 복사, 디스크·원격은 NIXL | CUDA, ROCm, XPU만 |
| 기본 단위 | 256토큰 | 엔진이 정한 키 | 16토큰(설정 가능) | page size | GPU 블록 크기 |
| 라이선스 | Apache-2.0 | Apache-2.0 | Apache-2.0 | Apache-2.0 | Apache-2.0 |

### 우리 엔진과의 적합성

| 엔진 | 장치 메모리 prefix cache | host 계층 | llm-d용 KV 이벤트 | 경로 |
|---|---|---|---|---|
| furiosa-llm (RNGD) | 있음, SDK 2026.1부터 기본(토큰 단위 radix tree, leaf부터 LRU) | **2026.4에 실험 기능**: L2 host 메모리(`--experimental-kv-offload-host-memory-gb`), write-through/write-back, 레이어별 재적재. L3 Mooncake Store 선택(dlopen) | 문서에 없음 | 2026.3에서 2026.4로 올리고 L2 활성화, rm-bench tool-agent 재생으로 측정 |
| vllm-rbln (ATOM) | 있음(`prefix_block_size`, 컴파일된 prefill chunk의 배수) | master(2026-10-19)에 `RBLNLMCacheConnectorV1`(`lmcache_rbln`을 재노출, Rebellions nightly index에서만 받음 — 공개 릴리스는 확인 못 함)과 host-bounce(DRAM)·장치 간 경로를 가진 RBLN NIXL connector | 플러그인이 vLLM 이벤트 발행기를 유지하면 있음 | 이를 담은 vllm-rbln 릴리스를 추적. 배포된 0.11.0은 그 이전 |
| Optimus Prime (aicomp) | 없음(aicomp #46) | 없음(aicomp #52) | 없음(#46) | 아래 요구사항에 따른 엔진 로컬 계층 |

LMCache나 KVBM을 Optimus Prime에 올리려면 vLLM의 scheduler/worker connector 계약(`get_num_new_matched_tokens`,
`update_state_after_alloc`, `build_connector_meta`, `start_load_kv`, `wait_for_layer_load`, `save_kv_layer`, `wait_for_save`,
`request_finished`), paged block table, NPU마다 LMCache `DeviceSpec`/`DeviceOps`를 구현해야 합니다. 계층 자체보다 코드가 많고, 릴리스마다
바뀌는 vLLM 내부에 묶입니다. 열어 둘 가치가 있는 것은 Mooncake Store입니다. 클라이언트가 엔진 중립적이고, 장치 지원 없이 host
메모리 세그먼트를 TCP로 저장하며, furiosa-llm이 이미 L3로 쓰므로 나중의 공유 계층을 RNGD와 우리 엔진이 함께 쓸 수 있습니다.

## aicomp #52 (및 #46) 인터페이스 요구사항

ai-rm 쪽이 엔진의 계층에 요구하는 것입니다. 나머지 설계는 엔진 담당자가 정합니다.

1. **내용 주소 블록**(#46): 토큰 단위 고정 블록 크기, 컴파일된 prefill chunk의 배수. 블록마다 (부모 해시, 토큰 ID, LoRA 등 추가 키)에
   대한 연쇄 해시. llm-d와 같은 방식(정규 CBOR `[parent, tokens, extra]`에 FNV-64a, 모든 pod 공통 seed)으로 계산하거나, 엔진 해시를
   토큰과 함께 발행해 indexer가 대응시키게 합니다.
2. **이벤트**(#46): `BlockStored`(해시, 부모, 토큰 ID, 블록 크기, `medium`)와 `BlockRemoved`(해시, `medium`)를 vLLM msgpack 형식으로
   ZMQ topic `kv@<pod>@<model>`에. 계층마다 `medium`(HBM은 장치 계층 이름, host는 `cpu`)을 써서 EPP precise prefix-cache scorer가
   가중치를 줄 수 있게(기본 gpu 1.0, cpu 0.8). host 사본은 장치 이벤트 다음에 `medium=cpu`, 토큰 없는 `BlockStored`를 하나 더 발행.
3. **계층 동작**: 장치 → host offload(저장 시 write-through 또는 eviction 시 write-back), 캐시되지 않은 suffix를 prefill하기 전
   host → 장치 재적재, leaf부터 LRU eviction, host 예산 플래그(`--kv-host-memory-gb`). 일치한 부분 중 장치에 있는 것은 재사용하고
   나머지만 재적재(furiosa-llm 방식).
4. **재적재 또는 재계산**: `bytes / reload_bandwidth < tokens / prefill_rate`일 때만 재적재. 손익분기 대역폭은 prefill tok/s × 토큰당 KV
   바이트(RNGD 2,500 tok/s의 Llama-8B는 0.33 GB/s). 블록당 재적재 시간 보고(#52 acceptance).
5. **host 메모리**: 한 번 할당한 page-aligned·pinned host 버퍼로, NIXL `DRAM_SEG` / Mooncake 세그먼트로 등록 가능해야 나중의 공유
   계층이나 NIXL 전송(#48)이 복사 없이 옮깁니다. rm-core `MemoryTier`(`host-dram`, 용량)로 기술하고 블록 배치는 `KVLayout`으로.
6. **캐시된 prefix에서 prefill**: 과거 KV가 있는 상태로 토큰 오프셋부터 prefill을 시작하는 그래프·커널 경로(chunked prefill). 없으면
   적중해도 계산을 건너뛸 수 없습니다. 단위 = 컴파일된 chunk.
7. **지표**(#45): 계층별 prefix 적중 토큰, 재적재 바이트·지연, offload 대기열 길이, host 계층 점유.
8. **선택**: 계산과 겹치는 레이어별 재적재(#47 레이어별 전송과 같은 메커니즘).

## 검증하지 않은 것

- 우리 하드웨어에서 실행하지 않았습니다. 적중률은 모두 LRU 모델로 트레이스를 재생한 값이고, prefill 시간은 프로파일 산술입니다.
  furiosa-llm 2026.4 host 계층과 vllm-rbln LMCache connector는 문서와 소스로 읽었을 뿐 돌려 보지 않았습니다.
- `lmcache_rbln`은 vllm-rbln master가 참조하지만 Rebellions 내부 nightly index에만 있습니다. 공개 여부·시점은 모릅니다.
- 우리 노드에서 host 메모리·TCP로 Mooncake Store put/get 성능은 측정하지 않았습니다.

## 출처

출처 목록은 [영문 문서](../kv-tier-evaluation.md#sources)와 같습니다.
