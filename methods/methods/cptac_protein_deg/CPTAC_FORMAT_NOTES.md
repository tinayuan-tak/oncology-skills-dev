# CPTAC-PDC data-format notes for PR 2 fresh-session pickup

**Status**: PR 2 (cptac_protein_deg) DEFERRED 2026-07-10. Env is ready
(pixi already has R + bioconductor). The `read.py` scaffold + card + rule
consumers are already in place from PR #4 earlier. What's needed: the
actual `derive.py` + R stages + tumor/normal labeling.

## Session lessons captured

The `.summary.tsv` file per-study contains **per-plex spectral counts +
peptide counts**, NOT per-sample abundance. This is easy to mistake for
a DEG-ready matrix because it has 168 cols × 10,000 genes — but the
cols are (spectral counts, distinct peptides, unshared peptides) × plexes,
not per-sample abundance.

The DEG-ready per-sample file is **`<study_name>.tmt10.tsv`** (or
`.tmt11.tsv` / `.itraq.tsv` depending on the TMT-plex generation used
by that study). Format:

```
Gene  <aliquot_uuid1>_D2 Log Ratio  <aliquot_uuid1>_D2 Unshared Log Ratio  ...
Mean  -0.079  -0.081  ...   # skip first ~3 rows (Mean/Median/StdDev)
Median  -0.075  ...
StdDev  ...
A1BG  0.234  0.221  ...      # actual gene rows start ~row 5
```

- ~10,500 gene rows per study
- ~1000-1500 columns = (1 gene col) + (2 metric cols) × (~500-750 aliquots)
- Values are log2 ratios (tumor / pool-reference), typical range -3..+3

## Per-aliquot tumor/normal labeling — the KEY GAP for v1

The tmt10.tsv aliquot UUIDs are consistent with the `sample.txt` file
in each Proteome folder. But **the tumor-vs-normal LABEL is NOT in
sample.txt** — sample.txt maps AnalyticalSample → TMT channel → aliquot
UUID, and the aliquot-UUID → tumor/normal assignment lives in the
per-study clinical XLSX files (e.g., `S039_BRCA_prospective_clinical_data_r2.xlsx`).

Three viable approaches for v1:

1. **Parse each clinical XLSX** — study-specific column names/schemas;
   ~1-2 hours per study of custom parsing.
2. **Use `MSstatsTMT` R package** (Bioconductor) — designed exactly for
   CPTAC TMT data; handles plex batch effects + tumor/normal contrast
   properly. Adds bioconductor-msstatstmt as pixi dep. ~30 min to wire.
3. **Use PDC GraphQL API** for aliquot annotations — the PDC API has a
   canonical `sample_type` field per aliquot. Query via
   `data-catalog/scripts/pull_pdc.py` (already exists per session
   context). ~1 hour.

**Recommended v1 approach**: Option 2 (MSstatsTMT) — designed for
this data, hides the batch-effect complexity, well-tested.

## The 10 canonical CPTAC discovery cohorts (PDC study IDs)

```
BRCA  → PDC000120 (CPTAC2 Prospective Breast BI)
COAD  → PDC000116 (CPTAC2 Prospective Colon PNNL) OR PDC000109 (VU)
OV    → PDC000110 (CPTAC2 Ovarian JHU)
CCRCC → PDC000127 (CPTAC3 Clear Cell RCC)
GBM   → PDC000204 (CPTAC3 Glioblastoma)
HNSCC → PDC000221 (CPTAC3 Head and Neck)
LUAD  → PDC000153 (CPTAC3 Lung Adenocarcinoma)
LSCC  → PDC000234 (CPTAC3 Lung Squamous Cell Carcinoma)
UCEC  → PDC000125 (CPTAC3 Uterine Corpus Endometrial)
PDAC  → PDC000270 (CPTAC3 Pancreatic Ductal Adenocarcinoma)
```

Each study has a Proteome/ subdirectory with:
- `.peptides.tsv` — per-peptide precursor areas (larger, not DEG-ready)
- `.tmt10.tsv` — per-gene per-aliquot log ratios (**DEG-ready substrate**)
- `.summary.tsv` — per-plex aggregated counts (NOT per-sample)
- `.sample.txt` — plex-to-channel-to-aliquot map
- `S###_<cohort>_clinical_data_*.xlsx` — clinical + tumor/normal labels

## v1 pipeline outline (fresh-session TODO)

```
methods/cptac_protein_deg/
  derive.py              — Python orchestrator, per-cohort loop
  steps/
    00_load_pdc.py       — read tmt10.tsv + sample.txt + clinical.xlsx
                           per PDC study; emit per-cohort rds
    01_limma_msstats.R   — MSstatsTMT::proteinSummarization +
                           MSstatsTMT::groupComparisonTMT (limma-eBayes-
                           trend under the hood, NO voom because
                           log-abundance not counts)
    02_write_parquet.R   — concat + arrow::write_parquet
```

Expected output parquet schema (already in derived manifest scaffold
from PR #4 planning):

```
cohort                              string   BRCA|CCRCC|COAD|GBM|HNSCC|LSCC|LUAD|OV|PDAC|UCEC
gene_symbol                         string
uniprot_ac                          string
protein_effect_size                 float64  limma logFC (tumor − normal, log2)
protein_p_value                     float64
protein_bh_q_value                  float64
protein_median_log2_tumor           float64
protein_median_log2_normal          float64
n_tumor_samples                     int32
n_normal_samples                    int32
n_proteins_tested_cohort            int32
protein_expression_class            string   strong_up | modest_up | strong_down | modest_down | ns
stat_test_used                      string   'msstatstmt_limma_ebayes_trend'
method_version                      string   '0.1.0'
```

## Biology validation gate (must pass before merge)

Well-characterized protein overexpression targets that MUST recover:

- **ERBB2 in BRCA**: logFC > 2, q<0.001 (HER2+ subset drives cohort mean)
- **MSLN in OV**: logFC > 3 (canonical mesothelin overexpression, ADC/TCE anchor)
- **FOLH1/PSMA in PDAC**: moderate up
- **MDM2** should track TP53-mut cases (positive in cohorts with TP53 mut)
- **MKI67** up in every cohort (proliferation universal)

If ERBB2 BRCA logFC < 1 OR MSLN OV logFC < 2, block PR.

## Framework skills impact when this lands

- `tumor-presence` skill (Phase A) gains dual-layer (RNA + protein)
- `surface-abundance-density` card (Phase F) becomes computable
- Framework skills state: 8/12 → 9/12 real data

## S3 layout reference

Source manifest: `data-catalog:manifests/sources/cptac-pdc-snapshot-2026-07-01.yaml`
Source S3: `s3://onc-compbio/data-catalog/sources/pdc/cptac-snapshot-2026-07-01/PDC######/Proteome/`
Target derived S3: `s3://onc-compbio/data-catalog/derived/cptac-protein-tumor-vs-normal-per-cohort-v1/`
Target derived manifest: `data-catalog:manifests/derived/cptac-protein-tumor-vs-normal-per-cohort-v1.yaml` (needs creation)
