---
name: example-gallery
description: |
  Developer/demo tool: generate a SIMPLE static-HTML gallery of full example outputs
  (verdict + per-card summaries + tables + figures) from the focused subskills, for
  showing collaborators + comp-bio colleagues what the framework produces.

  NOT a composed skill / not wired into target-profile — a standalone generator.

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  environment:
    - AWS_PROFILE=cbg
status: operational    # top-level, no composition block: developer/demo generator, not a compositional skill. Clears framework_health missing_status_field without making it a validated compositional skill.
---

# example-gallery

## What it does

Runs a configured list of `(subskill, target, indication)` rows and renders, per run, ONE
self-contained static HTML page — the deterministic verdict, each card's summary fields, its
`tables/*.csv`, and its FIGURES — plus an `index.html` linking them all.

It deliberately AVOIDS `compose-dashboard` (the heavy compose→execute→synthesize orchestrator with
a dashboard_spec + data_mode + schema-validation gates + evidence_package envelope). Instead it
reuses the two pieces that actually matter:
- runs each subskill's own `scripts/run.py` (→ `decision.json` + `summary.yaml` + `tables/`), and
- calls `_skills_common._figure_emitters.emit_figures_for_card` — the STANDALONE figure
  seam that needs only a card's summary dict — to produce the SVGs the subskill run doesn't emit.

## How to run

```
export AWS_PROFILE=cbg
python skills/example-gallery/scripts/generate_example_gallery.py \
    --config skills/example-gallery/examples.yaml --synthesize
# then open ~/dev/example-gallery/index.html
```

- **`--out` defaults to `~/dev/example-gallery`** — a SINGLE canonical dir that each run
  OVERWRITES in place (no proliferating gallery folders). Pass `--out DIR` only for a throwaway variant.
- **`--synthesize`:** adds the LLM relevance narrative to each page (needs Bedrock; a subskill that
  doesn't accept it is retried without it — best-effort).
- **Static (default):** SVGs inlined; pages self-contained, open anywhere incl. the VS Code Simple
  Browser, email-friendly. **`--interactive`:** plotly twins + inlined plotly.js (~4.6MB/page, real
  browser only) — for a live demo.
- **One-off (no config):** `--skill tumor-presence --target CEACAM5 --indication COADREAD`.

## Iterating

Add a row to `examples.yaml` and re-run — no code change. `indication` is omitted for target-grain
subskills (e.g. `target-intrinsic`).

## Honest gaps

Only ~34 cards have figure emitters (`CARD_FIGURE_EMITTERS`). Cards without one (e.g.
`signaling-network-mechanism`, co-mutation cards) render summary + tables but no chart — expected,
not a bug. `data_unavailable` / missing cards are rendered as such, never dropped.

## L4 target-story pages (epic #1986, C2 #1997)

`generate_story_pages.py` renders the two flagship **L4 target-synthesis** pages — the terminal,
decision-facing view over `_skills_common.l4_synthesis.assemble_target_synthesis` (thesis +
archetype, opportunity drivers, liabilities vs contradictions [kept DISTINCT], critical unknowns,
and whichever further facets have landed — the renderer, `l4_story_page.py`, is FACET-AGNOSTIC: it
iterates whatever `FACET_BUILDERS` actually returned, so a later facet landing (#2008 modality,
#2009 next-evidence, …) enriches the page with no code change here).

```
export AWS_PROFILE=cbg
python skills/example-gallery/scripts/generate_story_pages.py --out ~/dev/example-gallery/stories
# then open ~/dev/example-gallery/stories/EPCAM__COADREAD_story.html
#                                        /KRAS__COADREAD_story.html
```

It is a PURE READ-OVER: it runs tumor-presence's own `run.py --emit-envelope --figures` live (one
target at a time — SERIAL, RSS discipline on a shared host) and feeds the resulting `decision.json`
straight into `assemble_target_synthesis`; it never wires L4 into envelope emission (that is C1
#1996, deferred post-cutover) and never fabricates content the assembler didn't resolve.

**EPCAM/COADREAD** is the rich flagship: tumor-presence's committed L3d story resolves a
corroborated `archetype=undetermined` (a definitive archetype needs dependency/surface-modality/
safety too — all still NOT_ASSESSED) with populated drivers, a liability + a contradiction, and
figure jump-links off the claim-ref chips.

**KRAS/COADREAD** is DELIBERATELY sparse — only tumor_presence resolves (6 of 7
`KNOWN_DOMAINS` are `NOT_ASSESSED`) — and that honest gap IS the demo story: "here is what we
know, what we don't, and what to measure next." Never fabricate to make it look fuller.

`--target X --indication Y` renders a one-off pair instead of the two flagships;
`--skip-run` reuses an already-fetched `decision.json` under `--out/_runs/<slug>/` for fast
renderer-only iteration.
