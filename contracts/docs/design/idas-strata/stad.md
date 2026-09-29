# iDAS Strata Spec — STAD (Gastric Adenocarcinoma)

## Panel identity

| Field | Value |
|---|---|
| iDAS canonical code | `STAD` |
| Display name | Gastric Cancer |
| Strategic bucket | GI-upper (with ESCA, PAAD) |
| TCGA cohort mapping | TCGA-STAD |
| DepMap lineage | `Stomach` |
| CPTAC coverage | verify PDC — no confirmed STAD proteomics ingestion in current catalog |
| GTEx normal | `Stomach` |
| Adjacent-normal manifest | TCGA-STAD paired adjacent-normal via GDC clinical |

## iter-1 scope

- **6 atomic strata**: 4 TCGA marker-paper molecular subtypes (EBV/MSI/GS/CIN) + HER2-amp + PD-L1-CPS
- **Composite iDAS strata**: HER2+ × LOT drafted speculatively — **requires clinical-lead sign-off**
- **Deferred**: PD-L1 IHC ingestion (RNA proxy possible); site-specific strata (GEJ vs non-GEJ)

## Atomic strata

| stratum_id | derivation_source | data_source_of_record | expected_n_patient (TCGA-STAD) | expected_n_depmap (Stomach) | literature_anchor_pmid | iter1_status |
|---|---|---|---|---|---|---|
| `EBV_positive` | `directly_tagged_clinical` | `tcga-marker-papers-subtypes-2018/tcga_subtype_STAD.csv` (`Subtype_Selected: EBV`) | ~30 | 0 (rare in cell-line panels) | 25079317 (TCGA STAD marker paper) | live (patient); insufficient (DepMap) |
| `MSI_H` | `directly_tagged_clinical` (marker paper) OR `maf_filter_per_rule` (MC3 hypermutated) | `tcga-marker-papers-subtypes-2018` + MC3 | ~50 | ~5 (DepMap `OmicsInferredMolecularSubtypes` MSI flag) | 25079317 | live |
| `GS` (Genomically Stable) | `directly_tagged_clinical` | `tcga_subtype_STAD.csv` | ~50 | ~2 | 25079317 | live (patient); insufficient (DepMap) |
| `CIN` (Chromosomally Instable) | `directly_tagged_clinical` | `tcga_subtype_STAD.csv` | ~220 | ~25 | 25079317 | live |
| `HER2_amp` | `directly_tagged_source_provided` | `gdc-pancohort-somatic-dr45-0` copy-number OR TCGA amp calls | ~30 | ~5 | 20728210 (ToGA trial) | live |
| `PD-L1_CPS-high` | `classifier_run` (IHC or RNA proxy) | **IHC ingestion missing** — RNA proxy possible from TCGA RNA-seq | ~60 (est) | (n/a) | 32888399 (KEYNOTE-859) | deferred (needs IHC or validated proxy) |

## Composite iDAS strata (DRAFT — requires clinical-lead sign-off)

| iDAS composite | Constituent atomic strata | Rationale | iter1_status |
|---|---|---|---|
| `HER2+_1L` | `HER2_amp` × 1L | trastuzumab-deruxtecan / ToGA + KEYNOTE-811 SOC positioning | draft — requires sign-off |
| `MSI-H` | `MSI_H` × any-LOT | pembrolizumab pan-cancer MSI-H | draft — requires sign-off |
| `EBV+_IO-naive` | `EBV_positive` × IO-naive | EBV+ has distinct immune landscape; IO-first opportunity | draft — requires sign-off |
| `CIN_HER2-neg_2L+` | `CIN` × HER2-negative × 2L+ | largest unmet-need STAD subgroup | draft — requires sign-off |

## Subgroup-n floor discipline

Strata borderline / below n=30:
- `EBV_positive` (n≈30, borderline)
- `HER2_amp` on TCGA-STAD (n≈30, borderline; strategic-bucket cross-indication aggregation with ESCA-EAC HER2+ helps clear floor at bucket level)
- `PD-L1_CPS-high` — no data yet, insufficient by default

## Deferred to iter-2

- **CPTAC STAD proteomics** — verify PDC has a STAD cohort; if yes, ingest for protein-level strata
- **PD-L1 IHC** — same story as NSCLC; requires source manifest
- **Site-specific strata** (GEJ vs non-GEJ; upper/lower stomach) — clinical stratification but molecular overlap with existing 4-class

## Open questions

1. Does CPTAC PDC have a STAD cohort we can ingest?
2. Should HER2+ signal cross STAD ↔ ESCA-EAC ↔ Breast at strategic-bucket level (Thoracic doesn't include Breast, but HER2+ is a program-level concept)? Or is that a Phase-5 synthesis-layer concern?
3. RNA-proxy for PD-L1 — is there a validated signature? If yes, `PD-L1_CPS-high` could move to `live` iter-1.
