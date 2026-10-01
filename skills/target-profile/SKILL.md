---
name: target-profile
description: |
  Composed target-profile skill: "Give me the full biology + tractability +
  mutation + prevalence picture of target X in indication Y, with narrative
  synthesis." Fans out (in parallel, in-process) to the 15 wired
  question-answering skills:
    - tumor-presence
    - tumor-selectivity
    - functional-requirement
    - mechanism-and-pharmacology
    - genomic-alteration-profile        (SNV + copy-number + fusion [LIVE, additive])
    - differentiation-landscape
    - tractability-small-molecule       (small-molecule chemical-genetic half)
    - surface-modality-fit              (biologics ADC/TCE half)
    - immune-context                    (TCE effector-arm: CD8 infiltration companion to surface-modality-fit)
    - on-target-safety-liability
    - target-intrinsic                  (indication-independent dossier; GATELESS, verdict=None)
    - cis-feature-coherence             (locus→expression→dependency coherence; GATELESS, verdict-inert)
    - combination-and-vulnerability     (consolidated relational annex: SL + measured dual-KO + combo + resistance; GATELESS, verdict=None)
    - translational-readiness           (HCMI model availability + genotype-matched + PDXE in-vivo drug-response; GATELESS, verdict=None)
    - literature-context                (cited-literature evidence: co-occurrence volume/recency + typed relation direction; GATELESS, verdict-inert)
  Collects each sub-verdict, then invokes Tier-3 structured LLM synthesis
  (Bedrock tool_choice-forced) for executive_summary + tension_analysis +
  recommendation. Emits `target_profile.md` + `nomination.json` +
  provenance.

  RESTRUCTURED 2026-07-14 (scope deep-dive): tractability-and-modality SPLIT
  into tractability-small-molecule + surface-modality-fit; mutation-profile
  REFRAMED to genomic-alteration-profile; patient-population-and-access DELETED
  (prevalence folded into genomic-alteration-profile); surfaceome-cohort-ranking
  DROPPED from the fan-out (per-indication scan, not a per-target skill).

  Every LLM-produced field is tagged with `_source: llm_synthesized`,
  `_model_id`, and `_prompt_hash`. Sub-verdicts (deterministic, rule-
  fired) are stored in distinct schema slots from LLM narrative — the
  audit spine is invariant even if narrative drifts between runs.

  Use for full biologist-oriented profile requests: "profile TP53 in
  COADREAD", "give me the full picture on KRAS in colorectal cancer",
  "should we nominate MET in NSCLC?"

metadata:
  version: 1.3.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    # The fan-out reads the onc-compbio bucket via the boto3 DEFAULT credential chain.
    # No AWS_PROFILE is required: all that matters is the resolved identity is in an
    # onc-compbio account (default 557690623046; override the set via ONC_COMPBIO_ACCOUNT_IDS).
    # A SageMaker execution role in that account resolves automatically. On a local-dev box
    # whose default chain points elsewhere, `export AWS_PROFILE=cbg` (or any profile in that
    # account) — the preflight validates by ACCOUNT, not profile name.
    - AWS_REGION=us-east-1  # Bedrock (only for the --synthesis LLM step)

