---
name: render-evidence-package
description: |
  Iter-1 skill that consumes an evidence_package.json (the envelope written by target-profile
  --emit evidence-package / run_wired_skill --emit-envelope)
  and produces Stage-1 static markdown at data-products/{target}/{indication}/{package_id}/renderings/dashboard.md.

  The Stage-1 renderer is intentionally minimal: executive summary, per-card panels (with figure
  reference + summary + interpretation_call + caveats), governance block (data_mode + concurrence ref),
  provenance block. HTML rendering is iter-2 (Stage 2); PowerPoint and decision-memo renderers are
  iter-3+.

  Use this skill when: an evidence_package has been emitted (or re-emitted via lockfile) and a
  human-readable rendering is required. Run standalone against an emitted evidence_package.json
  (it was formerly auto-invoked by the retired compose-dashboard).

compute_mode: cross_product_synthesis
delegates_to: []                                 # pure read-and-render; no method invocations
consumes_contracts:
  - target-contracts/schemas/evidence_package.schema.json
produces_cached_artifact: true
cache_key: [package_id]
status: operational
---

# render-evidence-package

**Status: OPERATIONAL (iter-1b).** Stage-1 markdown renderer implemented in
`scripts/render_markdown.py`. Tested against KRAS-COADREAD (positive) and
TG-COADREAD (negative-control refusal) evidence packages. Closes the iter-1b
happy path: input → run_plan → executed cards → evidence_package → **rendered markdown**.

The renderer is intentionally simple: it walks the evidence_package's top-level
sections and emits each as a markdown block. NO new synthesis, NO new interpretation,
NO new computation. Per the layer-distinction discipline (plan § Dashboard, Interpretation,
Inference Layers), the renderer adds nothing to the dashboard, interpretation, or
inference layers; it surfaces what they produced. Decoupled from the orchestrator —
consumes any conforming evidence_package, current or archived.

## Iter-1 markdown layout

```
# Evidence Package: {target.symbol} in {indication.label}

## Executive Summary
{synthesis.headline}

**Governance**: data_mode={governance.data_mode}, release_pin={governance.release_pin}
**Concurrence**: {governance.concurrence.state if present else "not recorded"}

## Card Panels
For each card in cards[]:
  - if excluded_by_applies_when: render absence stub with exclusion_reason
  - else: render summary block + figure_ref + interpretation_call + caveats + warning_ids

## Caveats Summary
{synthesis.caveats_summary}

## Provenance
- framework_version
- generated_at, generated_by
- dashboard_spec_ref
- per-card method_calls + input_manifest_ids + canonical_decision_refs
```

## Iter-2+ scope (out of iter-1)

- HTML rendering (Stage 2)
- PowerPoint rendering (Stage 3+)
- Decision-memo composition (Stage 3+)
- Interactive UI (Stage 4)

## Dependencies

- ✅ target-contracts/schemas/evidence_package.schema.json
- Reads evidence_package.json + per-card summary.json + figure.svg from data-products/

Stage 1 is **markdown-only** by deliberate design (plan A3 § Stage 1 → Stage 4 maturity ladder).
Substrate-first; UI later. A pretty Stage 4 over an unfixed Stage 1 produces high-velocity wrong answers.
