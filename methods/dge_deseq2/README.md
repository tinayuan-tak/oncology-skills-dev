# `dge_deseq2` — TCGA/GTEx tumor-vs-normal DESeq2

DESeq2-based differential-gene-expression method for the RNA-seq tumor-vs-normal diagnostic.
Part of the `dge_deseq2` modernization arc
(analysis-methods [#690](https://github.com/oneTakeda/rnd-computational-biology-oncology-analysis-methods/issues/690));
this file describes the module as it stands after S0
([#692](https://github.com/oneTakeda/rnd-computational-biology-oncology-analysis-methods/issues/692)).

## The live design: a two-comparator sensitivity grid

The production pipeline runs up to two DESeq2 contrasts ("cells") per indication, both from
the SAME loaded substrate, so a gene's call can be checked for robustness across comparator
type:

| cell | contrast | correction | status |
|------|----------|------------|--------|
| A | TCGA tumor vs TCGA adjacent-normal (unpaired model) | raw | live |
| C | TCGA tumor vs GTEx normal (population) | raw | live |
| B | TCGA tumor vs TCGA adjacent-normal | ComBat-seq (TSS covariate) | **retired**, analysis-methods#727 |
| D | TCGA tumor vs GTEx normal (joint, ComBat source-correction) | — | **retired** |
| Cr | RUVg-corrected re-run | — | diagnostic-only, `method_development/` |
| AG | TCGA adjacent-normal vs GTEx normal | raw | diagnostic-only, `adj_vs_gtex.parquet` (S2, #695) |

Cell A is the trust anchor; cell C is the population-normal cross-check. Cell B (ComBat-seq
re-run of cell A on the identical samples) was removed in analysis-methods#727 — it was a
robustness re-run rather than an independent comparator, and its ComBat-seq step both
inflated/sign-flipped log2FC and was the pipeline's perf cliff; newly-emitted products carry
no `log2fc_B`/`padj_B` columns. Cell D was retired for carrying an
unresolved platform/batch confound between the two comparator families; it is no longer
computed. `cells_ran` / `comparator_families_ran` on the emitted `sensitivity.parquet`
records which cells actually ran for a given indication (adjacent-normal is absent for
ACC/LGG/OV/SKCM/TGCT/UCS/SCLC, so those read cell C alone).

Cell **AG** (adjacent-vs-GTEx, S2 #695) is a **normal-vs-normal QC diagnostic**, not a
comparator cell: it fits TCGA adjacent-normal (relabelled to the positive "tumor" level) vs
GTEx normal (reference) through the *unchanged* `deseq2_fit`, so `log2FC > 0` means higher in
TCGA adjacent than GTEx — the same TCGA-positive/GTEx-reference orientation as cell C. It
measures the combined TCGA-vs-GTEx nuisance envelope (cross-cohort batch + field-cancerized
peritumoral effect + RIN/ischemic + annotation), so a **large effect is the expected signal**,
and its best use is as the evaluation target for a source-correction (RUVg / cell Cr). It is
emitted as its own `adj_vs_gtex.parquet` byproduct and, like cell Cr, is **never added to the
`cells` list** that feeds `assemble_sensitivity` — so it does not enter `sensitivity.parquet`,
`cells_supporting`, or any concordance column. It runs on **both** substrates (recount3 and
xena_toil), guarded by the same availability check as cells A/C. Consume its direction/rank,
not its absolute log2FC (cross-cohort size factors are partly a normalization artifact).

Not all ~30 TCGA indications are wired yet, and not every wired indication has both an
adjacent-normal and a GTEx arm — see analysis-methods#690 for the indication-coverage roadmap
(S1). The adjacent-vs-GTEx diagnostic contrast landed in S2 (#695).

## Substrates

- **recount3** (`r/live/00_load_recount3.R`) — the production substrate. TCGA + GTEx counts
  uniformly reprocessed by one Monorail pipeline on GENCODE v26, so cells A/B/C above are
  internally comparable (see `read/__init__.py`'s substrate-provenance helpers, which derive
  this from the product manifest rather than an indication list).
- **Xena/Toil** (`r/live/00_load_xena_toil.R`) — a second, independent count substrate
  (UCSC Toil recompute, STAR+RSEM, GENCODE **v23**) for a cross-substrate reproducibility
  check. **Secondary / diagnostic, NOT a verdict input** (S1b, analysis-methods#694): run it
  with `run_pipeline.R --contrast four_cell_sensitivity --substrate xena_toil --indication <ind>`
  (or `scripts/run_indication_batch.sh` with `SUBSTRATE=xena_toil`). It reuses the same 06
  four-cell driver and the same one-aliquot-per-case dedup as recount3, but its catalogued
  product carries a **`-xenatoil` id infix** (`<ind>-dge-tumor-vs-normal-sensitivity-xenatoil-v1`)
  so it lands on a distinct S3 key/catalog id and is invisible to the pancan discovery glob and
  the sensitivity read path — the classifier only ever reads the recount3 product. On this
  substrate, as on recount3, only **cells A and C run** (cell B was removed pipeline-wide in
  analysis-methods#727 — see above; the Toil matrix never carried the `tcga_tss` batch
  structure cell B corrected on, so this held true before #727 too). The emitted
  `sensitivity.parquet` therefore has no `log2fc_B`/`padj_B` columns and `cells_ran` is at
  most 2. Both
  substrates are fed **offset-free** (plain counts; Toil ships `expected_count` with no
  effective-length matrix, so no length offset is possible — see the loader header). Gene rows
  are keyed on HGNC symbol via the substrate's native GENCODE v23 probemap; the cross-substrate
  stable-Ensembl-ID authority is a separate concern (S1c, #699).

## Directory layout

```
dge_deseq2/
  __init__.py          public API — re-exports the read/-side functions consumers import
  cli.py                Python CLI wrapping the R pipeline (Rscript r/live/run_pipeline.R)
  emit.py, emit_pan_tissue.py, figures.py   matplotlib/plotly figure emitters (no R dependency)
  gene_lengths.py       Gencode v26 gene-length loader (TPM normalization)
  derive_pancan_stack.py
  read/                 read-side package — Parquet readers consumed by compose-dashboard,
                        notebooks, and other methods. `from .read import ...` in __init__.py
                        and `from methods.dge_deseq2 import read` elsewhere both still resolve
                        every current name (including the private helpers several tests reach
                        into directly) — this stage only wraps the module in a package so a
                        future secondary-substrate reader (S1b) has somewhere to live alongside
                        it; it does not yet split the file's contents.
  r/
    live/                production R pipeline: 00_load_recount3.R (loader) →
                          06_four_cell_driver.R (whole-cohort) /
                          07_stratified_four_cell_driver.R (per-subgroup),
                          both sourcing _four_cell_lib.R; run_pipeline.R chains them.
    legacy/               quarantined — see r/legacy/README.md. Not called by anything in
                          r/live/ or by cli.py's default path.
  method_development/    ad-hoc calibration / reimplementation scratch work, not shipped code
  scripts/write_evidence.py
  tests/
```

## Running it

```bash
# production: recount3 four-cell sensitivity grid (writes sensitivity.parquet +
# tumor_vs_adjacent.parquet + tumor_vs_gtex.parquet + adj_vs_gtex.parquet + provenance.yaml)
pixi run python -m methods.dge_deseq2.cli \
    --indication COADREAD --contrast four_cell_sensitivity \
    --release-pin 2026-Q2 --out /tmp/dge_deseq2_run/

# quarantined legacy chain (only exercised today by the byte-identity gate)
pixi run python -m methods.dge_deseq2.cli \
    --indication COADREAD --contrast tumor_vs_adjacent \
    --release-pin 2026-Q2 --out /tmp/dge_deseq2_run/
```

`--dry-run` prints the resolved `Rscript` invocation without executing it. Per-subgroup runs
add `--stratify-by <axis> --subgroup-assignments-manifest <id> --strata <A,B,...>` (requires
`--contrast four_cell_sensitivity`).

## Consuming the output

`dge_deseq2.read` (in `read/`) is the read side — Parquet predicate-pushdown readers keyed by
target + indication, e.g. `read_tumor_vs_normal_selectivity`, `read_dge_gene_row`,
`read_per_sample_expression_all_three_groups`. These are re-exported from the package
`__init__.py` for the `_import_method`-then-getattr pattern compose-dashboard uses; import
either `methods.dge_deseq2` or `methods.dge_deseq2.read` directly.

## Cross-substrate reproducibility QC (S3c, #732)

`dge_deseq2.concordance` measures how well the per-gene effect sizes agree between the
**recount3** and **Xena/Toil** substrates for the same contrast cell (A and C), for every
indication that has a sensitivity product on both substrates (declared in
`config.run_ledger_intent()['sensitivity']`; today: COADREAD).

```bash
python -m methods.dge_deseq2.concordance --out concordance.json --self-check   # reads S3; needs cbg creds
```

- **Reproducibility-only, NOT biological validation.** The two substrates reprocess largely the
  same raw reads, so agreement measures *pipeline stability*, not that the biology is true. Every
  emitted row carries `reproducibility_only=True`.
- **Joins on the stable authority `gene_id`, never on the HGNC symbol.** The two substrates
  collapse counts to different symbol vocabularies (Ensembl-116 HGNC vs GENCODE-v23), so a
  symbol-string join would silently drop drifted symbols and mis-map reused ones — the
  annotation-skew artifact this QC exists to catch. Each product is resolved back to the authority
  gene_id (read time, via `methods.gene_id_authority.product`) and only genes resolving to exactly
  one authority gene in both substrates enter the join.
- Reports per (indication × cell): **coverage denominators** (mapped / ambiguous-dropped /
  unmapped-dropped per substrate), a significant-in-both gate, and the **Spearman rho** of log2fc
  over the gated set (plus sign-discordance and an ungated-context rho).
- **Fail-loud**: an empty/degenerate shared-gene join, a degenerate gated set, or zero declared
  pairs raise `ConcordanceError` rather than emitting a NaN/vacuous concordance.
- The artifact is generated on demand and is **not catalogued** (an ops/QC artifact *about* the
  products, like `build_run_ledger`'s `run_ledger.json`).

Live COADREAD signal (reproduces the ad-hoc S1b check): cell A rho ≈ 0.97, cell C rho ≈ 0.96,
with the GTEx colon tissue-composition confound surfacing as more sign-discordant genes in cell C.

## Testing

```bash
pixi run pytest methods/dge_deseq2/ --import-mode=importlib
```

The R4 byte-identity gate (`tests/test_byte_identity_vs_legacy_coadread.py`) additionally
needs a full R/Bioconductor env, a sibling `claude-oncology-skills` checkout, and credentialed
S3 — it's `@pytest.mark.requires_data` and skips cleanly without them; see its module
docstring for what it's actually checking and why the legacy chain (`r/legacy/`) is kept
runnable rather than deleted.

## Known gaps / roadmap

See analysis-methods#690 for the full modernization plan. As of S0:
- The indication → TCGA-study / GTEx-tissue rosters are still hard-coded in several places
  (`read/__init__.py`, R loaders) — consolidating them into one source of truth is S1 (#693).
- Xena/Toil is dev-only (above) — S1b (#694).
- ~~The adjacent-vs-GTEx normal-baseline-agreement diagnostic contrast~~ — **landed, S2 (#695)**:
  cell AG, emitted as `adj_vs_gtex.parquet` on both substrates, diagnostic-only /
  classifier-excluded.
- ~~There is no automated output-QC layer (summary tables, figures, cross-substrate
  reproducibility)~~ — **landed**: fail-loud output-QC assertions (S3a #701), per-run
  figures/metrics bundle (S3b #702), and the cross-substrate reproducibility concordance QC
  (S3c #732, `dge_deseq2.concordance`, above).
