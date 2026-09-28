---
name: differentiation-landscape
description: |
  Phase-E skill — co-mutation + mutual-exclusivity landscape for a target,
  panel-intersect-aware Fisher's-exact scan across TCGA MC3 + GENIE 19.0.

  GRADUATED 2026-07-08: placeholder → partial. Co-mutation card wired via
  cooccurrence_fisher_pancohort method + pancohort-cooccurrence-fisher-v1
  derived manifest. clinical-precedent is now WIRED (2026-08-21) via public-domain
  AACT (ClinicalTrials.gov) — no commercial license needed — and is produced in the
  composed dashboards; only patent-landscape remains placeholder (PatBase-equivalent
  licensing unresolved). Paralog-buffering was RE-HOMED to functional-requirement skill
  (Phase C-adjacent) per reviewer content flag — buffering is a
  dependency-hardening signal, not a differentiation signal.

  Question this skill answers:
  What genes co-occur with or are mutually exclusive to {target} mutations
  across TCGA MC3 + GENIE 19.0-public, and what patient-selection or
  combination-biology hypotheses does the pattern support?

  Reviewer-driven BLOCKER FIX (2026-07-08): the verdict is a PER-SOURCE,
  indication-scoped co-mutation class — NO cross-source pooling is performed
  (there is no pooled q-value column). `pooled_eligible` is DISPLAY/interpretation
  metadata flagging pairs where both genes fall in the 166-gene GENIE
  panel-intersect; it does NOT gate a pooled statistic (none exists). The
  naive-pooling failure mode (artifactual mutual-exclusivity for panel-absent
  genes) is prevented by NOT pooling at all, plus a TCGA-WES-only passenger
  floor and a panel-absence caveat.

metadata:
  version: 1.13.0
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
    - pathway-node-leverage               # WS3 (2026-08-17): COMPARATIVE node-leverage (is target the best NODE to hit, or dominated?); soft/verdict-inert differentiation context — its rules emit axis_fit signals + fired_rule_ids for the cross-evidence hypothesis agent; feeds NO resolver (verdict byte-stable)
    - alteration-clinical-association       # Q11-alteration (2026-08-20): OS by target MUTATION status; verdict-inert prognostic render facet (alteration arm of the differentiation prognostic question)
    - subtype-survival-association          # Q2-subtype (2026-08-20): OS ACROSS molecular subtypes (target-independent patient-selection context); verdict-inert
    - clinical-precedent                    # (2026-08-21) AACT clinical-trial precedent (highest stage / active trials / approved agents / notable failures for a target-engaging drug); ADDITIVE, VERDICT-INERT translational-maturity render facet
    - competitor-landscape                  # (2026-08-24) Open Targets competitor field (who else is developing a drug against this target, at what MODALITY + clinical stage); ADDITIVE, VERDICT-INERT competitive-positioning render facet. The cross-ref vs the framework's own modality-fit/biomarker verdicts is a target-profile synthesis-layer step.
    - mutational-signature-context          # (#1815, 2026-09-28) TCGA MC3 per-indication mutational-process context (dominant SBS + MMR-deficiency/HRD/APOBEC/POLE/tobacco/UV classes); the canonical patient-selection biomarker axis (MMR-deficiency→IO, HRD→PARP, TMB proxies). ADDITIVE, VERDICT-INERT render facet (feeds NO resolver — verdict byte-stable).
    - oncogenic-pathway-alteration          # (#1816, 2026-09-28) Sanchez-Vega 2018 per-indication oncogenic pathway-alteration FREQUENCY lens (orthogonal GENOMIC complement to the dependency-only pathway-node-leverage NODE axis). ADDITIVE, VERDICT-INERT render facet (no resolver rung — verdict byte-stable).
    # patent-landscape intentionally NOT listed — stays unwired (PatBase-equivalent licensing
    # unresolved). See NOTE below.
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. patent-landscape has no card/type
  # yet (licensing-blocked placeholder), so it's absent here; clinical_precedent's card is now WIRED
  # (public-domain AACT) and IS composed in THIS skill's cards_used (v1.5.0) as a verdict-inert
  # translational-maturity render facet. expression_clinical_association (Q11) is an ADDITIVE render facet
  # (verdict-inert). 2026-08-14 review: added stemness_context — the stemness-context card (Malta 2018,
  # added 2026-08-10) is in cards_used but its type was omitted here. test_differentiation_measurement_types.py
  # now enforces every used card's type is declared so this cannot silently re-drift.
  measurement_types_pulled:
    - mutation_cooccurrence               # co-mutation-and-mutual-exclusivity (verdict-driving)
    - stemness_context                    # stemness-context (Malta 2018 mRNAsi; verdict-inert)
    - expression_clinical_association     # expression-clinical-association (Q11; verdict-inert render facet)
    - precog_prognostic_association       # precog-prognostic-association (PRECOG pan-cancer meta-Z; verdict-inert)
    - clinical_precedent                  # clinical-precedent card (WIRED public-domain AACT); now COMPOSED in this skill (cards_used) as a verdict-inert render facet
    - competitor_landscape                # competitor-landscape card (WIRED Open Targets 26.06 drugAndClinicalCandidates); COMPOSED as a verdict-inert competitive-positioning render facet
    - pathway_node_leverage               # WS3 (2026-08-17): pathway-node-leverage card (comparative; verdict-inert soft differentiation context)
    - alteration_clinical_association     # alteration-clinical-association (Q11-alteration; verdict-inert prognostic render facet)
    - subtype_survival_association        # subtype-survival-association (Q2-subtype; verdict-inert)
    - mutational_signature_context        # mutational-signature-context (#1815; TCGA MC3 per-indication mutational processes; verdict-inert patient-selection facet)
    - oncogenic_pathway_alteration        # oncogenic-pathway-alteration (#1816; Sanchez-Vega genomic pathway-alteration frequency; verdict-inert lens)
  rules_scope:
    - co-mutation-and-mutual-exclusivity
    - pathway-node-leverage               # WS3: soft axis_fit signals, NOT wired to differentiation.resolver (additive; fired_rule_ids feed the hypothesis agent)
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: partial
  # NOTE: clinical-precedent is now WIRED (public-domain AACT) and COMPOSED in this skill's cards_used
  # (2026-08-21, v1.5.0) as a verdict-inert render facet — it reaches dispatch via the generic
  # dispatcher (the card's module/entrypoint). patent-landscape stays unwired (PatBase-equivalent
  # licensing unresolved), so it is the only card still absent from cards_used.
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

- **Patent landscape:** PatBase-equivalent licensing pending. Not in the card set.
  (Clinical-precedent is now DONE — WIRED via public-domain AACT and composed here as a
  verdict-inert render facet, v1.5.0.)
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
exclusive row. `pooled_eligible` is DISPLAY/interpretation metadata — it flags
pairs where both genes sit on the 166-gene GENIE panel-intersect; it does NOT
gate a pooled statistic (no cross-source pooling is performed and no pooled
q-value column is emitted). The verdict is always per-source (TCGA MC3 and
GENIE scored separately) and indication-scoped, with a TCGA-WES-only passenger
floor; per-source claims are available for panel-ineligible genes.

## Iter-2 roadmap

1. clinical-precedent DONE (2026-08-21, public-domain AACT) — card wired + composed in this skill (v1.5.0).
2. PatBase or equivalent → patent-landscape card wiring.
3. Method upgrade: DISCOVER (Canisius 2016) or SELECT (Mina 2020)
   alongside Fisher — cited in the card's caveats as principled successors.