composition:
  data_mode: derived_read
  phase: [A, B, C, D, E, F, G, H, K]           # EXTENDED 2026-07-08: added D, E, G
  cards_used:
    # Phase A + B (presence + selectivity)
    - cellline-rna-distribution
    - tumor-rna-vs-adjacent
    - tumor-vs-normal-selectivity
    - tumor-protein-abundance-cptac                   # Layer 6h addition (Phase A)
    # Phase C (requirement)
    - pan-cancer-crispr-dependency-distribution
    - pan-cancer-rnai-dependency-distribution
    - crispr-rnai-dependency-concordance
    - dependency-lineage-selectivity
    - paralog-buffering                        # Layer 6h addition (Phase C-adjacent)
    # Phase C (combinatorial-dependency: MEASURED dual-KO SL complement)
    - combinatorial-dependency                 # 2026-08-14: DepMap ParalogV2 dual-KO GI + published corroboration; gateless, additive
    # Phase A/E (genomic-alteration-profile: SNV + copy-number + fusion)
    - mutation-type-counts
    - mutation-stratified-dependency
    - mutation-hotspot-frequency
    - copy-number-distribution                 # 2026-07-14 CN axis wired
    - fusion-rearrangement-landscape           # LIVE (tcga-fusion-consensus-v1); additive signal-only
    - co-mutation-and-mutual-exclusivity       # (differentiation-landscape)
    - pathway-node-leverage                    # WS3 (differentiation-landscape): comparative node-leverage; verdict-inert soft context
    # Phase D (mechanism)
    - signaling-network-mechanism              # Layer 6h addition (Phase D)
    # Phase F (tractability-small-molecule: chemical-genetic)
    - prism-compound-activity
    - prism-crispr-concordance
    - dependency-predictability
    # Phase F (surface-modality-fit: biologics ADC/TCE)
    - surface-topology-and-ptm
    - surfaceome-family-classification
    - structure-features-static
    - surface-abundance-density
    - adc-tce-modality-fit
    # (surfaceome-cohort-ranking DROPPED from fan-out 2026-07-14 — per-indication scan)
    # Phase G (safety)
    - gnomad-lof-constraint                    # Layer 6h addition (Phase G)
    # cis-feature-coherence (Stage 2 2026-08-20: locus→expression→dependency coherence; GATELESS, verdict-inert)
    - cis-feature-expression-coherence         # NEW leg-1: CN→own-expression cis-dosage. leg-2 cards
                                               # (expression-dependency-correlation, amp-expr-stratified-dependency)
                                               # are HOME cards of functional-requirement / genomic-alteration-profile,
                                               # composed there; the cis_coherence axis rules fire on their fields.
    # target-intrinsic EXCLUSIVE cards (WS1 2026-08-17; GATELESS descriptive dossier —
    # its other 12 cards are HOME cards of other sub-skills' lenses, composed there, not re-listed)
    - target-identity-summary                  # canonical id / family / aliases
    - target-development-level                 # Pharos/IDG TDL druggability/novelty tier
    - protein-domains-class                    # UniProt FT DOMAIN architecture + protein class
    - domain-modality-relevance                # domain→modality facet (inhibitor_sufficient vs removal_required)
    - ppi-interactome                          # STRING functional network + CORUM complex membership
    - gene-ontology-annotation                 # GO BP/MF/CC term membership
    - reactome-pathway-membership              # Reactome pathway/geneset membership + rollup
    # Subtype tier — DEFAULT-ON (v1.3.0): strata auto-resolve from the contracts subtype_crosswalk;
    # --no-subtypes opts out, and an unregistered indication degrades to whole-cohort on its own.
    - subgroup-stratified-dependency           # verdict-bearing (cell-line dependency)
    - subgroup-stratified-mutation-frequency   # display-only in this tier
    # tumor-vs-normal-selectivity (declared above under selectivity) is ALSO composed in the subtype
    # tier: DUAL-GRAIN, its per-subgroup selectivity panorama is verdict-bearing here
    # (subtype_restricted_selectivity). 2026-09-11 STAD subtype-shard wiring. Not re-listed to avoid a
    # duplicate cards_used entry.
  rules_scope:
    - all
  synthesis:
    - rule_engine
    - structured_llm
  output_shape:
    - target_profile
  steps_covered: [1, 2, 3, 4, 5, 6]
  optional_lenses:
    - modality
    - therapeutic_hypothesis
  status: wired
---

# target-profile

## What this skill does

