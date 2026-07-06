# dge_deseq2 v2 — Four-Cell Sensitivity Consolidation

**Status:** DRAFT — awaiting scientific review + implementation kick-off
**Date:** 2026-07-06
**Author:** Ryan Abo (via Claude Code)
**Supersedes:** `methods/dge_deseq2/README.md` §"TODO (deep-research finding from wf_9cf5659f-2e0, 2026-06-15)"
**Retires:** `methods/dge_tcga_gtex_precompute/` (Python Welch-on-log2CPM)

---

## 1. Problem statement

The framework currently runs two independent DEG methods for tumor-vs-normal
selectivity:

| method | contrast | statistics | S3 output |
|---|---|---|---|
| `dge_deseq2` (R) | TCGA-tumor vs TCGA-adjacent | DESeq2 NB-GLM + apeglm shrinkage | `coadread-dge-df06320/…parquet` |
| `dge_tcga_gtex_precompute` (Py) | TCGA-tumor vs GTEx-normal | Welch's t on log2(CPM+1) | `coadread-dge-tumor-vs-gtex-v1/…parquet` |

Card v2.0.0 (`tumor-vs-normal-selectivity`) fans these into a
`selectivity_class` field by max log2FC across the two contrasts, thresholded
at 0.5 (modest) and 1.5 (strong).

**Three problems with this state:**

1. **Method inconsistency.** The two log2FC values are not on the same scale.
   DESeq2's apeglm shrinkage compresses low-count effect sizes and is
   normalized against DESeq2's size factors; Welch on log2CPM does not shrink
   and normalizes against a library-size CPM. A single threshold applied to
   both contrasts assigns different biological meanings to the same number
   depending on which method produced it.

2. **Neither comparator is clean.**
   - **Sorokin & Buzdin 2023** (PMC10448432): TCGA-adjacent-normal tissue
     carries early field-effect signatures — pre-neoplastic changes in
     morphologically normal margin — that inflate the "tumor is different"
     signal for a subset of genes (chronic inflammation, angiogenesis,
     immune-infiltration markers).
   - **Hui, Goh & colleagues 2024** (PMC11471903): including class covariates
     in ComBat when batch is confounded with biology (as in a TCGA + GTEx
     joint) inflates p-values by leaking biological signal into the batch
     estimate. But *omitting* batch correction leaves technical variation
     confounded with the tumor-vs-normal test.

   Result: **any single-comparator DEG is biased in a known direction**. The
   field-standard mitigation is not to pick one comparator, but to require
   agreement across a sensitivity grid.

3. **Two S3 layouts, two manifests, two producers to maintain.** Doubles the
   burden on downstream consumers (`_live_readers`, `read.py`, card renderers)
   and creates drift risk on every pipeline update.

## 2. Design — four-cell sensitivity

Per indication, the R pipeline emits **five** parquets on a single run:

| cell | comparator | ComBat-seq | log2FC column | interpretation |
|---|---|---|---|---|
| A | TCGA-adjacent-normal | off | `log2fc_A` | field-effect-inflated but single-source clean |
| B | TCGA-adjacent-normal | on (batch = TCGA plate) | `log2fc_B` | within-TCGA technical-batch removed |
| C | joint TCGA-tumor + GTEx-normal | off | `log2fc_C` | source contamination present (naive baseline) |
| D | joint TCGA-tumor + GTEx-normal | on (batch = source) | `log2fc_D` | empirical source-effect removal, biology preserved |

> **CORRECTION (2026-07-06, post data-inspection):** an earlier draft of this
> table proposed cell C as DESeq2 `~ source + group`. That design is
> **rank-deficient**: in a TCGA-tumor-vs-GTEx-normal contrast every tumor is
> TCGA and every normal is GTEx, so `source` is perfectly collinear with
> `group` and DESeq2 cannot estimate both coefficients. The real {with,
> without ComBat} axis for the joint regime is C (naive `~ group` on joint raw
> counts, source-contaminated) vs D (`ComBat_seq(batch=source, group=group)`
> then `~ group`). This is exactly the batch-biology confound Hui & Goh 2024
> describe — ComBat_seq's `group=` argument is what preserves the tumor-vs-
> normal signal while removing the source effect.

Plus:

