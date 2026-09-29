# iDAS Strata Spec — HNSC (Head and Neck Squamous Cell Carcinoma)

## Panel identity

| Field | Value |
|---|---|
| iDAS canonical code | `HNSC` |
| Display name | Head & Neck Cancer |
| Strategic bucket | Thoracic (with NSCLC, SCLC) — per user 2026-07-14 iDAS grouping |
| TCGA cohort mapping | TCGA-HNSC (~500 patients) |
| DepMap lineage | `Head_and_Neck` |
| CPTAC coverage | HNSC (`HNSCC` in CPTAC) |
| GTEx normal | (no exact match; use `Skin - Sun Exposed`/`Minor Salivary Gland` as best-available; verify at Phase 1) |
| Adjacent-normal manifest | TCGA-HNSC paired adjacent-normal via GDC clinical |

## iter-1 scope

- **10 atomic strata**: 1 HPV-status axis (dominant biological + treatment discriminator), 4 mutation strata, 4 molecular subtypes (Bass 2015), 1 site-anatomic (oropharyngeal — HPV-associated site)
- **Composite iDAS strata**: 5 drafted speculatively — **requires clinical-lead sign-off**
- **Deferred**: PD-L1 CPS ingestion; TMB-defined checkpoint-eligible strata beyond simple mutation count

## Atomic strata

| stratum_id | derivation_source | data_source_of_record | expected_n_patient (TCGA-HNSC) | expected_n_depmap (Head_and_Neck) | literature_anchor_pmid | iter1_status |
|---|---|---|---|---|---|---|
| `HPV_positive` | `directly_tagged_clinical` | TCGA-HNSC clinical (HPV-status column) | ~75 (~15% of HNSC; enriched in oropharyngeal) | ~5 (HPV+ cell lines rare) | 25631445 (Bass HNSC marker) | live |
| `HPV_negative` | `directly_tagged_clinical` | TCGA-HNSC clinical (negation) | ~425 | ~40 | 25631445 | live |
| `TP53_mut` | `maf_filter_per_rule` | `tcga-mc3-public-v0-2-8` + `gdc-pancohort-somatic-dr45-0` | ~350 (~72% overall; ~85% HPV-neg, near-zero HPV+) | ~30 | 25631445 | live |
| `PIK3CA_mut` | `maf_filter_per_rule` | MC3 + GDC MAFs | ~90 (~18%; enriched in HPV+ helical-domain vs HPV-neg kinase-domain) | ~10 | 25631445 | live |
| `CCND1_amp` | `directly_tagged_source_provided` | TCGA amp calls | ~150 (~30%; HPV-negative-enriched) | ~15 | 25631445 | live |
| `NOTCH1_mut` | `maf_filter_per_rule` | MC3 + GDC MAFs | ~90 (~18%; squamous-associated LOF pattern) | ~10 | 21798897 (Stransky HNSC exome) | live |
| `subtype_atypical` | `directly_tagged_clinical` | `tcga-marker-papers-subtypes-2018/tcga_subtype_HNSC.csv` (`Subtype_Selected: Atypical`) | ~120 (HPV-enriched) | ~10 | 25631445 (Bass 2015) | live |
| `subtype_mesenchymal` | `directly_tagged_clinical` | same | ~90 | ~8 | 25631445 | live |
| `subtype_basal` | `directly_tagged_clinical` | same | ~90 | ~10 | 25631445 | live |
| `subtype_classical` | `directly_tagged_clinical` | same | ~110 | ~12 | 25631445 | live |
| `site_oropharyngeal` | `directly_tagged_clinical` | TCGA-HNSC clinical (anatomic-site field) | ~80 (HPV+ concentrated here) | (varies) | 20530316 (Ang HPV-oropharynx) | live |
| `site_oral_cavity` | `directly_tagged_clinical` | same | ~300 | (varies) | 25631445 | live |
| `site_larynx` | `directly_tagged_clinical` | same | ~110 | (varies) | 25631445 | live |
| `PD-L1_CPS-high` | `classifier_run` (IHC or RNA proxy) | **IHC ingestion missing** | (varies) | (n/a) | 30412714 (KEYNOTE-048) | deferred (needs IHC) |
| `TMB_high` (≥10 mut/Mb) | `directly_tagged_source_provided` | MC3 aggregate | ~70 | ~15 | 30918912 (Rizvi pan-cancer) | live |