- Runs the 14 wired question-answering skills in parallel (all data-package
  producers): tumor-presence, tumor-selectivity, functional-requirement,
  mechanism-and-pharmacology, genomic-alteration-profile, differentiation-landscape,
  tractability-small-molecule, surface-modality-fit, immune-context,
  on-target-safety-liability, target-intrinsic, cis-feature-coherence,
  combination-and-vulnerability, translational-readiness.
  - **Six** shorts are **gateless** (absent from the kill/hold gate map `_SHORT_TO_GATE`):
    `expression` (tumor-presence), `immune-context`, `target-intrinsic`, `cis-feature-coherence`,
    `combination-and-vulnerability`, and `translational-readiness`. They surface in `sub_verdicts` + the
    LLM synthesis but do NOT drive
    the deterministic KILL/HOLD recommendation spine, which stays byte-stable. Nuances: `target-intrinsic`,
    `combination-and-vulnerability`, and `translational-readiness` are additionally **descriptive**
    (`verdict=None`). `cis-feature-coherence`
    emits a resolver verdict and has since **graduated** (2026-08-20) into the positive tier — its
    `coherent_cis_driver` is a `positive_signal` and `expressed_cis_coupled_inert` a `positive_contradiction`,
    so it can raise the confidence FLOOR and name the deciding axis — but it stays out of `_SHORT_TO_GATE`,
    so it still never forces a nominate/hold/veto.
- Collects each sub-verdict + fired rules + card summaries.
- Invokes Bedrock (Opus by default via env `ANTHROPIC_MODEL`) with a
  structured tool_use forcing the LLM to emit:
  - `executive_summary` — 3-5 sentence overall picture
  - `tension_analysis` — where sub-verdicts disagree + why
  - `top_arguments_for` — up to 5 strongest positive points
  - `top_arguments_against` — up to 5 strongest negatives
  - `overall_recommendation` — nominate / hold / veto (enum)
  - `confidence` — high / medium / low / insufficient (enum)
- Emits:
  - `target_profile.md` — rendered narrative with clearly-tagged LLM
    sections + rule-derived sub-verdict tables
  - `nomination.json` — structured version of the full profile
    (sub_verdicts + LLM output + provenance)
  - `provenance.yaml` — audit anchor

## What this skill does NOT do

- Does NOT run compose-dashboard's dashboard_spec-driven card dispatch. This is a
  fan-out-over-sub-skills composer with a cross-gate nomination — a legitimately
  distinct composition pattern. (It CAN now emit an `evidence_package.json`
  envelope of its own composed verdict — see Output modes below — but does not
  consume a dashboard_spec.)
- Does NOT synthesize LLM output for the categorical spine — that stays
  deterministic (rule-fired). LLM only writes narrative + high-level
  recommendation.

## Output modes (`--emit`)

`--emit` selects the output shape over the SAME deterministic verdict spine:

- `--emit nomination` (default) — the biologist-facing narrated profile:
  `nomination.json` + `target_profile.md` + `target_profile.html` + `provenance.yaml`
  (+ figures), with the Tier-3 LLM narrative.
- `--emit evidence-package` — the machine-facing artifact: a deterministic, **LLM-free**
  `evidence_package.json` envelope conforming to the shared contract (validates
  against `target-contracts/schemas/evidence_package.schema.json`). It implies
  `--no-synthesis` + `--no-figures` and writes **no** nomination.json / md / html. Its
  `synthesis` block is a SUPERSET of the schema's minimum: target-profile's nomination fields
  (`recommendation_gate` / `confidence_tier` / `deciding_axis`) + a schema-conformant
  `primary_gate_verdict` + `additional_gate_verdicts` split + the full per-sub-skill
  `sub_verdicts` — all sourced from each sub-skill's shared `CompositionResult`, with no
  re-resolution. `governance.data_mode` is `exploratory` (live, unpinned, not
  concurrence-reviewed).

## Grounded-substrate chain (DEFAULT-ON) — ground → risk → hypothesis

**DEFAULT-ON (2026-08-26, v1.2.0).** A full nomination run now AUTO-RUNS the whole grounded-substrate
two-projection chain in-process, after the fan-out, over the just-assembled `evidence_package.json`:

1. **ground** — `literature-risk-assessment/ground_axis` per engine axis → `grounded_<axis>.json`
   (escalate-only, PMID-cited literature findings). The ONE shared substrate.