| product | schema | purpose |
|---|---|---|
| `tumor_vs_adjacent.parquet` | one row per gene, columns from cell A | primary tumor-vs-adjacent contrast (backwards compatibility with the current v1 product) |
| `tumor_vs_gtex.parquet` | one row per gene, columns from cell C | primary tumor-vs-GTEx contrast (replaces the Python precompute output) |
| `sensitivity.parquet` | one row per gene; columns: `gene_symbol`, `log2fc_A..D`, `padj_A..D`, `is_sig_A..D`, `cells_supporting`, `direction_consensus`, `dominant_direction`, `sig_all_four` | discipline artefact — carries the concordance evidence card v3.0.0 will surface |

`cells_supporting` counts how many of the four cells report the gene as
`padj < 0.05` **in the same direction**. `direction_consensus` reports the
sign of `sign(log2fc_A) == sign(log2fc_B) == sign(log2fc_C) == sign(log2fc_D)`.
`dominant_direction` reports whichever sign majorities across A..D
(three-of-four sufficient), or `NA` when split 2-2. `sig_all_four` is the
gold-standard call: `padj<0.05` in the same direction across all four cells.

### 2.1 Design formulae

- Cell A: `counts` = recount3 TCGA tumor + recount3 TCGA adjacent-normal,
  raw. `design = ~ group`, no batch term.
- Cell B: `counts` = `ComBat_seq(TCGA tumor + adjacent, batch = TCGA-plate,
  group = group)`, then `design = ~ group` (technical batch already removed).
  TCGA plate is derived from `gdc_cases.tissue_source_site.code` +
  aliquot-plate in the recount3 metadata (25 TSS codes in COAD).
- Cell C: `counts` = joint recount3 TCGA-tumor + recount3 GTEx-normal, raw.
  `design = ~ group` (NAIVE — source contamination is knowingly present; this
  is the pessimistic baseline that a gene must survive *despite* the confound).
- Cell D: `counts` = `ComBat_seq(joint TCGA-tumor + GTEx-normal, batch =
  source, group = group)`, then `design = ~ group`. ComBat_seq's `group=`
  argument preserves the tumor-vs-normal contrast while removing the empirical
  TCGA-vs-GTEx source effect. This is the biology-preserving joint estimate.

**Alignment consistency (CRITICAL — corrected 2026-07-06):** ALL FOUR cells
load from **one** substrate: recount3 `tcga-gtex-2023-01-04` (monorail uniform
reprocess, Gencode v26/G026). recount3 carries TCGA-tumor, TCGA-adjacent-normal
(sample_type "Solid Tissue Normal"), and GTEx all uniformly aligned. Using
GDC-STAR for A/B and recount3 for C/D would confound *comparator* (adjacent vs
GTEx) with *aligner* (STAR vs monorail) — a third uncontrolled factor that
defeats the sensitivity logic. The single-substrate constraint is what makes
the A/B-vs-C/D disagreement interpretable as a pure comparator effect.

- `s3://onc-compbio/data-catalog/sources/recount3/tcga-gtex-2023-01-04/tcga/<STUDY>/…` (cells A/B/C tumor + A/B adjacent-normal)
- `s3://onc-compbio/data-catalog/sources/recount3/tcga-gtex-2023-01-04/gtex/<TISSUE>/…` (cells C/D normal)

**Consequence for validation:** cell A no longer byte-matches the legacy
GDC-STAR `coadread-dge-df06320` product (different aligner). The byte-identity
test is replaced by a **direction + rank concordance** check: cell A log2FC
should agree in sign with `coadread-dge-df06320` for the top-N-expressed genes
(Spearman ρ ≥ 0.9 expected), with magnitude differences attributable to
STAR-vs-monorail. The legacy GDC-STAR product is retained but marked as the
prior-generation tumor-vs-adjacent source.

**Adjacent-normal availability caveat:** recount3 TCGA adjacent-normal sample
counts are small for several indications (COAD has 41 Solid-Tissue-Normal vs
503 Primary Tumor). Cells A/B require ≥3 normals (DESeq2 minimum enforced in
`01_build_design.R`). Indications below that floor run cells C/D only, and
`cells_supporting` caps at 2 (mirrors the GTEx-unmapped HNSC case, opposite
axis).

## 3. Implementation

### 3.1 New files

- `methods/dge_deseq2/steps/00_load_recount3.R` — recount3 loader that returns
  a single .rds bundling all sample groups needed by the four cells: TCGA
  tumor, TCGA adjacent-normal (Solid Tissue Normal), and GTEx normal — each
  labelled with `group ∈ {tumor, normal}` and `source ∈ {TCGA, GTEx}` and
  `tcga_tss` (for cell B plate batch). Loads `gene_sums` matrices (genes ×
  samples, header row is the gene_id + sample UUIDs; `##`-prefixed comment
  lines skipped). Maps versioned Ensembl gene_id → HGNC via the same
  Ensembl-116 map the Python precompute uses.
