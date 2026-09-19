# 2026-09 — TCGA DGE "sensitivity" cross-cohort reimplementation

**Status:** in progress (Stage 0). Approved plan: `piped-whistling-conway`.
**Design reference:** [`../../DESIGN_v2_four_cell_consolidation.md`](../../DESIGN_v2_four_cell_consolidation.md).
**Characterization spec:** `data-catalog/specs/dataset-characterization-2026-Q3.md`.

## The question

The fused `*-dge-tumor-vs-normal-sensitivity-v1` family computes three live cells:

- **A** = TCGA tumor vs TCGA adjacent-normal (raw, `~ group`) — within-cohort, confound-free.
- **B** = same samples, ComBat_seq(batch = tissue-source-site) then `~ group` — a within-TCGA
  robustness re-run of A (not independent).
- **C** = TCGA tumor vs GTEx normal (raw joint `~ group`) — **naive, not batch-corrected**.

Cell **D** (cross-cohort ComBat → naive DE) was built and **retired**: it collapsed biology
(mean|log2FC| ~0.05 vs 1.05–1.40).

**Cell C is cross-cohort confounded.** Every tumor is TCGA and every normal is GTEx, so batch is
fully confounded with condition (non-identifiable). The QC below quantifies the damage.

## What the QC found (motivating evidence)

Run over the shipped v1 products (`scripts/qc.py`, `scripts/concordance_all.py`; outputs in
[`outputs/`](outputs/)):

- Cell C **inflates significance ~28 points** vs within-TCGA cell A (median sig_C ~85% vs sig_A ~57%).
- **~30% sign-flip** among genes significant in either arm; median A-vs-C Pearson only **~0.63**
  (paad 0.14, prad 0.40, stad 0.45, cesc 0.46 — the confound is worst where adjacent-normal is scarce).
- The fused product **drops `baseMean`**, so MA plots can't be reconstructed (a diagnosability gap).
- 8 products silently degrade to a single comparator; **7 are GTEx-only** (no within-TCGA anchor):
  acc, lgg, ov, sclc, skcm, tgct, ucs.

## Decisions (this arc)

1. **Within-TCGA cell A is the primary verdict-bearing signal** where it exists.
2. **No Welch's test anywhere** — every contrast is a count-based NB-GLM (DESeq2). The prior Welch
   products (OmicSoft-style normalized comparisons) are dropped, not ported.
3. **Cross-cohort cell C is corrected count-based:** RUVg-as-covariate in a single GLM (`~ W_k + group`),
   *not* the two-step ComBat→naive-DE that inflates confidence (Nygaard 2016). Shipped additively as
   cell **Cr** (`log2fc_Cr` / `padj_Cr` / `baseMean_Cr`).
4. **RIN / ischemic time evaluated as measured covariates.** They are the *mechanism* of the
   post-mortem confound and already sit in the recount3 GTEx metadata file the loader downloads
   (`gtex.gtex.<TISSUE>.MD.gz`, currently only `external_id` is kept). A symmetry probe decides whether
   they enter the design (present for both cohorts) or stay diagnostic-only (GTEx-only → confounded).
5. **Publication-native normals do not exist** for the GTEx-only cohorts — verified: SCLC/George is
   81 tumors / 0 normals (raw counts EGA-locked); the 6 TCGA GTEx-only cohorts never had adjacent
   normal collected. GTEx-lung stays the only fallback normal (already tissue-matched via
   `GTEX_TISSUE_BY_STUDY`).
6. **GTEx-only verdict policy and any substrate swap are DEFERRED** — the calibration study
   (`ruvg_calibration.py`, added in Stage 1) generates the evidence; it does not decide here.

## Scripts

| script | what it does | inputs |
|---|---|---|
| `scripts/qc.py` | Per-product volcano + MA + p-distribution panels; within-product A-vs-C concordance scatter for brca/paad. | live S3 (`AWS_PROFILE=cbg`) |
| `scripts/concordance_all.py` | Panel-wide A-vs-C concordance for every fused product with both arms live (Pearson, sign-flip, sig-fraction, median\|lfc\|). | live S3 + data-catalog manifests |
| `scripts/ruvg_calibration.py` | *(Stage 1)* substrate × method matrix (naive-C vs RUVg-Cr vs RUVg+RIN-Cr; recount3 vs Xena/Toil) vs the cell-A anchor → `outputs/calibration_report.md`. | live S3 + R pipeline |

### Running

```bash
# credentials: SageMaker container creds outrank AWS_PROFILE, so drop them (the scripts do this too)
env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
    python scripts/concordance_all.py           # writes outputs/concordance_all.json
env -u AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_PROFILE=cbg \
    python scripts/qc.py                          # writes outputs/summary.json + outputs/plots/*.png
```

Override the output dir with `DGE_QC_OUT=/some/dir` and the data-catalog clone with
`DATA_CATALOG_ROOT=/path/to/rnd-computational-biology-oncology-data-catalog`.

## Outputs (committed)

- [`outputs/summary.json`](outputs/summary.json) — per-product volcano/MA/p-dist summary from `qc.py`.
- [`outputs/concordance_all.json`](outputs/concordance_all.json) — panel-wide A-vs-C concordance table.
- `outputs/plots/*.png`, `outputs/*.parquet` — regenerated, **gitignored** (see `.gitignore`).
