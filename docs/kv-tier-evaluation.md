# KV tier evaluation: LMCache, Mooncake Store, llm-d, Dynamo KVBM

[Documentation](README.md) · [한국어](ko/kv-tier-evaluation.md) · [Roadmap](roadmap.md) (W4) · [Workload traces](workload-traces.md)

Question for roadmap W4: should the host-DRAM KV tier behind [aicomp #52](https://github.com/ai-computing/aicomp/issues/52)
be one of the existing systems, or our own? This page compares what each system needs from the inference engine, whether it
can run under our NPU engines, and what a DRAM tier would buy on the Mooncake traces. Researched 2026-10-19; versions and
links as of that date.

## Decision

**Build a small engine-local DRAM tier in Optimus Prime (aicomp #52), shaped to the interfaces below; do not adopt LMCache,
Dynamo KVBM or vLLM's OffloadingConnector for it; defer a shared tier (Mooncake Store) until there is more than one
prefill instance per model and a cross-node KV transport.** Where a vendor engine already ships a tier, use it:
furiosa-llm 2026.4 has hierarchical prefix caching (NPU → host → optional Mooncake Store), and vllm-rbln's master branch
has an RBLN LMCache connector and an RBLN NIXL connector.

Why:

1. **Every candidate is built around vLLM's KV connector API or CUDA memory.** LMCache, KVBM and the OffloadingConnector
   plug into `KVConnectorBase_V1` (scheduler + worker halves, per-layer save/load hooks, paged block tables) and move data
   with CUDA/ROCm/XPU copies. Optimus Prime is not vLLM and its graphs are compiled offline for a fixed sequence length; it
   would have to emulate the connector API to host any of them. Only Mooncake's Transfer Engine/Store is engine-neutral
   (a C++/Python object store with put/get and registered memory segments, TCP transport for host memory).
2. **On our traces the device-memory prefix cache comes first.** On Mooncake tool-agent a 4 GiB cache saves 27.5 % of
   prompt tokens and 16 GiB saves 34.3 %; a DRAM tier behind 4 GiB of HBM adds 7.8 points at 64 GiB and 11.1 at 256 GiB.
   That is aicomp #46 (prefix reuse in HBM) before #52. The DRAM tier matters most where device memory has no room: ATOM
   (~4 K tokens free beside the weights) gets 35.2 % from a 64 GiB host tier and nothing without one.
3. **The reload path only has to beat recompute, which on NPUs is a low bar.** RNGD prefill at 2,500 tok/s produces KV at
   0.33 GB/s (2,500 × 128 KiB), so even today's measured host-staged copy (0.6 GB/s) reloads faster than it recomputes. An
   A100 produces KV at ~1.3 GB/s: the same 0.6 GB/s path would make it slower than no cache (0.88 → 1.24 s mean prefill).
   A per-request reload-or-recompute choice is part of the interface.
4. **A shared store helps when prefill is spread over instances or the reuse distance exceeds one host.** Mooncake
   conversation reuse is far apart: under 5 % of prompt tokens below 128 GiB, 8.9 % at 256 GiB, 27 % only at 1 TiB. That is
   a cluster-wide store's job (Mooncake Store's design point), and it needs W3's transport and several prefill instances,
   neither of which we have yet.

## What a DRAM tier buys on the Mooncake traces

`python3 packages/rm-bench/tools/kv_tier_curve.py ~/.cache/rm-bench/traces --format md` (after `rm-bench traces fetch`).
The tool computes every block access's LRU stack distance once, which gives the hit rate of every cache size; a
**prefix hit** counts a block only if every block before it in the request is cached too (what an engine can reuse, since
prefill restarts at the first miss). Blocks are 512 tokens of Llama-3.1-8B bf16 KV (64 MiB). One cache in front of all
prefill work is assumed: one instance, a shared store, or a router that always finds the holder.

Prompt tokens saved by an LRU prefix cache of a given size:

| Cache | 1 GiB | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 | 512 | 1024 |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| Mooncake tool-agent | 13.6 % | 21.3 | 27.5 | 32.0 | 34.3 | 34.9 | 35.2 | 35.9 | 38.5 | 45.4 | 51.6 |
| Mooncake conversation | 2.3 % | 3.3 | 4.0 | 4.2 | 4.3 | 4.3 | 4.5 | 5.6 | 8.9 | 18.5 | 27.1 |

In these traces block hits and prefix hits coincide (a block's hash covers its whole prefix, and the parent is always used
just before the child, so LRU never keeps a child without its parent). The 27 % at 4 GB in
[workload traces](workload-traces.md) is the same figure.

Two tiers on tool-agent (HBM in front of DRAM, exclusive, one LRU order), with mean prefill time per request from the
rm-controller profiles (RNGD 2,500 tok/s + 60 ms, measured/derived; A100 10,000 tok/s + 20 ms, estimate) and two reload
paths: the measured host-staged copy (0.6 GB/s) and a PCIe DMA (16 GB/s, estimate):

| HBM | DRAM | Tokens from HBM | from DRAM | RNGD, 0.6 GB/s | RNGD, 16 GB/s | A100, 0.6 GB/s | A100, 16 GB/s |
|--:|--:|--:|--:|--:|--:|--:|--:|
| 0 | 0 | 0 % | 0 % | 3.50 s | 3.50 s | 0.88 s | 0.88 s |
| 0 | 64 GiB | 0 | 35.2 | 2.95 | 2.31 | 1.24 | 0.60 |
| 0 | 256 GiB | 0 | 38.5 | 2.90 | 2.20 | 1.27 | 0.58 |
| 4 GiB | 0 | 27.5 | 0 | 2.55 | 2.55 | 0.64 | 0.64 |
| 4 GiB | 64 GiB | 27.5 | 7.8 | 2.43 | 2.29 | 0.72 | 0.58 |
| 4 GiB | 256 GiB | 27.5 | 11.1 | 2.38 | 2.18 | 0.76 | 0.56 |
| 16 GiB | 0 | 34.3 | 0 | 2.32 | 2.32 | 0.59 | 0.59 |
| 16 GiB | 64 GiB | 34.3 | 1.0 | 2.30 | 2.29 | 0.60 | 0.58 |
| 16 GiB | 256 GiB | 34.3 | 4.6 | 2.25 | 2.17 | 0.63 | 0.55 |

Reading it for our cards:

- **RNGD** (~32 GB free after weights, part of it needed for active KV): a 4–16 GiB prefix cache in HBM cuts mean prefill
  27–34 %; a DRAM tier behind it cuts another 1–15 % (more behind 4 GiB than behind 16 GiB, more with a fast reload path).
  Worth having, second in line.
- **ATOM** (no HBM room): only a host tier gives any reuse — 35 % of tokens. The HBM-0 rows (RNGD rates) show 16–34 % less
  prefill time depending on the reload path; ATOM's slower prefill makes the same reload relatively cheaper. ATOM prefill is not on the serving path today (`optimal` never picks it), so this matters once ATOM
  prefill or long-context ATOM decode does.
- **Mooncake conversation** needs hundreds of GiB to a TiB: a shared, cluster-wide store, not a per-engine tier.
- Not modelled: per-instance caches behind a cache-blind router (lower hits; the EPP prefix scorer of W4 addresses it),
  attention cost of the cached prefix during the suffix prefill, and the compiled-graph constraint (reuse granularity is the
  compiled prefill chunk on RNGD/ATOM, not 512 tokens).

## The systems

| | LMCache | Mooncake Store + Transfer Engine | llm-d KV cache (indexer + tiered prefix cache) | Dynamo KVBM | vLLM OffloadingConnector |
|---|---|---|---|---|---|
| What it is | KV cache layer for vLLM (and SGLang): CPU/disk/remote tiers, P2P and PD via NIXL, CacheBlend for non-prefix reuse | Distributed KV object store (DRAM + SSD, replicas) over a multi-transport transfer engine | Routing-side index of which pod holds which block on which tier, plus recipes that offload through vLLM (native or LMCache) | NVIDIA's block manager: G1 GPU, G2 host, G3 SSD, G4 remote | vLLM's built-in GPU → pinned host (→ fs/obj/p2p) prefix-cache extension |
| Engine interface | `LMCacheConnectorV1` / `LMCacheMPConnector` (vLLM `KVConnectorBase_V1`) | Python/C++ client: put/get/remove of keyed objects, registered buffers; vLLM `MooncakeConnector`/`MooncakeStoreConnector`, SGLang HiCache, LMCache backend, NIXL plugin | Engine publishes `BlockStored`/`BlockRemoved` events (msgpack over ZMQ, topic `kv@<pod>@<model>`, field `medium` for the tier); indexer hashes tokens itself (FNV-64a over canonical CBOR `[parent, tokens, extra]`, seeded like vLLM's `PYTHONHASHSEED`, default block 16) | vLLM / TensorRT-LLM / SGLang connectors (scheduler leader + worker) | `--kv-transfer-config '{"kv_connector":"OffloadingConnector", ...}'`, `cpu_bytes_to_use`, block size a multiple of the GPU block |
| Device dependence | CUDA reference kernels; device backends for ROCm, XPU, MUSA, an NPU stack, Neuron (engine-driven only), HPU; adding one = `DeviceSpec` + `DeviceOps` (torch ops fallback) | None for host memory (TCP/RDMA); device transports for CUDA, HIP, Ascend, MUSA and others | None in the indexer; offload recipes are vLLM-on-GPU | CUDA copies; NIXL for disk/remote | CUDA, ROCm, XPU only |
| Default chunk | 256 tokens | engine-defined keys | 16 tokens (configurable) | page size | GPU block size |
| License | Apache-2.0 | Apache-2.0 | Apache-2.0 | Apache-2.0 | Apache-2.0 |

### Fit with our engines

| Engine | Device-memory prefix cache | Host tier available | KV events for llm-d | Path |
|---|---|---|---|---|
| furiosa-llm (RNGD) | Yes, on by default since SDK 2026.1 (token-level radix tree, LRU on leaves) | **Yes, experimental in 2026.4**: L2 host memory (`--experimental-kv-offload-host-memory-gb`), write-through/write-back, layer-wise reload; L3 Mooncake Store optional (dlopen) | Not documented | Upgrade from 2026.3 to 2026.4 and enable L2; measure with rm-bench tool-agent replay |
| vllm-rbln (ATOM) | Yes (`prefix_block_size`, a multiple of the compiled prefill chunk) | On master (2026-10-19): `RBLNLMCacheConnectorV1` (re-exports `lmcache_rbln`, from Rebellions' nightly index — not a public release we could verify) and an RBLN NIXL connector with host-bounce (DRAM) and device-to-device paths | vLLM's event publisher, if the plugin keeps it | Track the vllm-rbln release that ships it; our deployed 0.11.0 predates it |
| Optimus Prime (aicomp) | No (aicomp #46) | No (aicomp #52) | No (#46) | Engine-local tier per the requirements below |

Hosting LMCache or KVBM inside Optimus Prime would mean implementing vLLM's scheduler/worker connector contract
(`get_num_new_matched_tokens`, `update_state_after_alloc`, `build_connector_meta`, `start_load_kv`, `wait_for_layer_load`,
`save_kv_layer`, `wait_for_save`, `request_finished`), a paged block table, and an LMCache `DeviceSpec`/`DeviceOps` for each
NPU — more code than the tier itself, and tied to vLLM's internals, which change every release. Mooncake Store is the one
component worth keeping open: its client is engine-neutral, it stores host-memory segments over TCP without device
support, and furiosa-llm already uses it as L3, so a shared tier later can be common to RNGD and our engine.

## Interface requirements for aicomp #52 (and #46)

What the ai-rm side needs from the engine's tier; everything else is the engine owner's design.

1. **Content-addressed blocks** (#46): fixed block size in tokens, a multiple of the compiled prefill chunk; chained
   hash per block over (parent hash, token ids, extra keys such as LoRA). Either compute it as llm-d does (FNV-64a over
   canonical CBOR `[parent, tokens, extra]`, seed shared by all pods) or publish engine hashes with tokens so the indexer can
   map them.
2. **Events** (#46): `BlockStored` (hashes, parent, token ids, block size, `medium`) and `BlockRemoved` (hashes, `medium`) in
   vLLM's msgpack layout on ZMQ topic `kv@<pod>@<model>`. Use `medium` per tier (device tier name for HBM, `cpu` for host)
   so the EPP's precise prefix-cache scorer weights them (defaults gpu 1.0, cpu 0.8). A host copy publishes a second
   `BlockStored` with `medium=cpu` and no tokens, after the device one.
3. **Tier operations**: offload device → host (write-through on store, or write-back on eviction), reload host → device
   before prefilling the uncached suffix, LRU eviction on leaves, a host budget flag (`--kv-host-memory-gb`). Reuse the
   device-resident part of a match, reload only the rest (furiosa-llm's model).
4. **Reload or recompute**: reload only when `bytes / reload_bandwidth < tokens / prefill_rate`; the break-even bandwidth is
   prefill tok/s × KV bytes per token (0.33 GB/s for Llama-8B on RNGD at 2,500 tok/s). Report reload time per block
   (#52 acceptance).
5. **Host memory**: page-aligned, pinned host buffers allocated once and registrable as NIXL `DRAM_SEG` / Mooncake segments,
   so a later shared tier or NIXL transfer (#48) moves them without another copy. Describe them with rm-core `MemoryTier`
   (`host-dram`, capacity) and the block layout with `KVLayout`.
6. **Prefill from a cached prefix**: a graph or kernel path that starts prefill at a token offset with past KV present
   (chunked prefill); without it, hits cannot skip compute. Granularity = compiled chunk.
7. **Metrics** (#45): prefix hit tokens by tier, reload bytes and latency, offload queue depth, host tier occupancy.
8. **Optional**: layer-wise reload overlapping compute (shares the mechanism of #47 layer-wise transfer).

## Not verified

- No run on our hardware: all hit rates are trace replays through an LRU model; all prefill times are profile arithmetic.
  The furiosa-llm 2026.4 host tier and vllm-rbln's LMCache connector were read from docs and source, not run.
- `lmcache_rbln` is referenced by vllm-rbln master but published only on Rebellions' internal nightly index; whether and
  when it ships publicly is unknown.
- Mooncake Store's put/get performance from host memory over TCP on our nodes is unmeasured.

## Sources

- LMCache docs: https://docs.lmcache.ai/ · storage backends: https://docs.lmcache.ai/mp/l2_storage/supported_storages.html ·
  new device backend: https://docs.lmcache.ai/developer_guide/extending_lmcache/adding_a_new_device_backend.html ·
  MP mode and chunk size: https://docs.lmcache.ai/mp/configuration.html · CacheBlend:
  https://docs.lmcache.ai/kv_cache_optimizations/cacheblend.html · paper: https://arxiv.org/abs/2510.09665
- vLLM KV connector base: https://github.com/vllm-project/vllm/blob/main/vllm/distributed/kv_transfer/kv_connector/v1/base.py ·
  disaggregated prefill and connectors: https://docs.vllm.ai/en/latest/features/disagg_prefill.html · KV offloading:
  https://docs.vllm.ai/en/latest/features/kv_offloading_usage/
- Mooncake: https://github.com/kvcache-ai/Mooncake · Store design: https://kvcache-ai.github.io/Mooncake/design/mooncake-store.html ·
  Transfer Engine: https://kvcache-ai.github.io/Mooncake/design/transfer-engine/index.html · protocols and hardware:
  https://kvcache-ai.github.io/Mooncake/getting_started/supported-protocols.html · vLLM integration:
  https://kvcache-ai.github.io/Mooncake/deployment/integrations/vllm/index.html · paper (FAST'25):
  https://www.usenix.org/conference/fast25/presentation/qin
- llm-d KV cache: https://github.com/llm-d/llm-d-kv-cache (`docs/architecture.md`, `pkg/kvcache/kvblock/token_processor.go`,
  `pkg/kvevents/engineadapter/vllm_adapter.go`; FS backend upstreamed into vLLM: `kv_connectors/llmd_fs_backend/README.md`) ·
  tiered prefix cache guide: https://llm-d.ai/docs/well-lit-paths/tiered-prefix-cache
- Dynamo KVBM design: https://docs.nvidia.com/dynamo/v1.3.0/design-docs/component-design/kvbm-design.md
- NIXL: https://github.com/ai-dynamo/nixl (`src/api/cpp/backend/backend_engine.h`, memory types `DRAM_SEG`/`VRAM_SEG`/
  `BLK_SEG`/`OBJ_SEG`/`FILE_SEG` in `src/api/cpp/nixl_types.h`; plugins ucx, posix, cuda_gds, mooncake, obj, hf3fs,
  libfabric and others — none for RBLN or Furiosa)
- furiosa-llm prefix caching: https://developer.furiosa.ai/latest/en/furiosa_llm/prefix-caching.html · hierarchical prefix
  caching: https://developer.furiosa.ai/v2026.4.0/en/furiosa_llm/hierarchical-prefix-caching.html · release 2026.4.0:
  https://developer.furiosa.ai/v2026.4.0/en/whatsnew/release-2026.4.0.html
- vllm-rbln prefix caching: https://docs.rbln.ai/latest/software/model_serving/vllm_support/features/prefix-caching.html ·
  source: https://github.com/RBLN-SW/vllm-rbln (`vllm_rbln/distributed/kv_transfer/kv_connector/v1/rbln_lmcache_connector.py`,
  `.../rbln_nixl/registration.py`)