- `methods/dge_deseq2/steps/06_four_cell_driver.R` — orchestrator: from the
  one loaded .rds, subsets to each cell's sample set, builds each cell's
  design + optional ComBat, runs DESeq2 four times, joins the four result
  tables on `gene_symbol`, computes `cells_supporting` / `dominant_direction`
  / `sig_all_four`, and writes `sensitivity.parquet` + the two primary
  contrast parquets.

### 3.2 Modified files

- `steps/run_pipeline.R` — add `--contrast` choice:
  `tumor_vs_adjacent | tumor_vs_gtex | four_cell_sensitivity`. For
  `four_cell_sensitivity`, dispatch to `00_load_recount3.R` →
  `06_four_cell_driver.R` (bypasses the linear 00→05 GDC chain).
- `steps/01_build_design.R` — no change needed (four-cell driver builds its
  own per-cell designs); existing `~ group` / `~ batch + group` paths are
  reused by the driver via a shared helper.
- `steps/02_combat_seq.R` — refactor the `ComBat_seq` call into a sourced
  helper `combat_correct(counts, batch, group)` so the driver can call it per
  cell without shelling out. Keep the standalone CLI for the legacy path.
- `steps/03_deseq2.R` — refactor the DESeq2 fit + apeglm shrink into a sourced
  helper `deseq2_fit(counts, coldata, design)` returning the tidy results
  frame. Keep the standalone CLI.
- `cli.py` — accept `--contrast four_cell_sensitivity`, wire through to
  `run_pipeline.R`.
- `read.py` — new `read_tumor_vs_normal_sensitivity(target, indication)`
  reading `sensitivity.parquet`; `read_tumor_vs_normal_selectivity` refactored
  to derive its composite from the sensitivity product instead of two v1
  parquets.

The GDC-STAR chain (00_load_counts.R → 05_provenance.R) is UNTOUCHED and
remains the `--contrast tumor_vs_adjacent` legacy path. The four-cell path is
additive; nothing about the existing COADREAD tumor-vs-adjacent product breaks.

### 3.3 Removed files

Deferred to Phase 3 (post-consolidation-validation) to avoid orphaning
`coadread-dge-tumor-vs-gtex-v1` before the R pipeline replicates its numbers.
See §5.

- `methods/dge_tcga_gtex_precompute/` — entire directory, retired.

### 3.4 New data-catalog manifest

`manifests/sources/recount3-tcga-gtex-2023-01-04.yaml` — currently the recount3
data on S3 is only referenced from Python constants. To satisfy
`00_load_counts.R`'s manifest-resolution contract (line 60-64), a source
manifest must exist.

## 4. Card + rules impact

Card `tumor-vs-normal-selectivity` bumps to **v3.0.0** with:

**New primary field:** `sensitivity_cells_supporting` (integer 0..4). Along
with `dominant_direction`, this becomes the trust anchor.

**Selectivity vocabulary refactored:**
- `strong_tumor_selective` = `cells_supporting == 4` AND `dominant_direction == +` AND `max_log2fc_across_cells >= 1.5`
- `modest_tumor_selective` = `cells_supporting >= 3` AND `dominant_direction == +` AND `max_log2fc_across_cells >= 0.5`
- `discordant_across_comparators` = `cells_supporting <= 2` AND cells with `padj<0.05` disagree in sign — NEW class, surfaces the interesting failure mode where field-effect vs population-normal call the gene oppositely
- `not_selective` = `cells_supporting >= 3` AND `dominant_direction == -`
- `not_informative` = `cells_supporting <= 1`
- `data_unavailable` = one or more cells could not compute (typically no GTEx mapping for the indication → cells C/D are NULL, indication runs A+B only)

**Interpretation rules bump from 76 → ~81.** Cells C/D unavailable is a
distinct state from cells A..D all supporting.

**Backwards compatibility:** cards persisted under v2.0.0 remain
readable; the read layer synthesizes a v2-compatible `selectivity_class` from
the new `cells_supporting` field for any legacy caller. Dashboard specs pin
`>=3.0.0,<4` after cutover.

## 5. Migration + retirement of `dge_tcga_gtex_precompute`

The Python precompute output (`coadread-dge-tumor-vs-gtex-v1/…parquet`) is a
DEPRECATED product effective when the four-cell v2 lands. Migration path:

