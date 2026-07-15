# Sample Annotation Plan — from Raw Sources to Resolver Rows

**Purpose**: For every stratum in every iDAS spec, name the concrete annotation
method that takes raw source data and produces a per-sample `(sample_id,
stratum_id, is_member, derivation_source, derivation_value)` row in the resolver
product. This closes Phase 0's design loop — strata specs describe WHAT to
annotate; this document describes HOW.

**Prerequisite reading**: `IDAS_SUBTYPE_PIPELINE.md` (master design; Scope +
signal channels + resolver product shape). Each stratum spec at
`idas-strata/{indication}.md`.

## The three annotation modalities

Every stratum in every iDAS spec falls into one of three annotation modalities.
This partition is not accidental — it comes from the `derivation_source` enum
in `schemas/subgroup_catalog.schema.json`.

### Modality A: Directly tagged (lookup + normalize)

**When to use**: Source data ships a per-sample subtype label already computed
by an authoritative source (TCGA marker paper, DepMap Omics-inferred, clinical
supplement).

**Algorithm**:
1. Read the source table (`tcga_subtype_CRC.csv`, `OmicsInferredMolecularSubtypes.csv`, etc.)
2. Normalize the sample-id column to the canonical ID (see per-source ID mapping below)
3. For each atomic stratum in the catalog, filter rows where the source column matches the stratum's expected value
4. Emit `is_member=true` for matches, `is_member=false` for evaluated-not-matching, `is_member=null` for evaluated-but-missing-value (blank source cell)
5. For samples not in the source table at all, do NOT emit a row (rules layer treats row-absent as `insufficient`)

**Assigner method**: `analysis-methods/methods/subgroup_assigner_directly_tagged/`
(scaffolded, needs wiring per Phase 2). Consumes:
- Subgroup catalog YAML (stratum id → source column value)
- Source manifest (which table + column to read)
- Sample-id normalization sidecar (canonical mapping)

**Strata that use this modality**:

| Stratum family | Source | Source table | Column |
|---|---|---|---|
| CRC CMS + MSI | TCGA marker paper | `tcga_subtype_CRC.csv` | `expression_subtype`, `MSI_status` |
| CRC hypermutated | TCGA marker paper | same | `hypermutated` |
| STAD 4-class (EBV/MSI/GS/CIN) | TCGA marker paper | `tcga_subtype_STAD.csv` | `Subtype_Selected` |
| HNSC 4-class (Atypical/Mesenchymal/Basal/Classical) | TCGA marker paper | `tcga_subtype_HNSC.csv` | `Subtype_Selected` |
| HNSC HPV-status | TCGA-HNSC clinical | GDC clinical supplement | HPV-status column |
| PAAD Moffitt basal/classical | TCGA marker paper | `tcga_subtype_PAAD.csv` | Moffitt column |
| NSCLC histology (Adeno/SCC) | TCGA clinical | GDC clinical | primary histology |
| HNSC anatomic site | TCGA-HNSC clinical | GDC clinical | anatomic site column |
| DepMap KRAS-G12C, MSI, EWSR1-FLI1 (cell-line side) | DepMap 26q1 | `OmicsInferredMolecularSubtypes.csv` | one row per Model, columns per subtype flag |
| DepMap OncoTree lineage | DepMap 26q1 | `Model.csv` | `OncotreeLineage`, `OncotreePrimaryDisease`, `OncotreeSubtype` |
| AML cytogenetic risk | TCGA-LAML + BeatAML clinical | clinical supplements | risk-group column |
| ALK/ROS1/RET fusions (patient side) | GDC pancohort somatic | `gdc-pancohort-somatic-dr45-0` fusion table | fusion partner columns |
| Thorsson immune C1-C6 | PanCanAtlas immune | `Scores_160_Signatures.tsv.gz` | immune subtype column |

### Modality B: MAF-filter-derived (predicate on mutation table)

**When to use**: Source data is a mutation table (MAF); the stratum is defined
by a per-sample filter — hotspot mutation, gene-level LoF, mutation burden.

**Algorithm**:
1. Load the source MAF (`tcga-mc3-public-v0-2-8`, `gdc-pancohort-somatic-dr45-0`, per-cohort MAFs like BeatAML/TARGET-AML)
2. For each atomic stratum with `derivation_source: maf_filter_per_rule`:
   - Apply the stratum's `filter_rule` (e.g. `{gene: KRAS, protein_change: p.G12C}` or `{gene: TP53, effect: [nonsense, frameshift, splice, missense-damaging]}`)
   - Aggregate to sample level (any-hit vs all-hit; specified in catalog)