2. **[3A] risk** — BOTH 6-dim risk reads:
   - `risk_rollup.json` — the **deterministic** modality-conditioned bins (a pure function of the
     sub_verdicts; grounded findings only escalate, never move a bin).
   - `risk_assessment.json` — the **LLM** retrieval-grounded 6-dim literature read
     (`literature-risk-assessment`: Biological / Druggability / Translational / Clinical / Safety /
     Commercial).
3. **[3B] hypothesis** — `cross-evidence-hypothesis` → `hypothesis.json`, the gate-clamped, cited,
   six-part drug-target hypothesis reasoning ACROSS the lines (it is surfaced beside — not reconciled
   into — the Tier-3 exec-summary on the HTML dashboard, an independent second read). Consumes the
   shared substrate + the 6-dim risk from step 2.

All three are **DISPLAY-ONLY / verdict-INERT** — they read the finished spine and NEVER change a
sub-verdict, gate, or the recommendation — and **best-effort** (any failure — Bedrock, PubMed, parse —
is logged and degrades to "not shown"; the profile still emits). Because they call **Bedrock + PubMed**
and are **non-reproducible**, a default run is **no longer byte-identical / offline** (the Tier-3
synthesis already made a default run call Bedrock; this adds the PubMed retrieval).

### Opting out / tuning
- `--no-substrate` — opt OUT of the whole chain; restores the offline, network-free, byte-identical run.
- `--no-ground` / `--no-risk` / `--no-hypothesis` — granular per-leg opt-outs.
- The chain is **auto-skipped** in the offline/fast/machine modes (`--no-synthesis`, `--verdict-only`,
  `--emit evidence-package`), which stay byte-identical.
- An explicit `--ground` / `--grounded-dir` / `--risk-assessment` / `--risk-rollup` / `--hypothesis`
  input **always wins** over the auto-produced artifact.

### `--ground` axis selection (explicit override)
- `--ground` / `--ground engine` — the engine axes (`safety`, `dependency`, `selectivity`,
  `surface_modality`, `tractability_sm`, + the rolled-out `mechanism` / `genomic_alteration` /
  `differentiation` / `expression`) that anchor to a sub-verdict. This is also the default when the
  chain is on.
- `--ground all` — engine axes **+** the `clinical` / `commercial` pseudo-cards (engine-blind,
  literature-only).
- `--ground safety,dependency` — an explicit comma-list (validated against `ground_axis.AXIS_CONFIG`).

## Optional lenses

- `--modality <M>` — projects each sub-skill's fired rules onto a
  modality lens (small_molecule / degrader / adc / bite / antibody).
  Sub-verdicts unchanged; the LLM synthesis reshapes the executive-summary
  language to lens-emphasized reasoning.
- `--therapeutic-hypothesis "<text>"` — free-text clinical framing (line-
  of-therapy, patient state, clinical goal). Reshapes the executive-
  summary and argument prioritization to hypothesis-relevant evidence.
  Sub-verdicts unchanged.

## Verdict-affecting scope (`--subtypes` / `--no-subtypes`)

Unlike the lenses and fast modes above (which are verdict-inert), the subtype scope **can change the
recommendation spine**.

**DEFAULT-ON (2026-09-11, v1.3.0).** The subtype tier now runs on every profile. When `--subtypes` is
omitted, the run resolves the indication's registered stratum set from
`target-contracts/vocabularies/subtype_crosswalk.yaml` (the curated, axis-organized registry — the
data-catalog subgroup catalogs are the id source of truth but carry staging strata like `stage_I` and
source-duplicated `CMS*_depmap` ids, which are wrong for a molecular tier). WHY the change: the tier is
verdict-bearing in BOTH directions, yet while it was opt-in no published panel run ever evaluated it —
a subtype-restricted dependency and a subtype-specific NON-dependence both read as whole-cohort
silence. `provenance.scope_subtypes_source` records which path was taken (`auto:subtype_crosswalk`,
`auto:subtype_crosswalk:alias_of:<CODE>`, `explicit:--subtypes`, `disabled:--no-subtypes`,
`unavailable:<CODE>`).

