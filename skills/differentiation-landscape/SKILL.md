---
name: differentiation-landscape
description: |
  Phase-E skill — co-mutation + mutual-exclusivity landscape for a target,
  panel-intersect-aware Fisher's-exact scan across TCGA MC3 + GENIE 19.0.

  GRADUATED 2026-07-08: placeholder → partial. Co-mutation card wired via
  cooccurrence_fisher_pancohort method + pancohort-cooccurrence-fisher-v1
  derived manifest. Remaining cards (clinical-precedent, patent-landscape)
  stay placeholder; their commercial-data-licensing dependencies are not
  resolved. Paralog-buffering was RE-HOMED to functional-requirement skill
  (Phase C-adjacent) per reviewer content flag — buffering is a
  dependency-hardening signal, not a differentiation signal.

  Question this skill answers:
  What genes co-occur with or are mutually exclusive to {target} mutations
  across TCGA MC3 + GENIE 19.0-public, and what patient-selection or
  combination-biology hypotheses does the pattern support?

  Reviewer-driven BLOCKER FIX (2026-07-08): pooled Fisher analysis is
  restricted to the panel-intersect gene set. Genes absent from GENIE
  panels get per-source q-values only (`pooled_eligible: false`),
  preventing the naive-pooling failure mode that would produce
  artifactual mutual-exclusivity signals for panel-absent genes.

metadata:
  version: 1.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [E]
  cards_used:
    - co-mutation-and-mutual-exclusivity   # Wired 2026-07-08 (Layer 6f)
    - clinical-precedent                   # Placeholder (Cortellis licensing)
    - patent-landscape                     # Placeholder (PatBase licensing)
  rules_scope:
    - co-mutation-and-mutual-exclusivity
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: partial
  on_dependency_status:
    clinical-precedent: skip_section       # arch A4 discipline
    patent-landscape: skip_section
---

# differentiation-landscape — Phase E partial skill

## What this skill does (iter-1 partial wiring)

Given a target + indication:
  1. Loads the co-mutation-and-mutual-exclusivity card summary from
     pancohort-cooccurrence-fisher-v1 (panel-intersect-aware Fisher scan).
  2. Rules engine consumes cooccurrence_class categorical +
     has_cooccurring_driver + strong_mutually_exclusive fields.
  3. Emits data_package output tree with top_cooccurring + top_mutually_
     exclusive tables + per-source q-value provenance.

## What this skill does NOT do (yet)

- **Clinical-precedent feed:** Cortellis / IQVIA licensing pending. Skill
  will SKIP that section per on_dependency_status: skip_section (arch A4).
- **Patent landscape:** PatBase licensing pending. Similarly skipped.
- **Paralog buffering** (re-homed): functional-requirement skill consumes
  this — paralog buffering is a Phase C-adjacent dependency-hardening
  signal, not a Phase E differentiation signal (reviewer content flag).

## Output tree (data_package shape)

```
<out>/
├── decision.json                 # rule verdicts + fired rules
├── summary.yaml                  # co-mutation card summary_fields
├── figures/
│   └── cooccurrence_forest.png
├── tables/
│   ├── top_cooccurring.csv       # per-partner Fisher q-values
│   └── top_mutually_exclusive.csv
└── provenance.yaml               # MC3 + GENIE manifests, panel-intersect stats
```

## Invocation

```
/differentiation-landscape KRAS in COADREAD
```

## Reviewer BLOCKER FIX discipline (governance-critical)

Every emitted decision.json carries `panel_intersect_mode: strict` in
provenance + `pooled_eligible: bool` per top_cooccurring / top_mutually_
exclusive row. Governance readers can filter to pooled_eligible=True for
maximum-cohort claims; per-source (TCGA MC3 only OR GENIE only) claims
are always available for panel-ineligible genes.

## Iter-2 roadmap

1. Cortellis / IQVIA licensing → clinical-precedent card wiring.
2. PatBase or equivalent → patent-landscape card wiring.
3. Method upgrade: DISCOVER (Canisius 2016) or SELECT (Mina 2020)
   alongside Fisher — cited in the card's caveats as principled successors.