3. Emit rows: `is_member=true` for samples matching filter; `is_member=false` for samples in the MAF cohort not matching; row-absent for samples not in MAF cohort

**Assigner method**: `analysis-methods/methods/subgroup_assigner_maf_filter/`
(scaffolded, needs wiring per Phase 2).

**Strata that use this modality**:

| Stratum family | Source MAF | Filter rule |
|---|---|---|
| NSCLC EGFR variants (ex19del, L858R, ex20ins) | MC3 + GDC | `gene=EGFR, protein_change IN [...]` |
| NSCLC KRAS-G12C, G12D | MC3 + GDC | `gene=KRAS, protein_change=p.G12C` |
| NSCLC BRAF-V600E | MC3 + GDC | `gene=BRAF, protein_change=p.V600E` |
| NSCLC MET-ex14 | MC3 + GDC | `gene=MET, effect=splice_site, position in exon 14 skip region` |
| NSCLC HER2-mut | MC3 + GDC | `gene=ERBB2, effect=missense OR indel` |
| CRC KRAS variants + BRAF-V600E | MC3 + GDC | same pattern |
| PAAD KRAS variants (G12D/V/R/WT) | MC3 + GDC | KRAS hotspots; WT is negation |
| STAD/ESCA/HNSC TP53-mut | MC3 + GDC | `gene=TP53, effect IN [nonsense, frameshift, splice, missense-damaging]` |
| HNSC PIK3CA-mut (helical vs kinase) | MC3 + GDC | `gene=PIK3CA, position IN [helical_hotspots \| kinase_hotspots]` |
| HNSC NOTCH1-mut (LoF pattern) | MC3 + GDC | `gene=NOTCH1, effect IN [nonsense, frameshift, splice]` |
| AML FLT3-ITD | **BeatAML + TCGA-LAML MAFs; ITD-aware caller required** | `gene=FLT3, mutation_type=ITD` — NOT recoverable from standard MC3 Mutect2 output |
| AML NPM1-mut | MC3 + BeatAML | `gene=NPM1, exon=12, effect=insertion` |
| AML IDH1/IDH2-mut | MC3 + BeatAML | R132 (IDH1), R140/R172 (IDH2) hotspots |
| AML TP53-mut | MC3 + BeatAML | same as solid-tumor rule |
| TMB-high (all indications) | Aggregate MAF | mut/Mb ≥ threshold |

**Note on FLT3-ITD**: MC3 Mutect2-based calls under-count ITD insertions. iter-1
FLT3-ITD strata may need a dedicated ITD-aware caller (Pindel, or the BeatAML
pre-computed ITD annotation column). Flagged as an open question in `aml.md`.

### Modality C: Classifier-derived (signature score from RNA)

**When to use**: Source data is RNA expression; stratum is defined by a
transcriptional signature (z-score threshold, published classifier, or single-
marker RNA level).

**Algorithm**:
1. Load per-sample RNA expression matrix (recount3 for TCGA; DepMap Expression for cell lines)
2. For each atomic stratum with `derivation_source: classifier_run`:
   - Apply the classifier — usually z-score of marker gene(s) with an absolute or relative threshold
3. Emit rows

**Assigner method**: **DOES NOT EXIST YET** — new
`analysis-methods/methods/subgroup_assigner_classifier/` scaffold needed in Phase 2.

**Strata that use this modality**:

| Stratum | Classifier | Source data |
|---|---|---|
| SCLC-A (ASCL1-high) | Z-score(ASCL1) ≥ threshold | DepMap Expression (cell lines) |
| SCLC-N (NEUROD1-high) | Z-score(NEUROD1) ≥ threshold | DepMap Expression |
| SCLC-P (POU2F3-high) | Z-score(POU2F3) ≥ threshold | DepMap Expression |
| SCLC-Y (YAP1-high or inflamed) | Z-score(YAP1) OR immune-signature | DepMap Expression |
| DLL3-high (SCLC context) | Z-score(DLL3) ≥ threshold | DepMap Expression |
| PD-L1 CPS-high (RNA proxy, deferred) | CD274 z-score + validated signature (TBD) | TCGA/CPTAC RNA |
| PDAC HRD-deficient (deferred) | HRD-signature composite score (LOH + LST + TAI) | TCGA copy-number + MAF |
| PAAD Moffitt on cell-lines (deferred) | Sadanandam or Moffitt classifier | DepMap Expression |
| CMS1-4 on TCGA (deferred) | Ellrott classifier | TCGA RNA |

