---
name: combo-and-resistance
description: |
  [RETIRED FROM THE target-profile FAN-OUT 2026-08-20] Consolidated into combination-and-vulnerability for composition (its cards compose there under the combination_vulnerability dimension + relational claim_vector). Still runnable standalone; do NOT re-add to SUB_SKILLS.
  Phase-I skill: "When target X is inhibited, what COMBINATION opportunities emerge —
  which co-targets become more essential under inhibition?" Consumes the combo-crispr-screen
  card (DepMap 26Q1 drug-anchor CRISPR screens) + the combination-opportunity rule subset.
  Emits a data-package with a self-contained combination_verdict.

  GRADUATED 2026-08-07 placeholder → PARTIAL (combination half). UPGRADED 2026-08-10 PARTIAL → WIRED:
  the RESISTANCE half is now live. COMBINATION half: combo-crispr-screen →
  depmap-drug-anchor-combination-per-target-v1 via methods/combo_drug_anchor ("which co-targets
  become MORE essential under inhibition"). RESISTANCE half: resistance-emergence-signature →
  depmap-drug-anchor-resistance-per-target-v1 (the SIGN-MIRROR positive arm of the SAME screens) via
  methods/resistance_emergence ("which gene knockouts RESCUE the cell = candidate resistance
  mediators"). Two self-contained verdicts (combination_verdict + resistance_verdict).

  Use for questions like "what combines with KRAS inhibition?" (→ PTPN11/SHP2, GRB2 — validated),
  "what resistance mediators for KRAS inhibition?" (→ NF1, KEAP1/NRF2, NF2 — validated),
  "co-targets for XPO1 inhibition?". Biology-first; modality is a post-hoc co-targeting lens.

metadata:
  version: 3.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [I]
  cards_used:
    - combo-crispr-screen
    - resistance-emergence-signature
  measurement_types_pulled:
    - drug_anchored_combination
    - drug_anchored_resistance
  rules_scope:
    - combo-crispr-screen
    - resistance-emergence-signature
  # TWO SELF-CONTAINED verdicts (run.py _verdict + _resistance_verdict) on dedicated axes
  # (combination_opportunity + resistance_emergence) — NEITHER wired into nomination_verdict_gate
  # (a combination opportunity is a co-targeting rationale; a resistance mediator is a monitoring
  # rationale; neither is a monotherapy nomination). The dispatcher fires the combination axis; the
  # resistance axis is fired in-skill so the combination spine is byte-identical. Existing resolver
  # goldens byte-stable.
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
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
