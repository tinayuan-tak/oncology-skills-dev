---
name: functional-requirement
description: |
  Focused question skill: "Is target X a genetic dependency in indication
  Y, and how does the call hold up across CRISPR + RNAi + lineage context?"
  Consumes 4 dependency-relevant cards + the dependency-* rule subset.
  Emits a data-package output tree with a rank-ordered dependency verdict.

  Use for focused questions like "is KRAS a dependency in COADREAD?", "is
  MET essential across CRC cell lines?", "does the CRISPR and RNAi signal
  agree for CDK7 in LUAD?" — cases where you want the dependency call
  without the full 16-card evaluation.

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag; the primary output (dependency_verdict + driving_rule_id)
  is modality-independent.

metadata:
  version: 1.3.0
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
    - prism-crispr-concordance           # E-PRISM re-home 2026-07-20: chemical-genetic confirmation arm (was in run.py CARDS, missing here)
    - dependency-predictability          # Gate-C gap 1 (Option A): META-evidence → CONFIDENCE annotation only, NOT the verdict
    # Biomarker-facet render cards (ADDITIVE, verdict-inert — feed NO resolver ladder). Grouped:
    - expression-dependency-correlation  # RNA arm: mRNA predicts dependency (was in run.py CARDS, missing here)
    - recommended-models                 # Q4 patient↔model correspondence: model-backed-dependency (was in run.py CARDS, missing here)
    - abundance-dependency               # Q7 PROTEIN arm: protein abundance predicts dependency (2026-07-22)
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
  rules_scope:
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity
    - paralog-buffering
    - prism-crispr-concordance
    - dependency-predictability
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
    discordant / non_dependent / non_dependent_paralog_buffered / broadly_dependent /
    insufficient*), plus the driving CRISPR + RNAi calls and the predictability
    confidence annotation.
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
  (a selective dependency). Emitted by `methods/dependency_controls`.
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

## Verdict resolution

Rank-ordered (first match wins) — kept deliberately simple, biology-first,
so the logic is inspectable at a glance:

  1. If a rule marked `dominant: true` fires with a killer signal on either
     CRISPR or RNAi (e.g. pan-essential): verdict is `pan_essential_killer`.
  2. Else if `concordant-dependent-supportive-dominant` fires: verdict is
     `concordant_dependent`.
  3. Else if a lineage-selective rule fires: `lineage_selective`.
  4. Else if `concordance-discordant-warning` fires: `discordant`.
  5. Else if any non-dependent rule fires with no counter-signal:
     `non_dependent`.
  6. Else: `insufficient`.

Which specific rule drove the verdict is recorded in the headline
(`driving_rule_id`), so a reviewer can trace back to the interpretation-
rules YAML.

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
4. Read `<OUT_DIR>/decision.json`, present the `dependency_verdict` + the
   `driving_rule_id` + the `dep_control_position_class` (selective vs
   pan-essential) inline, and offer to open the full JSON if the user wants details.
