# iDAS Strata Spec — SCLC (Small Cell Lung Cancer)

## Panel identity

| Field | Value |
|---|---|
| iDAS canonical code | `SCLC` |
| Display name | SCLC |
| Strategic bucket | Thoracic (with NSCLC, HNSC) |
| TCGA cohort mapping | **No TCGA-standard cohort** — iter-1 patient side is data-blocked |
| Adjunct patient cohorts | George 2015 (Nature 524:47), Rudin 2019, cBioPortal SCLC studies — **none ingested** |
| DepMap lineage | `Lung` (SCLC cell lines subset — filter by OncoTree `SCLC`) |
| CPTAC coverage | **None** — no SCLC patient cohort in CPTAC |
| GTEx normal | `Lung` |
| Adjacent-normal manifest | None (SCLC has no useful matched-adjacent in current sources) |

## iter-1 scope

- **DepMap cell-line side only** — patient-cohort SCLC strata are data-blocked pending ingestion (George 2015 or cBioPortal SCLC)
- **6 atomic strata** on cell-line side: 4 NAPY transcriptional subtypes + DLL3-high + placeholder for stage (deferred)
- **iter-1 SCLC rules should default cell-line evidence to "hypothesis-generating, requires patient-tissue confirmation"** per extrapolation discipline

## Atomic strata (cell-line side only for iter-1)

| stratum_id | derivation_source | data_source_of_record | expected_n_depmap (Lung-SCLC) | literature_anchor_pmid | iter1_status |
|---|---|---|---|---|---|
| `SCLC-A` (ASCL1-high) | `classifier_run` (ASCL1 RNA z-score) | DepMap expression | ~15 | 30297170 (Rudin NAPY 2019) | live (cell-line only) |
| `SCLC-N` (NEUROD1-high) | `classifier_run` (NEUROD1 RNA z-score) | DepMap expression | ~5 | 30297170 | live (cell-line only) |
| `SCLC-P` (POU2F3-high) | `classifier_run` (POU2F3 RNA z-score) | DepMap expression | ~5 | 30297170 | live (cell-line only) |
| `SCLC-Y` (YAP1-high / Inflamed) | `classifier_run` (YAP1 RNA z-score or immune-inflamed signature) | DepMap expression | ~3 | 30297170; 33077817 (Gay 2021) | live (cell-line only) |
| `DLL3_high` | `classifier_run` (RNA z-score threshold) | DepMap expression | ~20 (SCLC Lung lineage subset) | 32122759 (Rudin DLL3 review) | live (cell-line only) |
| `stage_limited` | `directly_tagged_clinical` | **patient cohort required** | (n/a for DepMap) | Veterans-Administration-staging | deferred |
| `stage_extensive` | `directly_tagged_clinical` | same | (n/a) | same | deferred |

## Composite iDAS strata (DRAFT — requires SCLC patient cohort + clinical-lead sign-off)

| iDAS composite | Constituent atomic strata | Rationale | iter1_status |
|---|---|---|---|
| `SCLC-A_extensive_1L` | `SCLC-A` × `stage_extensive` × 1L | dominant SCLC subtype × dominant clinical stage | draft — requires patient data + sign-off |
| `SCLC-P_DLL3-high` | `SCLC-P` × `DLL3_high` | DLL3 ADC/TCE opportunity concentrated in NE-low subtype | draft — requires sign-off |
| `SCLC-Y_IO-eligible` | `SCLC-Y` × IO-eligible | inflamed SCLC subtype — checkpoint-inhibitor window | draft — requires patient data + sign-off |

## SCLC patient-cohort ingestion prerequisites (iter-2 unblock)

For iter-2 SCLC to have patient-side strata, one of these must land:
- **George 2015** — Nature 524:47, ~110 SCLC tumors with mutation + expression
- **cBioPortal SCLC studies** — check `project_cbioportal_nongenie_survey.md` for SCLC entries
- **DepMap "Rudin SCLC" panel** — if available
- **Takeda-internal SCLC RWD** — if any exists

## Subgroup-n floor discipline

**All iter-1 SCLC strata are below TCGA n=30 floor because there is NO TCGA-SCLC cohort.** Cell-line strata (`SCLC-A/N/P/Y`, `DLL3_high`) are DepMap-only; subgroup_n floor for DepMap side varies but n≈3-15 per NAPY subtype is inherently limited by DepMap's small SCLC panel.

**Recommendation**: SCLC iter-1 rules emit `hypothesis_generating` flag; synthesis renders as low-weight signal. Patient-side confirmation gates promotion to `supportive`.

## Deferred to iter-2

- **SCLC patient cohort ingestion** (highest priority for iter-2)
- **NAPY on patient side** — requires patient RNA-seq + classifier
- **SCLC-I "Inflamed" as distinct subtype** (per Gay 2021 4-subtype framework; iter-1 collapses under SCLC-Y)
- **KEAP1/STK11 co-mutations** — LKB1 axis relevant to SCLC IO-response

## Open questions

1. Is SCLC patient-cohort ingestion a data-catalog Phase-1 dependency? Or does iter-1 SCLC land cell-line-only, gated on iter-2?
2. Should SCLC iter-1 rules use a `hypothesis_generating: true` flag, or emit `insufficient` for patient-tier fields? The rules-layer channel-precedence needs to distinguish these.
3. DLL3 stratum: is n=20 SCLC lines enough for a live claim, or is it also below-floor for DepMap-side stratum-n?
