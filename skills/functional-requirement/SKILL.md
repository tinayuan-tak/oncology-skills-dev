---
name: functional-requirement
description: |
  Focused question skill: "Is target X a genetic dependency in indication
  Y, and how does the call hold up across CRISPR + RNAi + lineage context?"
  Consumes 16 cards: 7 verdict-bearing (CRISPR + RNAi distributions, CRISPR/RNAi
  concordance, lineage-selectivity, paralog-buffering [compound-only veto-suppressor],
  prism-crispr chemical-genetic confirmation, and partner-conditional-dependency
  [WRN×MSI-style SL rescue]) resolved via the shared dependency resolver;
  dependency-predictability + cross-consortium-dependency + coessential-module as
  3 CONFIDENCE annotations (not the verdict); 5 verdict-inert biomarker-facet render
  cards (expression↔dependency, abundance↔dependency, recommended-models,
  genomic-event-model-match, organoid-crispr-dependency); and the --subtypes-gated
  subgroup-stratified-dependency panorama (1). See DATA_PRODUCT.md for the canonical breakdown.

  Use for focused questions like "is KRAS a dependency in COADREAD?", "is
  MET essential across CRC cell lines?", "does the CRISPR and RNAi signal
  agree for CDK7 in LUAD?" — cases where you want the dependency call
  without the full composed target-profile evaluation.

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag; the primary output (dependency_verdict + driving_rule_id)
  is modality-independent.

metadata:
  version: 1.10.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [C]
  cards_used:
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity
    - paralog-buffering                  # Layer 6d addition: dependency-hardening signal
    - partner-conditional-dependency     # Track PC (2026-08-09): VERDICT-BEARING synthetic-lethality rescue — partner-deficient-stratified dependency (WRN×MSI). Fires partner_conditional_dependent in dependency.resolver (distinct verdict; rescues a pooled non_dependent veto, one-directional). MODERATE tier is rescue-firing for this family.
    - prism-crispr-concordance           # E-PRISM re-home 2026-07-20: chemical-genetic confirmation arm (was in run.py CARDS, missing here)
    - cross-consortium-dependency        # Project Score (2026-08-10): Broad-vs-Sanger dependency concordance; gate-C corroboration (raises confidence, verdict-inert)
    - dependency-predictability          # Gate-C gap 1 (Option A): META-evidence → CONFIDENCE annotation only, NOT the verdict
    # Biomarker-facet render cards (ADDITIVE, verdict-inert — feed NO resolver ladder). Grouped:
    - expression-dependency-correlation  # RNA arm: mRNA predicts dependency (was in run.py CARDS, missing here)
    - recommended-models                 # Q4 patient↔model correspondence: model-backed-dependency (was in run.py CARDS, missing here)
    - genomic-event-model-match          # GENOTYPE-matched patient↔model facet (Track C cross-wire, 2026-08-19): complements recommended-models (expression-similarity) with genotype IDENTITY. Built/homed in genomic-alteration-profile; ADDITIVE, verdict-inert — and verdict-inert here means UNINTERPRETED, not "interpreted elsewhere": the card is declared `interpretation: rules_pending` and NO interpretation rule in ANY lane reads `event_correspondence_class` (verified 2026-09-12). It reaches the output only as the render facet `headline.event_correspondence_class`. Same for the two other rule-less dependency-lane cards, `cross-consortium-dependency` and `coessential-module` — both are consumed by run.py's `dependency_confidence_note` in Python, not by a rule.
    - abundance-dependency               # Q7 PROTEIN arm: protein abundance predicts dependency (2026-07-22)
    - organoid-crispr-dependency         # Organoid-native Chronos facet (2026-08-18): dependency in patient-derived 3D organoids (GI-dominated n~114). ADDITIVE, verdict-inert — corroborates a positive call but is never a trusted veto
    - coessential-module                 # Co-essential-module CONFIDENCE facet (2026-08-19): is the dependency embedded in a coherent co-essential module (complex/pathway partners) or isolated? ADDITIVE, verdict-inert — folds into dependency_confidence_note (sibling of cross-consortium + predictability); the enrichment-review #1 item (depmap-coessentiality-26q1-v1 was orphaned)
    - subgroup-stratified-dependency     # SUBTYPE axis (2026-08-06): per-molecular-subgroup Chronos (MSI_H/MSS…); tier:subtype, DESCRIPTIVE panorama (emits NO verdict — display facet like genomic-alteration's by-subgroup card); resolves ONLY on the --subtypes path (SUBTYPE_CARDS), never the whole-cohort spine
  # DATA_TO_SKILL_CONTRACT Rule 3 — the measurement_type CLAIMS this gate PULLs (resolves against
  # target-contracts/vocabularies/measurement_types.yaml; the 2 CRISPR cards fold into one type).
  # chemical_genetic_concordance = the prism-crispr CONFIRMATION arm; dependency_predictability is
  # pulled as confidence META-evidence (feeds dependency_confidence_note, not the verdict). The three
  # biomarker-facet types (expression/abundance dependency correlation + patient_model_correspondence)
  # are ADDITIVE render facets — pulled for the biomarker/preferred-assay synthesis, verdict-inert.
  measurement_types_pulled:
    - crispr_lof_dependency
    - rnai_lof_dependency
    - crispr_rnai_concordance
    - paralog_buffering
    - chemical_genetic_concordance
    - dependency_predictability
    - expression_dependency_correlation
    - abundance_dependency_correlation
    - patient_model_correspondence
    - partner_conditional_dependency      # L3 parity fix (2026-08-13): partner-conditional-dependency was consumed but its measurement_type undeclared
    - cross_consortium_dependency         # L3 parity fix (2026-08-13): cross-consortium-dependency (Broad↔Sanger) was consumed but undeclared
    - coessential_module                  # coessential-module CONFIDENCE facet (2026-08-19): verdict-inert, folds into dependency_confidence_note
    - genomic_event_model_match           # genomic-event-model-match genotype patient↔model facet (2026-08-19): ADDITIVE render facet, verdict-inert
  rules_scope:
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity
    - paralog-buffering
    - prism-crispr-concordance
    - partner-conditional-dependency      # L3 fix (2026-08-13): VERDICT-BEARING (fires partner_conditional_dependent) — was omitted from rules_scope
    # dependency-predictability REMOVED from rules_scope (L3 fix): it is verdict-INERT by design (a
    # CONFIDENCE annotation, feeds NO resolver rung); listing it here contradicted the skill's own design.
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# functional-requirement — Dependency in Indication

