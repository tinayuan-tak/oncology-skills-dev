---
name: combo-and-resistance
description: |
  Phase-I skill: "When target X is inhibited, what COMBINATION opportunities emerge —
  which co-targets become more essential under inhibition?" Consumes the combo-crispr-screen
  card (DepMap 26Q1 drug-anchor CRISPR screens) + the combination-opportunity rule subset.
  Emits a data-package with a self-contained combination_verdict.

  GRADUATED 2026-08-07 placeholder → PARTIAL. The COMBINATION half is wired (combo-crispr-screen
  → depmap-drug-anchor-combination-per-target-v1 via methods/combo_drug_anchor). The RESISTANCE
  half (resistance-emergence-signature — genes whose loss RESCUES under inhibition, candidate
  resistance mediators) is DEFERRED: the positive-shift arm of the same screens is not yet
  distilled into a product. The skill reports it as an explicit remaining gap.

  Use for questions like "what combines with KRAS inhibition?" (→ PTPN11/SHP2, GRB2 — validated),
  "co-targets for XPO1 inhibition?". Biology-first; modality is a post-hoc co-targeting lens.

metadata:
  version: 2.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [I]
  cards_used:
    - combo-crispr-screen
  # DEFERRED (status: partial) — the resistance half, not yet a wired card/product:
  #   - resistance-emergence-signature  (positive-shift / rescued-gene arm of the drug-anchor screens)
  measurement_types_pulled:
    - drug_anchored_combination
  rules_scope:
    - combo-crispr-screen
  # SELF-CONTAINED verdict (run.py _verdict) on the dedicated combination_opportunity axis — NOT
  # wired into nomination_verdict_gate (a combination opportunity is a co-targeting rationale, not a
  # monotherapy nomination; it must not move the single-target verdict). Existing resolver goldens
  # byte-stable.
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: partial
---

# combo-and-resistance — Combination Opportunities (partial)

## What this skill does (combination half — wired)

Given a target: loads the combo-crispr-screen card, which reads DepMap 26Q1 drug-anchor CRISPR
screens (a genome-wide KO screen run WITH vs WITHOUT the target's anchor inhibitor) and reports,
per co-target gene, the essentiality SHIFT under inhibition. Fires the combination-opportunity
rules and resolves a self-contained `combination_verdict`:

- `strong_combination_opportunity` — a robust co-target (deep shift, significant across models)
- `combination_opportunity` — a supported co-target
- `context_combination_opportunity` — a single-model (conditional) co-target
- `no_combination_signal` — anchor screened, nothing passed (measured negative)
- `combination_insufficient` — `no_anchor_screen` (coverage gap) or read failure

Validation: KRAS inhibition (MRTX1133 anchor) → top co-target **PTPN11 (SHP2)**, robust, significant
in 5/6 KRAS-G12D models — the flagship clinically-validated KRAS combination; GRB2 next.

## Coverage + the deferred resistance half (status: partial)

COMBINATION coverage is NARROW: DepMap drug-anchor screens cover only single-target anchor
inhibitors (KRAS via MRTX1133, KIT via Avapritinib, XPO1 via Eltanexor). Any other target →
`no_anchor_screen` (a coverage gap, never "no combination exists" — measured-vs-null).

The RESISTANCE half — `resistance-emergence-signature` (genes whose loss RESCUES under inhibition,
the positive-shift arm) — is NOT yet wired. The same drug-anchor screens carry it; distilling that
arm into a product + card is the remaining work. `decision.json` surfaces `resistance_half_status`.

## Boundaries

A significant co-target is a co-targeting HYPOTHESIS to verify (KRAS/PTPN11 is validated; not every
hit will be). Cell-line drug-anchor genetic interaction ≠ in-vivo combination benefit. The card
carries n_models + n_significant so a single-model hit can't over-claim.

## How Claude invokes this skill

`/combo-and-resistance --target KRAS [--indication ...]`. Reads `decision.json`: `combination_verdict`
+ `driving_rule_id` are the audit spine; `top_co_targets` is the ranked combination-hypothesis list;
`resistance_half_status` flags the deferred arm.