**Design implications for Modality C**:
- **Threshold discipline**: signature-score thresholds need per-stratum calibration + documentation. Different thresholds per data source (DepMap cell lines vs TCGA patient tumors) — cell-line z-scores are not directly comparable to patient z-scores because reference cohorts differ
- **Assigner method signature**: `subgroup_assigner_classifier(catalog, expression_manifest, classifier_config) → subgroup_assignments.parquet`
- **Multi-class classifiers** (Moffitt, CMS, Bass, NAPY): a single classifier emits ONE label per sample; the assigner emits multiple `is_member` rows (one per class), where exactly one is `true` per sample

## Per-source sample-id normalization

Canonical sample-id conventions the resolver product uses:

| Source | Native ID column | Canonical `sample_id` | `patient_id` |
|---|---|---|---|
| TCGA (RNA-seq via recount3, MC3 MAF, marker paper, GDC clinical) | aliquot barcode (`TCGA-XX-XXXX-01A-11R-...`) | truncate to sample level `TCGA-XX-XXXX-01` | truncate to patient `TCGA-XX-XXXX` |
| DepMap 26q1 | `ModelID` (ACH-xxxxxx) | ModelID as-is | (n/a — no patient concept) |
| BeatAML1 (via GDC MAF) | `Aliquot ID` or `dbgap_subject_id` | dbgap_subject_id | dbgap_subject_id (same) |
| TARGET-AML (via GDC MAF) | `TARGET_USI` | TARGET_USI | TARGET_USI |
| GENIE public v19 | `SAMPLE_ID` | SAMPLE_ID as-is | `PATIENT_ID` from clinical |
| CPTAC (via PDC) | `case_submitter_id` + `aliquot_id` | aliquot_id | case_submitter_id |
| Tempus RWD | `emr_id` | emr_id as-is | emr_id (patient-level RWD) |
| Thorsson PanCanAtlas immune | TCGA barcode | join as TCGA | join as TCGA |
| GDC pancohort somatic | `Tumor_Sample_Barcode` (TCGA aliquot format) | TCGA sample-level | TCGA patient-level |

**Source_native_id column** — every resolver row also carries the original ID
before normalization, for audit trail (invariant from the target-id-resolver
memory: `pair-identifier-provider-invariant` — always preserve the source ID).

## Per-indication annotation matrix

Which annotation modalities each iDAS indication uses. Cell = `A|B|C` per
modality; blank = not applicable.

| iDAS | Directly tagged (A) | MAF-filter (B) | Classifier (C) |
|---|---|---|---|
| COADREAD | CMS, MSI-H, MSS, hypermutated, sidedness | KRAS_mut, KRAS_G12C, BRAF_V600E | (CMS on non-TCGA deferred iter-2) |
| NSCLC | histology, TMB, fusions (ALK/ROS1/RET) | EGFR ex19del/L858R/ex20ins, KRAS G12C/G12D, BRAF, MET-ex14, HER2 | PD-L1 RNA proxy (deferred) |
| SCLC | (patient data blocked — deferred) | (deferred until patient cohort ingested) | **NAPY (SCLC-A/N/P/Y), DLL3-high on DepMap** |
| HNSC | HPV-status, Bass 4-class, anatomic site | TP53, PIK3CA, CCND1-amp, NOTCH1, TMB | PD-L1 RNA proxy (deferred) |
| STAD | EBV, MSI-H, GS, CIN, HER2-amp | (none primary; TP53 secondary) | PD-L1 RNA proxy (deferred) |
| ESCA | histology (ESCC/EAC), HER2-amp | TP53 | (deferred SOX2/TP63 subtypes) |
| PAAD | Moffitt basal/classical | KRAS G12D/V/R/WT, TP53, BRCA1/2 (somatic) | HRD-signature (deferred); DDR-deficient (deferred) |
| AML | cytogenetic risk (clinical), CBF-AML (fusion; needs derived) | FLT3-ITD (with caller caveat), NPM1, IDH1, IDH2, TP53 | (CBF-AML fusion callable, needs Phase-2 derivation) |
| CML (iter-1b) | phase (needs longitudinal cohort ingestion) | BCR-ABL kinase-domain mutations (needs source) | (n/a) |