1. Land v2 four-cell pipeline; run for COADREAD.
2. Byte-compare `cell C` (joint TCGA+GTEx, no ComBat) log2FC values against
   the Python precompute for the top-500 highest-expressed genes. Expect
   direction agreement 100%, magnitude Pearson r ≥ 0.85. Discrepancies at
   pseudogenes / low-count genes are expected (Welch vs NB-GLM); the sanity
   check is the biology-relevant subset.
3. Rewrite `_dispatch_tumor_vs_normal_selectivity` to read the new
   `sensitivity.parquet` instead of the two v1 parquets.
4. Mark `dge_tcga_gtex_precompute/` with a deprecation `README.md` note
   pointing to `dge_deseq2 --contrast four_cell_sensitivity`. Leave the code
   in place for one release cycle so any external caller has a redirect.
5. In the following release, delete `dge_tcga_gtex_precompute/` and its
   `coadread-dge-tumor-vs-gtex-v1` manifest (mark as `SUPERSEDED` in the
   manifest, don't delete the S3 object — provenance).

## 6. Batch scope

Post-validation, run four-cell pipeline for:

- **Indications with GTEx mapping** (18): COAD, READ, COADREAD, LUAD, LUSC,
  BRCA, PAAD/PDAC, SKCM, STAD, PRAD, OV, KIRC, GBM, LGG, BLCA, LIHC, CESC,
  ESCA.
- **HNSC** has no clean GTEx mapping → run cells A+B only (tumor-vs-adjacent
  only); `sensitivity.parquet` emits with cells C/D as NULL and
  `cells_supporting` capped at 2.

Per-indication compute estimate (from the current COADREAD run wall-clock):
each cell is ~5-15 min DESeq2 fit + a few min ComBat-seq. Four cells × 5-15
min = 20-60 min per indication. 18 indications × ~40 min mean = 12 hours total
if serial; ~2 hours with 6× parallelism. Feasible for an overnight batch.

## 7. Test plan

- **Unit:** `steps/00_load_counts_recount3.R` returns integer-count matrix
  keyed by gene_symbol with `source` and `group` columns populated correctly.
- **Byte-identity:** cell A output for COADREAD matches the existing
  `coadread-dge-df06320` parquet log2FC values within numerical noise (same
  pipeline, no design change).
- **Direction:** cell C output for COADREAD agrees in sign with Python
  precompute for the top-N-expressed protein-coding genes (see §5.2).
- **Canonical CRC markers:** MKI67, TOP2A, EPCAM, LGR5, MYC, CDX2 must
  produce `cells_supporting == 4` and `dominant_direction == +`;
  APC and BRAF may show discordance (that's a *feature* of the four-cell
  discipline — biology says APC is loss-of-function-mutated but not
  necessarily expression-downregulated).
- **Card v3.0.0 live-smoke:** render for KRAS-COADREAD, verify the new
  `sensitivity_cells_supporting` field lands in the summary JSON, and the
  3-panel figure Panel B (forest) shows four log2FC values instead of two.

## 8. Non-goals

- Not touching subgroup-stratified expression (`--stratify-by`) — that's a
  separate iter-1 stub.
- Not touching pathway-level DEG (GSEA/CAMERA). Gene-level only.
- Not migrating any other DEG-adjacent pipeline (protein DE, sc-RNA DE) —
  scope is bulk-RNA tumor-vs-normal only.

## 9. Open questions

1. **`sensitivity.parquet` schema versioning.** Should the schema declare
   itself `sensitivity_v1` in the parquet metadata so future cell additions
   (e.g., a fifth cell using cell-line-vs-primary correlation) don't break
   consumers? **Recommendation:** yes, embed `schema_version: "1"` in the
   parquet key-value metadata.

2. **Compute environment.** Pixi env not currently solved for R+DESeq2 on the
   SageMaker space (per today's `pixi run` attempt). Solving fresh will pull
   ~500 MB of Bioconductor packages. Do this once and cache in the shared EFS
   mount rather than the ephemeral home directory.

3. **Cross-cell shrinkage consistency.** DESeq2's apeglm shrinkage uses per-
   cell dispersion estimates, so log2FC magnitudes across cells are not
   strictly comparable. **Mitigation:** the `sensitivity.parquet` primary
   trust metric is `cells_supporting` (direction + significance), NOT
   log2FC-magnitude concordance. Magnitudes are secondary.

4. **HNSC and other GTEx-unmapped indications.** These run cells A+B only.
   Should the card render differently for these targets, or silently cap
   `cells_supporting` at 2? **Recommendation:** silently cap, but expose a
   `gtex_mapping_available: bool` field so the card renderer can surface
   the constraint in a caveat line.
