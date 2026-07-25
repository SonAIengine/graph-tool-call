# Documentation Site Redesign

## Purpose

The public documentation site should feel like an official developer docs portal,
not a one-off marketing page. The home page must help a developer answer four
questions quickly:

1. What is graph-tool-call?
2. Where do I start?
3. How do I validate quality claims?
4. Which reference page do I need next?

## Benchmarked Patterns

- Docusaurus: keep the official docs framework because it provides docs routing,
  i18n, version-friendly structure, static publishing, and a broad showcase of
  production documentation sites.
  <https://docusaurus.io/docs>
  <https://docusaurus.io/showcase>
- Stripe Docs: prioritize "start here" routes, quickstarts, reference entry
  points, and product/capability browsing before long narrative copy.
  <https://docs.stripe.com/>
- Mintlify-style docs: treat AI-era documentation as search- and LLM-friendly by
  exposing compact entry points such as `llms.txt`, API reference, and task-based
  guides.
  <https://www.mintlify.com/docs>
- Astro Starlight: use as a comparison point for clean docs IA, but keep
  Docusaurus for this repository because the existing site already needs React,
  i18n, GitHub Pages, and future versioning.
  <https://starlight.astro.build/>

## Design Decisions

- Use a docs-portal home, not a full marketing hero.
- Make "Quickstart", "OpenAPI Collections", "XGEN Integration", and
  "Benchmarks" visible in the first scroll.
- Keep the code sample compact and realistic.
- Add a validation section so benchmark and quality gate pages are first-class,
  not buried in the sidebar.
- Avoid decorative visuals that do not explain the engine.
- Keep cards for repeated navigation items only.
- Use a neutral technical palette with limited blue accent.
- Keep the design usable in Korean and English without text overflow.

## Follow-up Criteria

- Add search when the content grows beyond the current small docs set.
- Add release-versioned docs before the first widely announced stable release.
- Promote benchmark result pages only when they are reproducible from committed
  fixtures or published artifacts.
- Add API examples only when they are verified against public package imports.
