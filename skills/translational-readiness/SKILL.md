---
name: translational-readiness
description: |
  PARTIAL SKILL (graduated 2026-08-14, scientific-gap #1) — was a pure placeholder; now composes the
  target-model-availability card (public HCMI patient-derived model coverage per indication), the
  "can I preclinically validate a nomination in this indication?" leg of translational readiness.

  Question this skill answers (partially): How translationally ready is target X in indication Y —
  are patient-derived (HCMI organoid / next-generation cancer) models available to validate it?

  DESCRIPTIVE (emits no verdict — like target-intrinsic): model availability is translational CONTEXT
  that informs confidence, not a nomination gate.

  Also composes three more public translational legs: the HCMI genotype-MATCHED-model card (does an
  available patient-derived model carry THIS target's alteration?), the organoid ex-vivo dependency card
  (does the target's dependency reproduce in patient-derived 3D CRISPR organoids — borrowed from the
  dependency axis), and the PDXE in-vivo drug-response card (does the target's tractability reproduce in
  Novartis PDXE PDX population trials?).

  STILL PARTIAL: the PD-assay, imaging-tracer, and INTERNAL Takeda models (PDX/organoid/GEMM) legs
  remain un-wired (those catalogs are not in data-catalog).

metadata:
  version: 1.5.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [J]
  cards_used:
    - target-model-availability   # scientific-gap #1: per-indication HCMI patient-derived model coverage;
                                  # INDICATION-level, target-independent; VERDICT-INERT translational context
    - target-genotype-matched-model  # genotype-matched refinement: do available HCMI models carry THIS
                                  # target's alteration? (gene x indication, HCMI WXS MAF join); VERDICT-INERT
    - target-pdx-drug-response    # in-vivo tractability corroboration (Novartis PDXE, Gao 2015); target-grain;
                                  # VERDICT-INERT translational display facet
    - organoid-crispr-dependency  # ex-vivo dependency reproduction (DepMap 3D CRISPR organoids); BORROWED from
                                  # the dependency axis, read as translational validation-readiness; VERDICT-INERT
  measurement_types_pulled:
    - model_availability          # target-model-availability (cohort-grain, HCMI-CMDC-DR45 derived)
    - genotype_matched_model      # target-genotype-matched-model (target_indication-grain, HCMI WXS MAF join)
    - pdx_drug_response           # target-pdx-drug-response (target-grain, PDXE-Gao-2015 derived)
    - crispr_lof_dependency       # organoid-crispr-dependency (target-grain, DepMap 26Q1 OrganoidGeneEffect)
  rules_scope:
    - none                        # DESCRIPTIVE skill (verdict_fn=None) — no resolver rung
  synthesis:
    - none
  output_shape:
    - data_package
  steps_covered: [1, 2]
  status: partial
---

# translational-readiness — partial

## Status: partial (graduated from placeholder 2026-08-14)

This skill was a pure placeholder. It now composes ONE real translational signal — the public HCMI
patient-derived model-availability card — and honestly flags the remaining un-wired legs.

When invoked, it emits `decision.json` with:

- `status: "partial"`
- a DESCRIPTIVE headline (no verdict — `verdict_fn=None`):
  - `model_availability_class`: `deep_model_coverage` (>=50 models) / `moderate_model_coverage`
    (15-49) / `sparse_model_coverage` (<15) / `data_unavailable`
  - `n_patient_derived_models`: count of distinct HCMI models crosswalked to the indication
  - `primary_site_breakdown`: provenance of which GDC histologies mapped in
  - `model_source`: `HCMI-CMDC-DR45`
  - `genotype_matched_class`: `matched_deep` (>=5 models) / `matched_sparse` (1-4) / `none` (0) /
    `data_unavailable` — do the available HCMI models carry a functional coding alteration in THIS target?
  - `n_models_with_alteration`: distinct HCMI models carrying an alteration in the target (within the indication)
  - `pdx_drug_response_class`: `pdx_objective_responders` / `pdx_no_objective_response` /
    `pdx_response_unavailable` / `data_unavailable` — does the target's tractability reproduce in vivo (PDXE)?
  - `pdx_responder_fraction`: objective-response rate (mRECIST CR/PR) across PDX models + treatments
  - `pdx_most_active_treatment`: the best single agent/combo naming the target in PDXE
  - `pdx_median_best_avg_response` / `pdx_min_best_avg_response`: the regression MAGNITUDE (signed %
    tumour-volume change; more-negative = more shrinkage) across contributing PDXE records — the
    decisive datum behind `pdx_drug_response_class`
  - `pdx_n_models_tested` / `pdx_n_response_records`: PDX model / response-record breadth backing the
    class + magnitude reads
  - `pdx_most_active_treatment_median_best_avg_response`: the per-treatment median magnitude of
    `pdx_most_active_treatment`
  - `pdx_treatment_types`: `single` / `combo` / `single|combo` — the authoritative treatment-type mix
    (vs. inferring combination from the treatment-name substring)
  - `organoid_dependency_class`: `pan_organoid_essential` / `broad_organoid_dependency` /
    `selective_organoid_dependency` / `rare_organoid_dependency` / `not_organoid_dependent` /
    `data_unavailable` — does the target's dependency reproduce EX VIVO in patient-derived 3D CRISPR organoids?
  - `organoid_frac_dependent`: pan-organoid dependent fraction (fallback context)
  - `organoid_lineage` / `organoid_lineage_frac_dependent` / `organoid_lineage_class`: the
    indication-matched organoid lineage read — the most granular ex-vivo display facet (VERDICT-INERT:
    it feeds no verdict, risk bin, or claim-vector tier; the claim vector's ORGANOID tier keys the pan
    `organoid_dependency_class` instead); `null` when the indication has no mapped organoid lineage
  - `organoid_lineage_n_screened` / `organoid_lineage_small_cohort`: the indication-matched lineage's
    screened-organoid count and a reliability caveat — `true` when that cohort is below the organoid
    card's `min_organoid_models` (20) floor (e.g. Prostate n=9, Breast n=16 in 26Q1), so the per-lineage
    class rests on a thin cohort. Verdict-inert; the class itself is unchanged.
- `partial_status_note`: the still-un-wired legs.

## What this skill wires

- **target-model-availability** (scientific-gap #1, lighter-v1): per-indication HCMI (Human Cancer
  Models Initiative) patient-derived model coverage. INDICATION-level, target-INDEPENDENT translational
  cohort context — "how many patient-derived models exist to validate a target here?" Backed by
  `hcmi-model-availability-per-indication-v1` (631 of 805 models across 12 indications; broadened 2026-08-24).
- **target-genotype-matched-model** (genotype-matched refinement): the target-DEPENDENT complement —
  "do the available HCMI models CARRY a functional coding alteration in THIS target?" (gene x indication).
  Backed by `hcmi-genotype-matched-model-per-gene-v1` (HCMI-CMDC DR45 WXS aliquot-MAF join on top of the
  availability crosswalk; 12 indications + an `ALL` rollup). VERDICT-INERT translational context.
- **target-pdx-drug-response** (in-vivo tractability corroboration): "does the target's drug-response
  reproduce IN VIVO — do treatments naming it produce tumour regression in PDX population trials?"
  Backed by `pdxe-drug-response-per-gene-v1` (Novartis PDXE, Gao et al. 2015 Nat Med; the only large
  public in-vivo genotype -> drug-response resource). TARGET-grain (no per-indication split); a
  RESEARCH-ONLY source. VERDICT-INERT translational display facet.
- **organoid-crispr-dependency** (ex-vivo dependency reproduction): "does the target's dependency
  REPRODUCE EX VIVO in patient-derived 3D CRISPR organoid models — the ex-vivo complement of the PDX
  in-vivo leg?" Backed by `organoid-crispr-dependency-26q1-v1` (+ `-by-lineage`) — the DepMap 26Q1
  OrganoidGeneEffect Chronos run over 114 patient-derived organoid models (GI-dominated). BORROWED from
  the dependency axis (home skill: functional-requirement) and read here with a TRANSLATIONAL framing;
  the indication-matched `organoid_lineage_frac_dependent` is the most granular display facet, but it
  is display-only — the claim vector's ORGANOID tier keys the pan `organoid_dependency_class`, not the
  lineage-matched read. VERDICT-INERT.

## Still un-wired (honest coverage gaps)

- **Internal Takeda models registry** (PDX/organoid/GEMM) — not catalogued in data-catalog.
- **PD-assay catalog** — not wired.
- **Imaging-tracer catalog** — not wired.
- **Genotype-STRATIFIED PDX response** (do BRAF-MUTANT PDX respond to encorafenib?) — a downstream v2
  requiring the PDXE per-model genomics join; the current PDX card is a drug -> target rollup.

## How Claude invokes this skill

1. Extract `target` (HGNC symbol, uppercase) + `indication` (OncoTree code).
2. Pick a durable `out` directory (avoid `/tmp`).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/translational-readiness/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
   Optional OPT-IN lanes, both verdict-INERT sibling keys (the spine is byte-identical without them):
   `--synthesize` → `decision["llm_synthesis"]`, and `--literature` → `decision["literature_synthesis"]`
   (published-literature read per axis + agreement-vs-omics + omics-blind signals, through this
   skill's translational-readiness lens; `--literature-model <id>` overrides the Bedrock model). The two
   are INDEPENDENT — `--literature` alone gives the key with no narration; with both, the literature
   lane is attached first and fed to the narrator as a corroboration/contradiction input. If you did
   not pass `--literature`, `literature_synthesis` is simply ABSENT: the flag was not passed, the lane
   did not fail.
4. Read `<OUT_DIR>/decision.json`; present `model_availability_class` +
   `n_patient_derived_models` inline, and surface `partial_status_note` for the un-wired legs.
