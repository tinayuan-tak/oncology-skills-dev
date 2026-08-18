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
- calls `compose-dashboard/scripts/_figure_emitters.emit_figures_for_card` — the STANDALONE figure
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
