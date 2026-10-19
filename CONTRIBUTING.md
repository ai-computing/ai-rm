# Contributing to AI-RM

[English](README.md) · [한국어](README.ko.md) · [Documentation](docs/README.md)

Use a focused branch and PR. The umbrella owns architecture, component pointers, integration tools, the in-tree packages under `packages/` (rm-bench, rm-controller) and public documentation; other implementation changes belong in the appropriate component repository.

The [Optimus Prime direction](docs/engine-integration.md) consolidates inference-engine technology into `aicomp/opt_prime` with `fasop` as a planner element. Keep new engine work aligned with that owner; existing source cards remain transition requirements. `config/engine-integration.yaml` is planning metadata, not a runtime activation mechanism. Do not change live setup to a proposed branch before it exists and is validated.

## Integration changes

Read the [component card](docs/components/README.md), [integration guide](docs/integration-guide.md) and [rm-core protocol](https://github.com/ai-computing/rm-core/blob/main/PROTOCOL.md). Document the exact adapter names, measurements and conformance results. Preserve component logic unless the implementation task explicitly requires a change. Distinguish hardware SKIP from PASS.

For a pointer update, identify old/new component revisions and the validation actually performed for that combination. Do not move unrelated submodules.

## Documentation and translation

- English is the default in `README.md` and the top-level documentation. Korean is in `README.ko.md` and `docs/ko/`.
- Update both languages when changing setup commands, access rules, architecture or status. Preserve reciprocal language links.
- Detailed component work cards currently remain in Korean; label their language in navigation.
- Use repository-relative links for local pages and descriptive alt text for images.
- Keep the root README focused on purpose, quick start, one overview and navigation. Put detailed diagrams, migration mechanics and environment imagery in the topic guides.
- Separate intended architecture, implemented behavior and tested results. Keep unreleased KPI numbers and private evidence out of public docs.

## Visual assets

Original SVG sources are regenerated with:

```bash
python3 tools/render_docs_assets.py
```

Keep diagrams readable at GitHub content width and on small screens. Check the README's light/dark `<picture>` variants and stacked mobile overview. Retain the captions distinguishing AI-generated conceptual imagery from installation photos. [Asset provenance](docs/assets/README.md) records prompts and ownership boundaries.

## Before submitting

```bash
python3 tools/check_docs.py
# Stage the specific intended files, then run the tracked-file scan:
python3 tools/check_sensitive.py .
git diff --check
```

Review rendered diagrams and both language entry points. Do not report that a documentation check validated accelerator hardware or deployed a cluster.

## 한국어 안내

문서와 구조 변경은 영문·한국어를 함께 갱신하고, 설치·접근 권한·현재 상태가 두 언어에서 일치하도록 해주세요. 구현 변경은 해당 구성요소 저장소에서 진행합니다. 작업 카드와 rm-core 계약을 따르고 실제 검증 결과의 PASS·FAIL·SKIP을 구분해 기록합니다. 사이트 값·자격 증명·미공개 과제 증빙은 공개 문서에 넣지 않습니다.
