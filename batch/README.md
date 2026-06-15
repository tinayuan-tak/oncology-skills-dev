# `batch/` — scheduled compute, never invoked by Claude

This directory is the **structural fix** introduced in the v2 architecture: batch jobs that compute and write artifacts are physically separated from the `skills/` directory that Claude invokes for retrieval.

## The principle

`batch/` jobs:
- Run on a schedule (or manually triggered) by humans / CI / cron, **not by Claude**.
- Read from `s3://onc-compbio/data-catalog/{sources,derived}/`.
- Write to `s3://onc-compbio/data-catalog/derived/{transform}/{git-sha}/` (intermediate Parquets) or `s3://onc-compbio/core-artifacts/{ONCOTREE_CODE}/{subtype}/{gene}/{dimension}/` (`evidence.json` + `provenance.yaml` + figures).
- Pin reproducibility via the catalog manifest's `git_commit:` field.

`skills/` jobs:
- Are invoked by Claude.
- Are **retrieval-only** — they read pre-computed artifacts; they do not recompute on every call.
- This makes "wire a skill to recompute on every call" physically impossible — the foundational v2 invariant.

## What goes here

- One subdirectory per batch job, named for what it produces.
- Each job has: a Python entrypoint, parameter file references, S3 path conventions, and a comment block at the top citing the producing notebook (`notebooks/NN-*.ipynb`) it was promoted from.

## First entry

`expression_rna_COADREAD/run_pipeline.R` — pure-R DESeq2 + ComBat-seq + lfcShrink(apeglm) pipeline for COADREAD (combined TCGA-COAD + TCGA-READ; common name CRC). Computes tumor-vs-adjacent DGE across all ~18K genes, writes Parquet to `s3://onc-compbio/data-catalog/derived/COADREAD-dge/{git-sha}/tumor_vs_adjacent.parquet`. See [`expression_rna_COADREAD/README.md`](expression_rna_COADREAD/README.md) for the staged 00→05 pipeline and the joint-regime sensitivity-analysis discipline.
