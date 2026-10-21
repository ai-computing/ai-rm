# Visual assets and provenance

[Documentation](../README.md) · [한국어 문서](../ko/README.md)

All artwork is stored in this repository; diagrams do not depend on a remote renderer. The README wordmark and overview have light/dark variants selected through `<picture>`. Detailed diagrams retain their fixed dark canvas. Each diagram has a title, description and matching Markdown alt text. Their English labels are shared by both documentation languages; the surrounding Korean prose explains the same concepts.

| Asset | Type / source | Purpose |
|---|---|---|
| `wordmark-light.svg`, `wordmark-dark.svg` | Original SVG | Compact, theme-aware README identity |
| `overview-light.svg`, `overview-dark.svg` | Original SVG | Concise hub / runtime / planner overview |
| `overview-mobile-light.svg`, `overview-mobile-dark.svg` | Original SVG | Stacked overview with readable labels on small screens |
| `ai-rm-overview.webp` | Original animation, rendered with Remotion; 960×540, 12 fps, 73 s loop | README opening: what each layer does and which limit it removes |
| `hero.svg` | Original SVG, generated from repository code | Project identity and hardware scope |
| `architecture.svg` | Original SVG | L1–L5 responsibilities and rm-core boundary |
| `request-flow.svg` | Original SVG | Conceptual PD request and named KV path |
| `memory-paths.svg` | Original SVG | Distinguish KV, expert offload and unified-memory search |
| `research-workflow.svg` | Original SVG | Discover → connect → execute → measure |
| `engine-consolidation.svg` | Original SVG | AI-RM hub / Optimus Prime runtime / FASOP planner / migration-source boundary |
| `icon-*.svg` (six files) | Original SVG | Device, memory, serving, cluster, observation and contract icons |
| `lab-environment.png` | Built-in ImageGen, generated for this documentation | Conceptual lab environment |
| `hardware-workbench.png` | Built-in ImageGen, generated for this documentation | Generic hardware research context |

Regenerate the 18 SVG assets with `python3 tools/render_docs_assets.py` from the repository root. The generator is Python standard-library only. SVG artwork is original project material distributed under the repository license. Third-party badges retain their providers' terms; vendor/product names identify the research context without implying endorsement.

## README layout references

The layout refinement reviewed [vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), [Ray](https://github.com/ray-project/ray) and [llm-d](https://github.com/llm-d/llm-d) on 2026-10-19. The adopted patterns are a compact identity, a short purpose statement, early quick start, role-based navigation and links to detailed documentation. Artwork and project copy remain original; no third-party logos, screenshots or performance claims are reused.

## Overview animation

`ai-rm-overview.webp` is an original motion graphic made with [Remotion](https://www.remotion.dev) on 2026-10-21 and converted to animated WebP (960×540, 12 fps, silent loop) because GitHub README pages do not autoplay video. It is an explanatory illustration, not a recording of a live system. Every figure on screen comes from a public component README: npu-offload (2.3 → 34.9 tok/s), hetero-npu-p2p (≈3 ms median DMA per request; RNGD solo 66.3 → PD 98.3 tok/s at output 128), onggi (99.3 % shared bytes between ATOM variants) and npu-train (NSMC 84.6 % vs 84.2 %, 4.32 vs 3.08 tok/J). The lmd-top screen in it shows illustrative pod names and values. Optimus Prime is labeled as integration in progress.

## Image provenance

The two raster images were generated with the built-in ImageGen tool on 2026-10-19. They are **conceptual illustrations, not actual installation photos, product reference photos or benchmark evidence**. No real deployment photographs were supplied. Keep the captions when reusing these images. No third-party stock photos or copied vendor product photographs are included.

### Lab environment prompt

```text
Use case: photorealistic-natural. Asset type: wide editorial hero for the AI-RM open-source research integration repository. Primary request: a sophisticated realistic AI computing research laboratory, heterogeneous compute infrastructure. Scene: clean university or industrial computing lab with two modest server racks, accelerator servers with front ventilation grilles, copper and optical cabling, and a small compact desktop compute appliance in the foreground. Composition: cinematic panoramic landscape, server racks across center-right, quiet dark navy negative space at upper left. Style: restrained premium technology editorial photography, realistic materials and scale, soft cool blue light with restrained teal status LEDs. No people, no brands, no logos, no readable labels, no UI or charts, no imaginary holograms, no text or watermark. This is conceptual lab imagery, not a photograph of an actual deployment.
```

### Hardware workbench prompt

```text
Use case: product-mockup. Asset type: landscape supporting image for AI-RM heterogeneous hardware documentation. Primary request: realistic hardware workbench in an AI accelerator laboratory. Scene: two unbranded PCIe accelerator boards in antistatic holders, a CPU server motherboard with realistic heatsinks and memory DIMMs, and a small silver compact compute desktop. Show physically plausible hardware as illustrative generic examples, not identifiable actual products. Composition: landscape, tidy equipment arrangement, three-quarter camera view, all devices in frame with breathing room. Style: high quality technical editorial still-life photography, natural silver metal, dark graphite, soft blue and teal lab illumination. No text, labels, brand marks, charts, human hands, watermark, futuristic floating objects.
```

## 한국어 안내

`ai-rm-overview.webp`는 Remotion으로 만든 자체 제작 개요 애니메이션입니다(GitHub README는 동영상을 자동 재생하지 않아 animated WebP로 변환). 화면의 수치는 모두 공개된 구성요소 README에서 가져왔고, lmd-top 화면의 pod 이름과 값은 예시입니다. SVG 18개는 저장소의 생성 스크립트에서 재현하는 자체 제작 도식·아이콘입니다. README용 워드마크·개요 그림에는 밝은/어두운 테마를 제공하고, 작은 화면에서는 세로형 개요 그림을 표시합니다. PNG 2개는 내장 ImageGen으로 만든 실사풍 개념 이미지이며 실제 과제 장비 사진·제품 식별 자료·성능 증빙이 아닙니다. 이미지 설명은 유지하고 실제 구축 사진은 출처와 공개 가능한 내용을 확인해 별도 등록합니다.