**Indication ALIASES (2026-09-13).** The registry is keyed by `canonical_code`, so a sub-indication or
synonym code used to resolve zero strata and run whole-cohort. Curated aliases from
`indication_crosswalk.yaml` now resolve (`LUAD`/`LUSC` → NSCLC, `COAD`/`READ` → COADREAD, `GC` → STAD,
…) and the provenance token names which indication answered. **Axes declared `partition: co_defining`
are dropped on an alias**: NSCLC's `histology_Adeno` is (approximately) the whole LUAD cohort, so
stratifying a LUAD run by that axis yields one degenerate stratum with no cross-stratum contrast — and
the verdict-bearing `subtype_restricted_dependency` rung reads a single stratum's own class, so it
cannot detect the degeneracy itself. Pure synonym aliases lose nothing (only NSCLC and ESCA declare a
`co_defining` axis, and ESCA has no aliases). The same resolution routes the per-indication
subgroup-assignments shard registries, so an alias run reaches the shards its canonical cohort has;
reads served that way are labelled with the CANONICAL cohort and carry `_indication_scope`
`{requested, resolved, how}`, because shard membership is the canonical cohort's, not the alias's.

- `--no-subtypes` — skip the tier entirely (whole-cohort only); the pre-v1.3.0 default. Overrides
  `--subtypes`.
- An indication absent from the crosswalk (e.g. MPN, AML) resolves to zero strata and stays
  whole-cohort — the tier is a no-op there rather than an error. AML is deliberately still
  whole-cohort: its data-catalog strata exist but no `*-subgroup-assignments-aml-*` shard does, so
  wiring it would request strata nothing can serve.
- `--subtypes <ids>` — comma-separated molecular subgroup ids (e.g. `MSI_H,MSS`) to scope the tier to a
  chosen subset (or to strata outside the curated registry, including staging). It is BI-DIRECTIONAL,
  negative-precedence, over MEASURED,
  floor-cleared (n>=30) strata:
    - NEGATIVE (precedence): a NOT-dependent subtype fires subtype-non-dependence → gate `hold`
      (`subtype_specific_non_dependence`).
    - POSITIVE (dependency): a STRONG-dependent subtype → `subtype_restricted_dependency` (a SUPPORTIVE
      positive + `non_dependent` veto-suppressor; the precision-oncology channel).
    - POSITIVE (tumor-tissue selectivity, 2026-09-11): a STRONG per-subtype tumor-vs-normal selectivity
      stratum → `subtype_restricted_selectivity` (a SUPPORTIVE positive, NOT a veto-suppressor). The
      tumor-tissue analogue that reaches indications whose DepMap subtype dependency channel is
      data-blocked (STAD/ESCA carry 0 subtype-labeled DepMap lines).
  Precedence when several fire: opposing HOLD > dependency-supportive > selectivity-supportive.

## Provenance / instrumentation flags (verdict-inert)

- `--release-pin <pin>` — STAMP a data `release_pin` into `governance`/`provenance` for
  reproducibility parity with compose-dashboard. **Pass-through only**: target-profile reads live and
  does NOT auto-resolve the release; absent this flag the pin is recorded as `unpinned` (honest,
  never fabricated). Auto-resolution is a deferred data-catalog follow-on.
- `--profile-timers` — emit per-sub-skill READ vs FIGURE-EMIT wall-clock timings to stderr
  (instrumentation only; zero effect on artifacts).

## The literature lane here is `--subskill-literature`, NOT `--literature`

⚠️ **This skill does NOT accept `--literature`.** That flag belongs to the sub-skill dispatcher
(`_skills_common/dispatcher.py`), which the orchestrator does not route through — passing it exits
**rc 2, `unrecognized arguments`**. There is also **no top-level `nomination["literature_synthesis"]`**;
looking for one and finding nothing is the expected shape, not a failed lane.

