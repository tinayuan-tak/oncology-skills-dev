# `dge_deseq2` — TCGA/GTEx tumor-vs-normal DESeq2

DESeq2-based differential-gene-expression method for the RNA-seq tumor-vs-normal diagnostic.
Part of the `dge_deseq2` modernization arc
(analysis-methods [#690](https://github.com/oneTakeda/rnd-computational-biology-oncology-analysis-methods/issues/690));
this file describes the module as it stands after S0
([#692](https://github.com/oneTakeda/rnd-computational-biology-oncology-analysis-methods/issues/692)).

## The live design: a three-cell sensitivity grid

The production pipeline runs up to three DESeq2 contrasts ("cells") per indication, all from
the SAME loaded substrate, so a gene's call can be checked for robustness across comparator
type and batch-correction choice:

| cell | contrast | correction | status |
|------|----------|------------|--------|
| A | TCGA tumor vs TCGA adjacent-normal | raw | live |
| B | TCGA tumor vs TCGA adjacent-normal | ComBat-seq (TSS covariate) | live, de-weighted (see `read/`) |
| C | TCGA tumor vs GTEx normal (population) | raw | live |
| D | TCGA tumor vs GTEx normal (joint, ComBat source-correction) | — | **retired** |
| Cr | RUVg-corrected re-run | — | diagnostic-only, `method_development/` |

Cell A is the trust anchor; cell C is the population-normal cross-check; cell B corroborates
direction but is excluded from the magnitude gate (ComBat inflates/sign-flips log2FC for some
genes — see the calibration notes in `read/__init__.py`). Cell D was retired for carrying an
unresolved platform/batch confound between the two comparator families; it is no longer
computed. `cells_ran` / `comparator_families_ran` on the emitted `sensitivity.parquet`
records which cells actually ran for a given indication (adjacent-normal is absent for
ACC/LGG/OV/SKCM/TGCT/UCS/SCLC, so those read cell C alone).

Not all ~30 TCGA indications are wired yet, and not every wired indication has both an
adjacent-normal and a GTEx arm — see analysis-methods#690 for the indication-coverage roadmap
(S1) and the planned adjacent-vs-GTEx diagnostic contrast (S2).

## Substrates

- **recount3** (`r/live/00_load_recount3.R`) — the production substrate. TCGA + GTEx counts
  uniformly reprocessed by one Monorail pipeline on GENCODE v26, so cells A/B/C above are
  internally comparable (see `read/__init__.py`'s substrate-provenance helpers, which derive
  this from the product manifest rather than an indication list).
- **Xena/Toil** (`r/legacy/00_load_xena_toil.R`) — a second, independent count substrate
  (UCSC Toil recompute, GENCODE v23) for a cross-substrate reproducibility check. **Currently
  dev-only and unwired** — no production CLI path calls it; it lives under `r/legacy/`
  because it isn't part of the live pipeline today, not because it's being retired. Promoting
  it to its own catalogued secondary-substrate data-package (with the same one-aliquot-per-case
  dedup discipline as recount3) is analysis-methods#694 (S1b). See `r/legacy/README.md`.

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
# tumor_vs_adjacent.parquet + tumor_vs_gtex.parquet + provenance.yaml)
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
- The adjacent-vs-GTEx normal-baseline-agreement diagnostic contrast doesn't exist yet — S2
  (#695).
- There is no automated output-QC layer (summary tables, figures, cross-substrate
  reproducibility) — S3 (#696).
