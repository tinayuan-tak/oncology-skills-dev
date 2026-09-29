# iDAS Strata Spec — PDAC (Pancreatic Ductal Adenocarcinoma)

## Panel identity

| Field | Value |
|---|---|
| Panel canonical code | `PDAC` |
| Member indication | PAAD (single-indication panel) |
| TCGA cohort mapping | PAAD → TCGA-PAAD |
| DepMap lineage | `Pancreas` |
| CPTAC coverage | PDAC (`PDAC` in CPTAC) |
| GTEx normal | `Pancreas` |
| Overlap membership | PAAD is also a member of the GI panel |

## iter-1 scope

- **8 atomic strata**: 3 KRAS variants + 4 DDR/co-mutation strata + 2 Moffitt expression subtypes
- **Composite iDAS strata**: 3 line-of-therapy × KRAS-status conjunctions — drafted speculatively, **requires clinical-lead sign-off**
- **Deferred**: Bailey subtype (2016) if not in marker-paper; PDAC RWD strata (Tempus PDAC — check if available)

## Atomic strata

| stratum_id | derivation_source | data_source_of_record | expected_n_patient (TCGA-PAAD) | expected_n_depmap (Pancreas) | literature_anchor_pmid | iter1_status |
|---|---|---|---|---|---|---|
| `KRAS_G12D` | `maf_filter_per_rule` | `tcga-mc3-public-v0-2-8` + `gdc-pancohort-somatic-dr45-0` | ~65 | ~15 | 27924024 (Bailey) | live |
| `KRAS_G12V` | `maf_filter_per_rule` | same | ~40 | ~10 | 27924024 | live |
| `KRAS_G12R` | `maf_filter_per_rule` | same | ~20 | ~5 | 27924024 | live |
| `KRAS_WT` | `maf_filter_per_rule` (negation of KRAS hotspots) | same | ~15 (~10%) | ~5 | 30202053 (Singhi review) | live |
| `TP53_mut` | `maf_filter_per_rule` | MC3 + GDC MAFs | ~130 (~72%) | ~50 | 24132290 (Waddell) | live |
| `BRCA1_mut` (germline OR somatic) | `maf_filter_per_rule` | MC3 + GDC MAFs; **germline gap** — TCGA germline not in catalog | ~5 somatic; germline TBD | ~2 | 25409174 (Kaufman POLO) | live (somatic) / deferred (germline) |
| `BRCA2_mut` (germline OR somatic) | `maf_filter_per_rule` | same | ~10 somatic; germline TBD | ~3 | 25409174 | live (somatic) / deferred (germline) |
| `DDR_deficient` | `classifier_run` (HRD-signature or BRCA/ATM/PALB2 mut union) | requires HRD-score derivation from MC3 + copy-number | ~20 | ~5 | 26187781 (Waddell HRD) | deferred (HRD classifier not wired) |
| `Moffitt_basal-like` | `directly_tagged_clinical` | `tcga-marker-papers-subtypes-2018/tcga_subtype_PAAD.csv` (Bailey/Moffitt) | ~40 | ~15 (per Sadanandam-adapted DepMap classification, if available) | 25706875 (Moffitt) | live (patient) / deferred (cell-line) |
| `Moffitt_classical` | `directly_tagged_clinical` | same | ~90 | ~25 | 25706875 | live (patient) / deferred (cell-line) |

**KRAS-WT gap**: while KRAS-WT PDAC is ~10% and clinically distinct, subtype-n on TCGA-PAAD is only ~15. Marks as `insufficient` under strict subgroup-n floor. Governance override possible if the target has strong biology in KRAS-WT lineage.

## Composite iDAS strata (DRAFT — requires clinical-lead sign-off)

| iDAS composite | Constituent atomic strata | Rationale | iter1_status |
|---|---|---|---|
| `KRAS-G12D_1L_metastatic` | `KRAS_G12D` × 1L × metastatic | RMC-6236 lead indication; adagrasib/sotorasib G12C is a small share of PDAC | draft — requires sign-off |
| `KRAS-G12D_adjuvant` | `KRAS_G12D` × adjuvant | mFOLFIRINOX-eligible adjuvant space; distinct MoA opportunity | draft — requires sign-off |
| `DDR-deficient_maintenance` | `DDR_deficient` × maintenance-after-platinum | POLO trial paradigm; PARPi maintenance | draft — requires HRD classifier + sign-off |
| `Moffitt-basal_chemo-refractory` | `Moffitt_basal-like` × chemo-refractory | basal-like has worse prognosis; unmet-need cohort for novel MoAs | draft — requires sign-off |

## Line-of-therapy definition

Same as Lung spec: LOT axis is not native to TCGA (single-timepoint); requires Tempus / Flatiron RWD. Placeholder composite strata resolve against RWD at Phase 2. TCGA-only PDAC analyses default to indication-level.

## Subgroup-n floor discipline

Same rule as Lung. Strata with expected n < 30 on TCGA (`KRAS_WT`, `BRCA1_mut` somatic, `KRAS_G12R`) marked automatic-insufficient. `Moffitt_basal-like` at n≈40 clears the floor.

## Deferred to iter-2

- **Germline BRCA1/2 ingestion** — TCGA germline data (dbGaP-restricted or PanCanAtlas germline supplement) not in catalog
- **HRD-classifier method** — HRD-signature (LOH + LST + TAI) or Myriad-equivalent scoring not wired
- **DepMap Moffitt classifier** — DepMap Pancreas cell lines don't have Moffitt basal/classical assignments; requires Sadanandam-adapted or Moffitt-signature classifier
- **Bailey 4-subtype (2016)** — Squamous / Immunogenic / Pancreatic Progenitor / Aberrantly Differentiated Endocrine Exocrine (ADEX). Check if `tcga_subtype_PAAD.csv` marker-paper file carries Bailey labels; if yes, add strata; if no, defer to iter-2 classifier
- **Tempus PDAC RWD** — no `tempus-pdac-*` manifest in catalog yet (Tempus CRC is the only Tempus ingestion). Bin Li owes PDAC iDAS per personal-notes `implementation-runbook.md:377`

## Open questions

1. Does `tcga_subtype_PAAD.csv` marker-paper file carry Bailey subtypes (iCluster-derived 4 groups), or only Moffitt basal/classical? Read the file in Phase 1 authoring.
2. Should germline BRCA1/2 ingestion be a Phase-1 dependency for PDAC, or defer? Impacts DDR-deficient stratum readiness.
3. Cell-line Moffitt assignment: is there a published DepMap-Pancreas classifier? If no, iter-1 keeps `Moffitt_*` strata as patient-only.
4. Tempus PDAC ingestion — is this a data-catalog Phase-1 dependency, or does PDAC iter-1 land TCGA/DepMap-only?