## What this skill does

- Fetches the dependency-relevant cards via the compose-dashboard live-reader
  dispatchers (zero new dispatcher code; same read path the composed target-profile uses).
- Filters the intracellular-intrinsic rules to the dependency-* subset (skips
  tvn-*, mutation-*, cn-*, etc.).
- Emits `decision.json` with:
  - `headline`: `dependency_verdict` (pan_essential_killer / concordant_dependent /
    lineage_selective / selective_dependent / chemical_genetic_confirmed_dependent /
    partner_conditional_dependent / lineage_selective_in_indication /
    dependent_in_indication / not_dependent_in_indication / discordant / non_dependent /
    non_dependent_paralog_buffered / broadly_dependent / insufficient*), plus the
    driving CRISPR + RNAi calls and the predictability confidence annotation.
    All 17 tokens with their precedence are under "Verdict resolution" below; that list and
    `resolvers/dependency.resolver.yaml` are the authoritative enum.
  - `fired_rules`: which of the dep-* rules matched.
  - `modality_lenses`: optional SM+degrader tally (`--modality`).

## Contextualized interpretation axes (display-only, verdict-inert)

Two "relative-to-what?" axes anchor the raw dependency signal (mirrors the
tumor-presence hardening). Both are ADDITIVE — no rule reads them, so the
`dependency_verdict` spine is byte-identical with or without them:

- **Axis-2 — control benchmark** (`dep_control_position_class` on the CRISPR
  distribution card): anchors the target's pan-panel median Chronos against curated
  **pan-essential** (ceiling) + **non-essential** (floor) controls. Note the
  **inversion** vs presence: reading `as_essential_as_pan_essential` is a
  **broad-toxicity liability**, NOT a win; the therapeutic window is `between_controls`
  (a selective dependency). Emitted by `onc_methods/dependency_controls`.
- **Axis-3 — across-lineage omnibus** (`lineage_omnibus_effect_size_class` +
  `lineage_variance_explained` ε² on the lineage-selectivity card): the global
  variance view ("how much of the dependency variance does lineage explain?"),
  **complementing** the existing per-lineage-threshold `enrichment_class`. Emitted
  by `depmap_chronos.compute_lineage_summary`.

