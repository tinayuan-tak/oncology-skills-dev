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
  version: 1.2.0
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [E]
  cards_used:
    - co-mutation-and-mutual-exclusivity   # Wired 2026-07-08 (Layer 6f)
    - expression-clinical-association       # Q11 (2026-07-23): expression→survival prognostic context (render facet)
    - precog-prognostic-association         # PRECOG (2026-08-10): pan-cancer META-ANALYTIC expression→survival meta-Z (Gentles 2015 + 2026 NAR); the better-powered CORROBORATION of expression-clinical-association; verdict-inert render facet
    - stemness-context                    # Malta 2018 (2026-08-10): tumor-stemness (mRNAsi) cohort prior; verdict-inert prognostic/aggressiveness context
    # clinical-precedent + patent-landscape intentionally NOT listed — they are
    # excluded from the runtime card set (commercial-data licensing unresolved) and
    # never reach run.py CARDS; see NOTE below. (Trimmed 2026-08-05 to match run.py.)
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. patent-landscape has no card/type
  # yet (licensing-blocked placeholder), so it's absent here; clinical_precedent is pulled.
  # expression_clinical_association (Q11) is an ADDITIVE render facet (verdict-inert — feeds no resolver).
  measurement_types_pulled:
    - mutation_cooccurrence
    - clinical_precedent
    - expression_clinical_association
    - precog_prognostic_association   # PRECOG pan-cancer meta-Z corroboration (verdict-inert render facet)
  rules_scope:
    - co-mutation-and-mutual-exclusivity
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: partial
  # NOTE: clinical-precedent + patent-landscape are intentionally NOT in
  # cards_used above — they are excluded from the runtime card set (their
  # commercial-data licensing is unresolved), so they never reach dispatch.
  # (A previous `on_dependency_status: skip_section` block was removed here
  # because run.py never passed it — the skip is by omission, not by that
  # mechanism. Wiring on_dependency_status is a separate feature decision.)
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

- **Clinical-precedent feed:** Cortellis / IQVIA licensing pending. The card
  is not in this skill's runtime card set, so no section is produced for it.
- **Patent landscape:** PatBase licensing pending. Likewise not in the card set.
- **Paralog buffering** (re-homed): functional-requirement skill consumes
  this — paralog buffering is a Phase C-adjacent dependency-hardening
  signal, not a Phase E differentiation signal (reviewer content flag).

## Output tree (data_package shape)

```
<out>/
├── decision.json                 # rule verdicts + fired rules
├── summary.yaml                  # co-mutation card summary_fields
├── tables/
│   ├── top_cooccurring.csv       # per-partner Fisher q-values
│   └── top_mutually_exclusive.csv
└── provenance.yaml               # data_provenance (manifest IDs) + panel-intersect stats
```

(No `figures/` are emitted by this skill — the shared writer only records
figures a caller places in the dir, and this skill wires no emitter. Invoke
`compose-dashboard` for the rendered co-occurrence figure set.)

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
