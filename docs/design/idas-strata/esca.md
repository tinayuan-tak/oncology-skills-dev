# iDAS Strata Spec — ESCA (Esophageal Cancer)

## Panel identity

| Field | Value |
|---|---|
| iDAS canonical code | `ESCA` |
| Display name | Esophageal Cancer |
| Strategic bucket | GI-upper (with STAD, PAAD) |
| TCGA cohort mapping | TCGA-ESCA (contains both ESCC and EAC) |
| DepMap lineage | `Esophagus/Stomach` (DepMap groups these; filter by OncoTree for ESCA-only) |
| CPTAC coverage | **None** — no ESCA CPTAC cohort |
| GTEx normal | `Esophagus` |
| Adjacent-normal manifest | TCGA-ESCA paired adjacent-normal via GDC clinical |

## iter-1 scope

- **4 atomic strata**: 2 histology axes (ESCC squamous vs EAC adenocarcinoma) + HER2-amp (EAC context) + TP53-mut
- **Note**: ESCC and EAC are biologically distinct — ESCC clusters with HNSC-SCC, EAC clusters with STAD-CIN. iter-1 keeps them as one iDAS but rules-layer distinguishes via histology field
- **Composite iDAS strata**: 2 drafted speculatively — **requires clinical-lead sign-off**
- **Deferred**: ESCC-specific molecular subtypes (SOX2-amp, TP63-driven); EAC-specific molecular subtypes (MDM2/CCNE1 amp)

## Atomic strata

| stratum_id | derivation_source | data_source_of_record | expected_n_patient (TCGA-ESCA) | expected_n_depmap (Esophagus) | literature_anchor_pmid | iter1_status |
|---|---|---|---|---|---|---|
| `histology_ESCC` (squamous) | `directly_tagged_clinical` | TCGA-ESCA clinical | ~90 | ~15 | 28052061 (TCGA ESCA marker) | live |
| `histology_EAC` (adenocarcinoma) | `directly_tagged_clinical` | TCGA-ESCA clinical | ~90 | ~10 | 28052061 | live |
| `HER2_amp` (EAC-enriched) | `directly_tagged_source_provided` | TCGA amp calls (or copy-number derived) | ~15 (EAC) | ~2 | ToGA extended to ESCA | live (borderline n) |
| `TP53_mut` (near-universal in ESCC) | `maf_filter_per_rule` | MC3 + GDC MAFs | ~150 (~85% of ESCA) | ~20 | 28052061 | live |

## Composite iDAS strata (DRAFT — requires clinical-lead sign-off)

| iDAS composite | Constituent atomic strata | Rationale | iter1_status |
|---|---|---|---|
| `EAC_HER2+_1L` | `histology_EAC` × `HER2_amp` × 1L | HER2+ upper-GI expansion beyond STAD | draft — requires sign-off |
| `ESCC_1L_platinum` | `histology_ESCC` × 1L × platinum-eligible | ESCC-specific therapeutic development track | draft — requires sign-off |

## Subgroup-n floor discipline

Strata below n=30 on TCGA:
- `HER2_amp` on EAC (n≈15) — insufficient at ESCA-level; may clear at strategic-bucket level if aggregated with STAD-HER2-amp
- ESCC-specific sub-strata (SOX2-amp, TP63) — deferred, but if authored, likely below floor

## Deferred to iter-2

- **ESCC molecular subtypes** (SOX2-amp, TP63-driven, CDKN2A) — clusters with HNSC-SCC biology
- **EAC molecular subtypes** (MDM2/CCNE1 amp) — clusters with STAD-CIN biology
- **Site-specific ESCA** (upper vs middle vs lower esophagus; GEJ)
- **CPTAC ESCA proteomics** — no cohort exists in PDC

## Cross-iDAS notes

- **ESCC biology overlaps HNSC** — strategic-bucket queries could benefit from cross-iDAS aggregation (ESCC + HNSC squamous). Deferred to synthesis-layer.
- **EAC biology overlaps STAD-CIN** — same story. HER2+ upper-GI cross-iDAS aggregation is a real clinical concept.

## Open questions

1. Should ESCC and EAC be split into TWO iDAS entries (`ESCC`, `EAC`) rather than one ESCA? Biology arguments favor split; TCGA cohort grouping and strategic-bucket parsimony favor keeping unified.
2. If HER2+ strategic-bucket aggregation happens at synthesis-layer, does ESCA's HER2_amp (n≈15) contribute even though below its own iDAS floor? Design decision for Phase 5.
