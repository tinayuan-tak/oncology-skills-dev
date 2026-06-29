# `batch/expression_rna_COADREAD/` — global COADREAD (CRC) tumor-vs-normal DGE pipeline (R)

Pure-R Bioconductor pipeline that computes the global COADREAD (combined TCGA-COAD + TCGA-READ; OncoTree code COADREAD; common name "colorectal cancer / CRC") differential expression once across all ~18K genes and writes a Parquet artifact for sub-second per-gene retrieval downstream.

> **TODO (deep-research finding from `wf_9cf5659f-2e0`, 2026-06-15):** The runbook now mandates a **sensitivity-analysis discipline for the joint TCGA + GTEx regime** — when joint analysis is used (typically when adjacent-normal n < 30 for an indication), the pipeline must run **four DESeq2 cells**: {with, without} ComBat-seq class covariates × {TCGA-adjacent-only, joint with GTEx}, and emit a `sensitivity.parquet` matrix in addition to the primary results. The current pipeline below is the **single-cell** version; the four-cell variant becomes the default for the joint regime once `00_load_counts.R`'s source-specific loader is implemented (loader is currently a stub awaiting GDC + recount3 mirror availability). Rationale: per Sorokin/Buzdin 2023 (PMC10448432), TCGA-adjacent has field-effect signatures; per Hui/Goh 2024 (PMC11471903), class-covariate inclusion in ComBat when batch is confounded with biology inflates p-values. Neither comparator is clean; reporting only genes that survive all four cells is the high-confidence answer. See [runbook §"Decisions carried into implementation"](https://github.com/takoncoder/personal-notes/blob/main/strategy/oncology-platform-implementation-runbook.md) for the full rationale.

## The pipeline

```
00_load_counts.R       Load raw integer counts (cohort + matched normal).
                       Resolves source via configs/COADREAD.yaml `source.manifest_id`
                       (data-catalog manifest — gives the s3_uri to read from).
01_build_design.R      Construct the design matrix: tumor/normal label, batch
                       (TCGA-vs-GTEx if joint), CMS subtype if available.
02_combat_seq.R        ComBat-seq batch correction on raw counts (sva package).
                       Writes adjusted counts; the original counts also kept.
03_deseq2.R            DESeq2 NB GLM, Wald test, lfcShrink with apeglm.
                       Tier-1 BH-FDR genome-wide. Independent filtering on baseMean.
04_write_parquet.R     Convert DESeq2 results to a tidy Parquet (one row per gene,
                       columns: gene_symbol, log2fc, lfcSE, pvalue, padj, baseMean,
                       n_tumor, n_normal, …). Sorted by gene_symbol so per-gene
                       predicate-pushdown reads are sub-second.
05_provenance.R        Write provenance.yaml: DESeq2 version, sva version,
                       design formula, parameter hash, git commit, source
                       catalog_refs, Bioconductor release.
```

## Why pure R, not Python

DESeq2 + ComBat-seq are R/Bioconductor canon. Reviewers expect identical results to every published TCGA tumor-vs-normal analysis, which means *the* DESeq2, not a port. The interface to the rest of the platform is the **Parquet artifact**, not in-process function calls — Python skills/query_evidence.py reads what R writes. Process boundary = clean architectural seam.

## Running the pipeline

```bash
# end-to-end (orchestrator chains 00→05 in order):
pixi run Rscript batch/expression_rna_COADREAD/run_pipeline.R --config configs/COADREAD.yaml --git-sha $(git rev-parse HEAD)

# or each step independently for development:
pixi run Rscript batch/expression_rna_COADREAD/00_load_counts.R    --config configs/COADREAD.yaml --out /tmp/00_counts.rds
pixi run Rscript batch/expression_rna_COADREAD/01_build_design.R   --counts /tmp/00_counts.rds --out /tmp/01_design.rds
# ... etc.
```

## Source-agnostic: how the source decision plugs in

`configs/COADREAD.yaml` has a `source:` block:

```yaml
source:
  manifest_id: TODO          # e.g. tcga-gdc-dr42 — set after deep-research lands
  catalog_repo: rnd-computational-biology-oncology-data-catalog
```

The R pipeline calls a small helper (`resolve_source.R`) that reads the catalog manifest by `manifest_id`, returns the `s3_uri` and per-file metadata, and the loader pulls counts from there. **Swapping sources = a config edit, not a code change.**

## Output

```
s3://onc-compbio/data-catalog/derived/COADREAD-dge/{git-sha}/
├── tumor_vs_adjacent.parquet     # one row per gene, sorted by gene_symbol
└── provenance.yaml               # what produced this and from what
```

That Parquet is what `skills/query-target-evidence` reads (via predicate pushdown — one row, ~ms) to assemble per-gene `evidence.json` artifacts in `core-artifacts/`.

## Package dependencies

To be added to `pixi.toml` (channels: `conda-forge`, `bioconda`):
- `r-base`
- `bioconductor-deseq2`
- `bioconductor-sva` (provides `ComBat_seq`)
- `bioconductor-apeglm` (provides `lfcShrink` shrinkage method)
- `r-arrow` (Parquet I/O)
- `r-yaml`
- `r-optparse`
- `r-aws.s3` or `r-paws.storage` (S3 reads)

This adds ~500-800 MB to the environment, accepted per the v2 architecture decision (2026-06-15) since DESeq2 canonical-results are BLF-defensibility-critical.
