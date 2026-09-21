# 2026-09 — TCGA DGE "sensitivity" cross-cohort reimplementation

**Status:** Stage 1 calibration COMPLETE — **cell Cr failed the sign-off gate (NEGATIVE)**.
Approved plan: `piped-whistling-conway`.
**Design reference:** [`../../DESIGN_v2_four_cell_consolidation.md`](../../DESIGN_v2_four_cell_consolidation.md).
**Characterization spec:** `data-catalog/specs/dataset-characterization-2026-Q3.md`.

## Result — cell Cr NEGATIVE (do not use as a verdict input) · 2026-09-20

RUVg-in-GLM does **not** make the cross-cohort TCGA-vs-GTEx contrast trustworthy. A four-lens
independent review + an authorized **6-anchor recount3 re-run** (brca/kirc/luad/lusc/prad/coad)
with a rebuilt, CI-bearing metric are unanimous: the residual false-positive rate against the
confound-free within-TCGA anchor stays **0.35–0.47 on every anchor** (RUVg only partially trims
naive-C's inflation), and its effect on sign/effect concordance is cohort-dependent, never
converging on the anchor — the signature of the structural non-identifiability (cohort aliased
to `group`). See the verdict + numbers in [`outputs/calibration_report.md`](outputs/calibration_report.md)
and the rebuilt-metric panel in [`outputs/multi_anchor/multi_anchor_calibration.md`](outputs/multi_anchor/multi_anchor_calibration.md).

**Disposition (user sign-off):** ship the anchor-independent v2 wins (baseMean carry-through,
apeglm s-values, comparator-family de-dup, no-Welch); ship **Cr diagnostic-only** with a
negative-calibration flag (never feeds the classifier/ranker); classifier stays on A + naive C;
do **not** extend RUVg-Cr to the 7 GTEx-only cohorts (unsupportable, not merely deferred).

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
4. **RIN / ischemic time are DIAGNOSTIC-ONLY — symmetry probe resolved GTEx-only (2026-09-20).**
   They are the *mechanism* of the post-mortem confound and sit in the recount3 GTEx metadata file the
   loader downloads (`gtex.gtex.<TISSUE>.MD.gz`, currently only `external_id` is kept). The Stage-1
   symmetry probe ([`outputs/rin_symmetry_probe.json`](outputs/rin_symmetry_probe.json)) checked whether
   the TCGA side carries a comparable field: **GTEx `SMRIN`/`SMTSISCH` are 100% populated** (brca 482/482,
   paad 360/360) but the **TCGA recount3 metadata has no RNA-integrity field at all** — only analyte-level
   `a260_a280_ratio` (a spectrophotometric *purity* ratio, not strand integrity, and absent from GTEx).
   So RIN is GTEx-only → perfectly collinear with `group` in the cross-cohort contrast →
   **non-identifiable as a design term.** RIN/ischemic are surfaced into colData as **diagnostic-only**
   columns (RIN-distribution reporting + optional low-RIN QC filter), never a GLM covariate. **RUVg is
   the sole confound corrector** — the graceful-degradation path plan risk #8 anticipated.
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
| `scripts/ruvg_calibration.py` | *(Stage 1)* substrate × method matrix (**naive-C vs RUVg-Cr**; recount3 vs Xena/Toil) vs the cell-A anchor → `outputs/calibration_report.md`. The `RUVg+RIN-Cr` arm was dropped after the symmetry probe (RIN GTEx-only → non-identifiable; see Decision 4). `DGE_CALIB_SUBSTRATES`/`DGE_CALIB_INDICATIONS` env-override the matrix (used for the multi-anchor re-run). | live S3 + R pipeline |
| `scripts/volcano_and_genome_summary.py` | 4×3 volcano grid (substrate×indication × A/C/Cr) + genome-wide summary stats → `outputs/plots/volcano_grid.png`, `outputs/genome_summary.{md,csv}`. | cell TSVs |
| `scripts/multi_anchor_report.py` | *(re-run)* rebuilt metric — FPR-vs-anchor-null, sign-concordance on anchor-sig genes, effect-size correlation, each with gene-bootstrap 95% CIs + paired Cr−C uplift CI → `outputs/multi_anchor/`. Companion to the hand-authored verdict; never regenerates `calibration_report.md`. | cell TSVs |
| `scripts/kscan_cr.R` | RUVg k-sensitivity probe scaffold. **Killed as moot** — the failure is structural, not k-dependent. | cached `.rds` |

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

- [`outputs/calibration_report.md`](outputs/calibration_report.md) — **the NEGATIVE verdict** (four-lens review + multi-anchor confirmation).
- [`outputs/summary.json`](outputs/summary.json) — k=2 substrate×indication calibration metrics + provenance.
- [`outputs/genome_summary.md`](outputs/genome_summary.md) / `.csv` — genome-wide per-cell summary stats.
- [`outputs/multi_anchor/multi_anchor_calibration.md`](outputs/multi_anchor/multi_anchor_calibration.md) + `multi_anchor_summary.json` — 6-anchor rebuilt-metric panel (FPR/sign-conc/effect-corr with bootstrap CIs).
- [`outputs/concordance_all.json`](outputs/concordance_all.json) — panel-wide A-vs-C concordance table.
- `outputs/plots/*.png`, `outputs/*.parquet` — regenerated, **gitignored** (see `.gitignore`).