## Cell-line vs patient annotation discipline

**Cell-line annotations come from DepMap's `OmicsInferredMolecularSubtypes.csv`
where available.** For strata not covered by that CSV, cell-line annotation
uses the same MAF-filter or classifier rule as the patient side, applied to
DepMap's `OmicsSomaticMutations` (equivalent of MC3 for cell lines) or DepMap
Expression.

**Extrapolation discipline is critical here.** iter-1 rules should render
cell-line-derived subtype evidence as `hypothesis_generating` when there's no
paired patient-side confirmation for the same stratum. This is the
signal-vocab redesign's job — rules emitting on cell-line-only evidence carry
that flag; synthesis-layer down-weights.

## Assigner method wire-in plan (Phase 2)

Three assigner methods, each with a defined interface:

```python
# analysis-methods/methods/subgroup_assigner_directly_tagged/
def emit_assignments(
    catalog_path: str,             # subgroup catalog YAML
    source_manifest_id: str,       # source data manifest
    output_manifest_path: str,
    release_pin: str,
) -> None: ...

# analysis-methods/methods/subgroup_assigner_maf_filter/
def emit_assignments(
    catalog_path: str,
    maf_manifest_id: str,          # MC3, GDC pancohort, BeatAML, etc.
    output_manifest_path: str,
    release_pin: str,
) -> None: ...

# analysis-methods/methods/subgroup_assigner_classifier/  (NEW in Phase 2)
def emit_assignments(
    catalog_path: str,
    expression_manifest_id: str,   # recount3 for TCGA, DepMap Expression for cell lines
    classifier_config_path: str,   # per-classifier: thresholds, marker genes, published-classifier spec
    output_manifest_path: str,
    release_pin: str,
) -> None: ...
```

All three emit rows conforming to `schemas/subgroup_assignment.schema.json`,
into the tall parquet at `s3://onc-compbio/derived/subgroup-assignments/
{indication}/{data_source}/{release_pin}/assignments.parquet`.

## Rollup: how many derived-manifest files does Phase 2 produce?

Rough count assuming iter-1 = 8 indications × ~2 data sources × ~2 assigner
modalities per source-indication:

| Data source | Indications with coverage | Assigner modality mix |
|---|---|---|
| TCGA (marker paper + MC3) | COADREAD, NSCLC, HNSC, STAD, ESCA, PAAD, AML | A + B (both used) |
| DepMap 26q1 | COADREAD, NSCLC, SCLC, HNSC, STAD, ESCA, PAAD, AML | A (Model.csv + OmicsInferredMolecularSubtypes) + B (OmicsSomaticMutations) + C (NAPY/DLL3 on SCLC) |
| BeatAML/TARGET-AML (GDC MAF) | AML | B only |
| GENIE | (all — but not primary for iter-1) | B only |
| CPTAC (via PDC) | Coverage varies per indication | A only (subtype-associated protein signatures deferred) |

**Estimated iter-1 derived manifests**: ~20 shards (8 indications × 2-3 primary
data sources each). Manageable per data-catalog convention (one-branch-one-
manifest).

## Open questions

1. **`subgroup_assigner_classifier` scaffold** — not yet designed at method-scaffold level. Should Phase 2 include this method's scaffold work, or defer classifier strata (SCLC-NAPY, DLL3-high, PD-L1 proxy) to iter-1b?
2. **CBF-AML fusion derivation** — the aml.md spec flags this as deferred. Should Phase 2 include a fusion-caller run on TCGA-LAML RNA (STAR-Fusion or Arriba), or defer with a `deferred_derivation` flag on the CBF-AML stratum?
3. **DepMap `OmicsSomaticMutations` consumption** — no method today reads this file. Should it be a Phase-2 loader alongside `OmicsInferredMolecularSubtypes.csv`?
4. **Threshold-calibration discipline** for Modality C classifiers — cell-line z-score thresholds differ from patient z-score thresholds. How is this documented + validated?
5. **BeatAML expression ingestion** — currently only MAFs are in catalog; RNA-seq would enable RNA-classifier strata (FAB-like AML subtypes). Phase-1 dependency or iter-2 deferred?
