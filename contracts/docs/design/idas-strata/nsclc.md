# iDAS Strata Spec — NSCLC (Non-Small Cell Lung Cancer)

## Panel identity

| Field | Value |
|---|---|
| iDAS canonical code | `NSCLC` |
| Display name | NSCLC |
| Strategic bucket | Thoracic (with SCLC, HNSC) |
| Composed of | LUAD (adenocarcinoma) + LUSC (squamous) + LCC (large-cell, no TCGA) |
| TCGA cohort mapping | TCGA-LUAD + TCGA-LUSC |
| DepMap lineage | `Lung` (spans NSCLC + SCLC cell lines; filter by OncoTree code for NSCLC-only) |
| CPTAC coverage | LUAD (`LUAD`), LUSC (`LSCC`) |
| GTEx normal | `Lung` |
| Adjacent-normal manifest | TCGA-LUAD/LUSC paired adjacent-normal via `gdc-pancohort-somatic-dr45-0` clinical |

## iter-1 scope

- **14 atomic strata**: 11 driver mutations × 3 histology axes; PD-L1 IHC deferred; TMB live
- **Composite iDAS strata**: 7 drafted speculatively (LOT × driver × histology) — **requires clinical-lead sign-off**
- **Deferred**: LCC (no TCGA cohort), PD-L1 IHC ingestion, RWD LOT source

## Atomic strata

| stratum_id | derivation_source | data_source_of_record | expected_n_patient (TCGA) | expected_n_depmap (Lung-NSCLC) | literature_anchor_pmid | iter1_status |
|---|---|---|---|---|---|---|
| `EGFR_mut_ex19del` | `maf_filter_per_rule` | `tcga-mc3-public-v0-2-8` + `gdc-pancohort-somatic-dr45-0` | ~35 (LUAD) | ~15 | 15118125 (Paez 2004) | live |
| `EGFR_mut_L858R` | `maf_filter_per_rule` | same | ~40 (LUAD) | ~10 | 15118125 | live |
| `EGFR_mut_ex20ins` | `maf_filter_per_rule` | same | ~10 (LUAD) | ~2 | 22178589 (Yasuda) | live |
| `KRAS_G12C` | `maf_filter_per_rule` | same | ~30 (LUAD) | ~10 | 24322666 (Ostrem) | live |
| `KRAS_G12D` | `maf_filter_per_rule` | same | ~15 (LUAD) | ~5 | 34544778 (Wang) | live |
| `ALK_fusion` | `directly_tagged_source_provided` | `gdc-pancohort-somatic-dr45-0` fusion column; DepMap `OmicsFusion*` | ~10 (LUAD) | ~5 | 17625570 (Soda) | live |
| `ROS1_fusion` | `directly_tagged_source_provided` | same | ~5 (LUAD) | ~2 | 22215748 (Bergethon) | live |
| `RET_fusion` | `directly_tagged_source_provided` | same | ~5 (LUAD) | ~2 | 22327622 (Kohno) | live |
| `BRAF_V600E` | `maf_filter_per_rule` | MC3 + GDC MAFs | ~5 (LUAD) | ~3 | 22833753 (Paik) | live |
| `MET_ex14` | `maf_filter_per_rule` (splice-site) | MC3 + GDC MAFs | ~10 (LUAD) | ~4 | 25971938 (Frampton) | live |
| `HER2_mut` | `maf_filter_per_rule` | MC3 + GDC MAFs | ~5 (LUAD) | ~2 | 15118073 (Stephens) | live |
| `histology_Adeno` | `directly_tagged_clinical` | TCGA-LUAD clinical | ~500 | ~60 | TCGA LUAD marker paper 2014 | live |
| `histology_SCC` | `directly_tagged_clinical` | TCGA-LUSC clinical | ~500 | ~40 | TCGA LUSC marker paper 2012 | live |
| `histology_LCC` | `directly_tagged_clinical` | **no TCGA cohort** — deferred | 0 | ~5 (DepMap Lung LCC) | (n/a) | deferred |
| `PD-L1_high` (≥50%) | `classifier_run` (IHC threshold) | requires IHC / RNA proxy; no cataloged manifest | (varies) | (n/a) | 27718847 (Reck) | deferred (needs IHC ingestion) |
| `TMB_high` (≥10 mut/Mb) | `directly_tagged_source_provided` | MC3 aggregate + TCGA-LUAD/LUSC clinical | ~100 combined | ~30 | 28777099 (Rizvi) | live |

## Composite iDAS strata (DRAFT — requires clinical-lead sign-off)

| iDAS composite | Constituent atomic strata | Rationale | iter1_status |
|---|---|---|---|
| `EGFR-mut_1L` | `EGFR_mut_ex19del ∪ EGFR_mut_L858R` × line-of-therapy=1L | osimertinib 1L SOC (FLAURA); target-eval must be TKI-aware | draft — requires sign-off |
| `EGFR-mut_TKI-resistant_2L+` | `EGFR_mut_*` × 2L+ | post-osimertinib resistance (T790M, MET-amp, HER3, C797S); highest whitespace | draft — requires sign-off |
| `KRAS-G12C_2L+` | `KRAS_G12C` × 2L+ | sotorasib/adagrasib label positions; resistance biology is 2L+ | draft — requires sign-off |
| `KRAS-G12D_1L` | `KRAS_G12D` × 1L | RMC-6236 (G12D pan-KRAS) landscape opening | draft — requires sign-off |
| `SCC_IO-refractory` | `histology_SCC` × IO-refractory (post-checkpoint) | LUSC checkpoint-inhibitor space post-KEYNOTE | draft — requires sign-off |
| `PD-L1_high_1L` | `PD-L1_high` × 1L | KEYNOTE-024 monotherapy positioning | draft — requires PD-L1 IHC + sign-off |
| `Adeno_driver-negative` | `histology_Adeno` × no driver mutation | ~30% of LUAD; unmet-need cohort for novel MoAs | draft — requires sign-off |

## Line-of-therapy definition

LOT axis is not native to TCGA — requires RWD source. Composite LOT strata resolve against Takeda RWD (Tempus / Flatiron) at Phase 2. TCGA-only NSCLC analyses default to indication-level.

## Subgroup-n floor discipline

Strata below n=30 on TCGA (`EGFR_mut_ex20ins`, `BRAF_V600E`, `HER2_mut`) automatic-insufficient for TCGA-side rule firing.

## Deferred to iter-2

- LCC on any patient side — no cataloged cohort
- PD-L1 IHC ingestion
- LOT × driver composite strata — pending clinical-lead sign-off + RWD source wiring

## Open questions

1. LCC deferral is correct given zero TCGA cohort — but should DepMap-side LCC still get a stratum (n≈5 lines)? Or is n=5 below the DepMap subgroup-n floor?
2. Which RWD source supplies LOT annotations?
3. Should `TMB_high` threshold be 10 mut/Mb (FDA label) or empirically-optimized per-cohort?