- **It is already DEFAULT ON.** The master switch is `--rich-embedded` (default **True**), which runs
  each sub-skill's narrative *and* literature lane in the fan-out. So a plain run already produces the
  literature read — you do not need to opt in.
- **Where the block actually lands**: per sub-skill, inside that sub-skill's embedded
  `evidence_graph` decision (`tp_fanout.py:1578`) and on its `synthesis_facet["literature_synthesis"]`
  (`:1487`) — *not* at the top level. Read it per axis, not once for the nomination.
- `--subskill-literature` / `--no-subskill-literature` overrides `--rich-embedded` for the literature
  lane only; `--synthesize-subskills` does the same for the narrative only.
- `--subskill-literature-scope all|gating` — `all` (default) or the 8 gating axes only (cheaper).
- **AUTO-OFF** whenever top-level synthesis is suppressed: `--no-synthesis`, `--verdict-only`, and
  `--emit evidence-package` (that value only — `--emit nomination`, the default, does NOT suppress it;
  `--verdict-only` and `--emit evidence-package` both work by forcing `no_synthesis`, `run.py:560-569`).
  If a run produced no literature at all, check those first — the fast modes are Bedrock-free by design.
- Cost is the reason it is worth knowing about: up to 14× (EuropePMC/PubTator retrieval + Bedrock
  literature synthesis). `--no-rich-embedded` gives an omics-rich, Bedrock-lean run.

Verdict-INERT and display-only in every combination — the deterministic spine stays byte-identical.

## Fast modes (deterministic spine, no LLM)

The deterministic verdict spine — sub-verdicts, the recommendation gate, the positive tier, the
deciding axis, the gate scorecard, and the biomarker/subtype facets — is computed independently
of the Tier-3 LLM synthesis. These flags skip verdict-inert work and leave that spine
**byte-identical** to a full run:

- `--verdict-only` — umbrella fast mode (implies `--no-synthesis` + `--no-figures`). Emits
  `nomination.json` + a narrative-free `target_profile.md` + `provenance.yaml` with **no Bedrock
  call** and no figure/panel render. Use for CI, iteration, and re-runs where only the auditable
  nomination is needed. `nomination.json` marks `llm_synthesis._synthesis_skipped: true`, and the
  report shows a note in place of the narrative.
- `--no-synthesis` — skip only the LLM synthesis tail (keep figures).
- `--no-figures` — skip only figure/HTML rendering (keep synthesis).

## How Claude invokes this skill

When called as `/target-profile`, Claude should:

1. Extract `target` + `indication`. Optionally extract `modality`,
   `therapeutic-hypothesis`, and/or molecular `subtypes`/subgroups from the
   user's natural-language prompt if named.
2. Pick an `out` directory (default `/tmp/target-profile/{target}-{indication}`).
3. Run. The S3 reads use the boto3 DEFAULT credential chain — no profile export is
   needed when the ambient identity already resolves to an onc-compbio account (e.g. a
   SageMaker execution role in account 557690623046). Only prefix `export AWS_PROFILE=cbg &&`
   on a local-dev box whose default chain points elsewhere (and where a `cbg` profile is
   configured); the preflight validates by ACCOUNT, not profile name, so it fails loudly
   rather than silently degrading if the identity is wrong.
   ```
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/target-profile/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
   Add `--modality <M>`, `--therapeutic-hypothesis "<text>"`, and/or `--subtypes <ids>`
   if supplied by the user. The subtype tier runs by DEFAULT (strata auto-resolved) and can
   change the verdict — pass `--subtypes` only to narrow it, `--no-subtypes` to skip it. Add
   `--emit evidence-package` when the user wants the machine-facing `evidence_package.json`
   envelope instead of the narrated profile (deterministic, LLM-free — no
   `AWS_PROFILE`/Bedrock needed).
4. Read `<OUT_DIR>/target_profile.md` and present the executive summary
   inline; offer the full nomination.json for detail. (For `--emit
   evidence-package`, read `<OUT_DIR>/evidence_package.json`.)
