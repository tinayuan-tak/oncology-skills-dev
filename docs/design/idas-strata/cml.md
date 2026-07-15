# iDAS Strata Design Note — Heme-CML (iter-1b, DEFERRED)

## Status

**DEFERRED to iter-1b.** This document is a design note capturing the
data-ingestion prerequisites and strata intent for CML, so the workstream
is scoped (not lost) and can resume once iter-1 solid + AML lands.

## Why deferred

Per Phase-0a heme survey (2026-07-14):

- **No TCGA-CML cohort** — CML is not a TCGA study code
- **No phase-annotated longitudinal patient cohort** in the current
  data-catalog — CML clinical practice requires chronic/accelerated/blast
  phase stratification; without a longitudinal cohort, phase-defined
  strata cannot be populated
- **No TKI-resistance annotation source** — T315I and BCR-ABL kinase
  domain mutation calls need a dedicated ingestion
- **DepMap CML lines are few** — K562 (canonical), KCL-22, KU812, MEG-01
  (bcr-abl+ megakaryoblastic), LAMA-84. Combined n ≈ 5-6 — below any
  reasonable subgroup-n floor for cell-line-only claims
- **CPTAC has no CML cohort** — CPTAC AML studies are FLT3-context,
  not CML; no CML proteomics in catalog
- **User-side intent confirmed** — `personal-notes/decisions/log.md:36-38`
  (Bin, 2026-06-09) names CML in the iDAS scope; deferral is a data-
  readiness call, not a strategic one

## Data-ingestion prerequisites for iter-1b

To bring CML into iter-1b, the following would need to land in
data-catalog BEFORE strata authoring:

1. **A CML patient cohort with molecular annotation** — candidates:
   - **cBioPortal CML studies** — check `cbioportal-genie-*` and non-GENIE
     public studies (per `project_cbioportal_nongenie_survey.md` — 413
     non-TCGA public studies enumerated; some may include CML)
   - **ICGC-CMLE** (International Cancer Genome Consortium CML-Epigenome)
     — check availability
   - **MSK-IMPACT CML subset** — MSK-IMPACT covers heme; CML samples
     may be extractable
   - **Blueprint Epigenome CML** — DNA methylation + gene expression;
     limited mutational data
   - **Direct pull from published Branford / Cortes datasets** —
     phase-annotated longitudinal cohorts published in the literature

2. **A TKI-resistance mutation manifest** — BCR-ABL kinase domain
   mutations (T315I, E255K/V, Y253H, F359V, etc.). Sources:
   - Published mutation-frequency papers with per-patient annotations
   - Sanger COSMIC entries filtered to BCR-ABL kinase domain
   - Any Takeda-internal TKI-resistance database (unknown if exists)

3. **A phase-annotation source** — chronic/accelerated/blast phase.
   Requires longitudinal patient cohort with phase tracking.

4. **DepMap Blood-Lymphoid subtype resolution** — verify which DepMap
   cell lines are labeled CML (vs generic Blood or Lymphoid) via
   `Model.csv` OncoTree assignments. May need `OmicsInferredMolecular
   Subtypes.csv` inspection.

## Intended atomic strata (for iter-1b, subject to data availability)

| stratum_id | derivation_source | data_source_needed | literature_anchor |
|---|---|---|---|
| `phase_chronic` | `directly_tagged_clinical` | CML patient cohort with phase annotation | 27337797 (Hochhaus review) |
| `phase_accelerated` | `directly_tagged_clinical` | same | 27337797 |
| `phase_blast` | `directly_tagged_clinical` | same | 27337797 |
| `BCR-ABL_T315I` | `maf_filter_per_rule` | TKI-resistance MAF/mutation source | 22186725 (ponatinib clinical) |
| `BCR-ABL_kinase-domain-mut_non-T315I` | `maf_filter_per_rule` | same | 22186725 |
| `TKI-resistant_multi-mutation` | `classifier_run` (mutation-combination logic) | same | 33326587 (asciminib STAMP paper) |
| `TKI-naive` | `directly_tagged_clinical` (negation) | longitudinal cohort | (n/a — reference class) |

## Intended composite iDAS strata (iter-1b, requires clinical-lead sign-off)

- `phase_chronic_TKI-first-line` — imatinib/dasatinib/nilotinib 1L
  frontline decisions
- `phase_chronic_TKI-2L+` — post-1L failure, options include ponatinib,
  asciminib
- `phase_accelerated_blast_R/R` — highest-unmet-need CML population,
  natural target for novel MoAs
- `T315I_asciminib-refractory` — narrow but critical rare-population
  cohort

## Stakeholder inputs needed

Before iter-1b lands:

1. **Bin Li** — CML iDAS-scope confirmation post-iter-1 delivery
2. **Clinical-lead for heme** — TBD; composite strata definitions
   require heme-oncologist review (Takeda internal or external
   consultant)
3. **Data-catalog owner (Corneliu?)** — assess feasibility of CML
   cohort ingestion; identify best available source

## Cross-reference

- Parent plan: `/home/sagemaker-user/.claude/plans/deep-foraging-thompson.md`
- Heme survey: findings archived in this session's Phase-0a Explore agent output
- User context: `personal-notes/decisions/log.md:36-38` (Bin 2026-06-09
  iDAS scope declaration)
- Data-source survey: `personal-notes/claude-memory-backup/project_cbioportal_nongenie_survey.md`