## Composite iDAS strata (DRAFT — requires clinical-lead sign-off)

| iDAS composite | Constituent atomic strata | Rationale | iter1_status |
|---|---|---|---|
| `HPV+_1L` | `HPV_positive` × 1L | de-escalation-eligible cohort; distinct treatment paradigm (RTOG 1016) | draft — requires sign-off |
| `HPV-_TP53-mut_1L` | `HPV_negative` × `TP53_mut` × 1L | dominant HPV-negative biology; ~85% of HPV-neg HNSC | draft — requires sign-off |
| `Recurrent-Metastatic_IO-eligible` | R/M × any-atomic | KEYNOTE-048 pembro±chemo landscape | draft — requires sign-off |
| `PIK3CA-mut_HPV+_helical` | `PIK3CA_mut` × `HPV_positive` × E542/E545/Q546 helical hotspots | HPV+ has distinct PIK3CA hotspot enrichment vs HPV-neg | draft — requires sign-off |
| `Basal-classical_HPV-_platinum-refractory` | (`subtype_basal ∪ subtype_classical`) × `HPV_negative` × platinum-refractory | high-unmet-need HPV-neg cohort | draft — requires sign-off |

## Cross-iDAS notes

**HNSC-SCC biology overlaps ESCC** (both are aerodigestive squamous carcinomas). Strategic-bucket queries could benefit from cross-iDAS aggregation for squamous-shared strata (TP53-mut, TP63, SOX2, NOTCH). Deferred to synthesis-layer.

**HPV-positive HNSC** clusters distinctly from HPV-negative — different mutation landscape, different treatment paradigm, different prognosis. The HPV axis is the single most important stratifier and should be rule-schema-mandatory-annotated for HNSC subtype rules.

## Subgroup-n floor discipline

Strata borderline / below n=30:
- `HPV_positive` on TCGA (n≈75, clears) but sub-strata within HPV+ often below floor
- Bass 4-class subtypes at n≈90-120 clear floor
- Anatomic-site strata all clear except potentially rare sites

## Deferred to iter-2

- **PD-L1 CPS IHC ingestion** — same story as NSCLC/STAD; requires source manifest
- **Salivary-gland tumors** — biologically distinct from HNSC-squamous; not in TCGA-HNSC
- **Nasopharyngeal carcinoma (NPC)** — separate cohort (TCGA-doesn't-cover); EBV-driven biology
- **CPTAC HNSCC proteomics** — is ingested per `cptac-pdc-snapshot-2026-07-01`; wire in Phase 2 for protein strata

## Open questions

1. Strategic-bucket placement: Thoracic (per your grouping) — confirm this is stakeholder-preferred. Some frameworks put HNSC in its own "Head & Neck" bucket alongside skin-SCC or salivary; Thoracic groups by shared squamous biology + checkpoint-inhibitor landscape.
2. Should HPV-status be a REQUIRED annotation on every HNSC subtype rule? The user's plan-level rigor discipline mandates `subtype_defining_data`; HPV-status could similarly be mandated at rule-schema level for HNSC context.
3. HNSC-SCC ↔ ESCC ↔ LUSC squamous cross-panel aggregation — is this a Phase-5 synthesis-layer concern, or should the strategic-bucket vocabulary encode this?
4. NPC (nasopharyngeal) inclusion — clinically HNSC-adjacent, molecularly distinct (EBV-driven). Explicit exclusion for iter-1?