## Optional molecular-subgroup panorama (`--subtypes`)

Opt-in `--subtypes MSI_H,MSS` (comma-separated stratum ids) resolves the DESCRIPTIVE
`subgroup-stratified-dependency` card — per-molecular-subgroup Chronos **within this
indication's cell lines** (e.g. MSI-H vs MSS), the patient-selection grain **distinct
from lineage** (tissue-of-origin). This is the dependency analog of
genomic-alteration-profile's `--subtypes` and tumor-presence's subtype panorama; the
cell-line→subgroup mapping comes from the `depmap-subgroup-assignments-{indication}-v1`
shards.

**Verdict-inert**: the subgroup cards are resolved on a separate path (the dispatcher's
`subtype_panorama_fn` hook), never enter `fired`, and touch no resolver rung — so
`dependency_verdict` is **byte-identical** with or without `--subtypes`. Without the flag
the path is a complete no-op.

**Power discipline (important)**: DepMap per-indication molecular strata are frequently
**underpowered** (few cell lines per subgroup). The card tags `subgroup_n < 30` as
`underpowered`; the panorama surfaces each stratum's `evidence_state`, and the pattern
label is `not_informative` unless ≥2 strata are `measured`. A cross-subgroup Δ over an
underpowered stratum is **not** read as a subgroup-specific difference (the `--synthesize`
narration enforces the same rule). Availability is per-indication: only indications with a
landed subgroup-assignment shard (COADREAD, ESCA, HNSC, NSCLC, PAAD, STAD) can be scoped.

## Optional LLM synthesis (`--synthesize`)

Opt-in `--synthesize` attaches a provenance-tagged narration under
`decision['llm_synthesis']` (Bedrock, forced structured tool-use). It is a **two-slot**
design: the narration is attached as a SIBLING key AFTER the deterministic decision is
composed, so it is **structurally impossible** for it to alter the verdict spine (a run
WITHOUT the flag is byte-identical). The dependency narrator reads the FULL evidence set
(CRISPR + RNAi + concordance + lineage + paralog + PRISM + predictability) plus the two
axes, and foregrounds the **selective-vs-pan-essential** distinction (a pan-essential
read argues AGAINST the target). A Bedrock failure degrades to a `_synthesis_error` note
— the deterministic verdict is unaffected.

## Optional literature corroboration (`--literature`)

Opt-in `--literature` attaches a provenance-tagged, citation-verified literature synthesis under
`decision['literature_synthesis']` (Europe PMC → PubTator3 fallback grounding + a post-synthesis
`verify_citations` pass; `_verification` reports n_pmid_checked / n_verified / n_flipped) and feeds the
`--synthesize` narrator. It is **verdict-inert** and two-slot (attached after the deterministic decision
is composed), so a run without the flag is byte-identical. The dependency query terms (genetic
dependency / essential gene / CRISPR knockout / RNA interference / oncogene addiction / selective
dependency) are declared per-lens in `_skills_common/literature_retrieval.py`.

## Verdict resolution

