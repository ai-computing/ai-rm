# Visual assets and provenance

[Documentation](../README.md) · [한국어 문서](../ko/README.md)

All artwork is stored in this repository; diagrams do not depend on a remote renderer. The SVGs use a fixed dark background for readable display in GitHub light and dark themes. Each diagram has a title, description and matching Markdown alt text. Their English labels are shared by both documentation languages; the surrounding Korean prose explains the same concepts.

| Asset | Type / source | Purpose |
|---|---|---|
| `hero.svg` | Original SVG, generated from repository code | Project identity and hardware scope |
| `architecture.svg` | Original SVG | L1–L5 responsibilities and rm-core boundary |
| `request-flow.svg` | Original SVG | Conceptual PD request and named KV path |
| `memory-paths.svg` | Original SVG | Distinguish KV, expert offload and unified-memory search |
| `research-workflow.svg` | Original SVG | Discover → connect → execute → measure |
| `engine-consolidation.svg` | Original SVG | AI-RM hub / Optimus Prime runtime / FASOP planner / migration-source boundary |
| `icon-*.svg` (six files) | Original SVG | Device, memory, serving, cluster, observation and contract icons |
| `lab-environment.png` | Built-in ImageGen, generated for this documentation | Conceptual lab environment |
| `hardware-workbench.png` | Built-in ImageGen, generated for this documentation | Generic hardware research context |

Regenerate the 12 SVG assets with `python3 tools/render_docs_assets.py` from the repository root. The generator is Python standard-library only. SVG artwork is original project material distributed under the repository license. Third-party badges retain their providers' terms; vendor/product names identify the research context without implying endorsement.

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

SVG 12개는 저장소의 생성 스크립트에서 재현하는 자체 제작 도식·아이콘입니다. PNG 2개는 내장 ImageGen으로 만든 실사풍 개념 이미지이며 실제 과제 장비 사진·제품 식별 자료·성능 증빙이 아닙니다. 실제 구축 사진이 제공되면 개인정보·주소·화면 내 비밀정보를 확인하고 명확한 출처와 함께 별도 등록하세요. 생성 이미지의 설명 문구는 유지합니다.