The verdict is resolved by the shared declarative resolver
(`target-contracts/resolvers/dependency.resolver.yaml`), evaluated by the ONE
interpreter both engines call. The former per-skill if-chain was retired
(gap #5, 2026-07-20) — the resolver is the source of truth, proven byte-for-byte
equivalent to the old if-chain by the golden-oracle test. The rungs (first
match wins), highest precedence first:

  1. `insufficient_underpowered_pan_essential` — a ≥85% pan-essential call on a
     sub-floor panel (tiny-panel artifact; escapes the killer).
  2. `pan_essential_killer` — no therapeutic window (a SAFETY liability; ranked
     so no lower positive can mask it).
  3. `concordant_dependent` — CRISPR + RNAi both dependent (gold standard).
  4. `lineage_selective` — ≥1 lineage significantly enriched (BH-corrected MW).
  5. `selective_dependent` — context-specific essentiality.
  6. `chemical_genetic_confirmed_dependent` — CRISPR + RNAi both track PRISM
     compound kill (positive-only, veto-safe confirmation).
  7. `discordant` — ≥30% CRISPR/RNAi disagreement (downgrades a shaky veto).
  8. `insufficient_underpowered` — below-floor pooled negative contradicted by a
     concentrated well-sampled lineage.
  9. `non_dependent_paralog_buffered` — pooled non-dependence AND a strong
     paralog buffer → buffering artifact spares the veto (veto-suppressor:
     `when_all_fired`, so it can never fabricate a dependency).
  10. `partner_conditional_dependent` — pooled non-dependence rescued by a
      partner-deficiency-stratified SL signal (WRN×MSI), OR a standalone partner-
      conditional call; strong + moderate tiers, veto-suppressor (`driving_rule`
      re-pointed to the partner rule). Four resolver rungs.
  11. `non_dependent` — CRISPR non-dependence VETO (RNAi-alone non-dependence is
      neutral — false-negative-prone — and never vetoes).
  12. `broadly_dependent` — broad but sub-pan-essential.
  13. `insufficient` — measured coverage gap / nothing fired (provenance-anchored;
      as of 2026-09-06 a live-read-errored backbone card also anchors this rung
      rather than falling through to a null driving_rule).

Indication-conditioned verdicts (resolver v1.5.0+, priorities 4/5/10/11 — they
outrank `lineage_selective` so the target-grain shape token is reachable only on a
run with NO indication supplied). Each fires on the `indication_dependency_class`
card field, which a `dependency` card preprocessor writes at the QUERIED lineage
grain, so the name means what it says about the indication the run asked about:

  - `lineage_selective_in_indication` — the queried lineage IS the enriched one
    (the honest form of `lineage_selective`).
  - `dependent_in_indication` — dependent in the queried lineage, but not
    selectively so.
  - `not_dependent_in_indication` — measured negative in the queried lineage (a
    veto at the indication grain; its escapes mirror the pooled `non_dependent`).
  - `insufficient_underpowered_in_indication` — could-not-look / barely-looked in
    the queried lineage (never a call).

(These are the 17 emitted verdicts; the resolver expresses them across 26 ordered
rungs — several verdicts have multiple rungs, e.g. the CRISPR vs RNAi-both-agree
paths, the partner-conditional strong/moderate × rescue/standalone matrix, and the
indication-killer's paralog twin.)

`driving_rule_id` in the headline records which rule drove the verdict, so a
reviewer can trace back to the resolver rung + the interpretation-rules YAML.

## What this skill does NOT do

- No new dispatchers, no new rules — reuses target-contracts. The verdict is
  resolved from the shared declarative `resolvers/dependency.resolver.yaml`
  (the former per-skill if-chain was retired; the resolver is the source of truth).
- The two contextualization axes + the `--synthesize` narration are ADDITIVE and
  verdict-inert (no rule reads them; the resolver golden snapshot is untouched).
- No figure rendering by default; caller can invoke `compose-dashboard` on
  a filtered spec to get the dependency-card figure set.
- Not modality-locked. Modality lenses are OPTIONAL post-hoc projections
  (biology-first output shape).

## Invocation

```
python scripts/run.py --target KRAS --indication COADREAD \
    --out /tmp/dep-KRAS-COADREAD
# → writes /tmp/dep-KRAS-COADREAD/decision.json

# Optional LLM narration (two-slot, verdict-inert; needs Bedrock creds):
python scripts/run.py --target KRAS --indication COADREAD \
    --out /tmp/dep-KRAS-COADREAD --synthesize
```

## How Claude invokes this skill

When called as `/functional-requirement`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication`
   (AACR OncoTree code, uppercase — e.g. COADREAD, LUAD, BRCA) from the
   user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/functional-requirement/{target}-{indication}`
   unless the user specifies one.
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/functional-requirement/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
   Add `--synthesize` when the user wants a narrative synthesis (attaches
   `decision['llm_synthesis']`; the deterministic verdict is unchanged).
4. Read `<OUT_DIR>/decision.json` and present, inline, the three fields that sit at
   the TOP of `headline`: `dependency_verdict`, `driving_rule_id`, and
   `dependency_confidence` + `dependency_confidence_note` (the verdict-inert
   predictability / cross-consortium / co-essential-module annotation; on a
   `non_dependent*` verdict the note is phrased in the direction of the veto).
   Then offer to open the full JSON if the user wants details.
   Selective-vs-pan-essential positioning is NOT a top-level headline field: it is
   `dep_control_position_class`, nested at
   `headline.subgroup_signals.DEP.claims[*].evidence_atom.values` — quote it only if
   you actually read it from there.
