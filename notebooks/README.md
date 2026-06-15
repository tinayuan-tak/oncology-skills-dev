# `notebooks/` — exploration before code hardens into `batch/`

The runbook's three-notebook sequence lives here, plus future exploration. Notebooks are where logic is sketched and validated; once a notebook is producing useful output stably, the logic is **promoted** into `batch/` (parameterized, runnable as `pixi run …`).

## The runbook three-notebook sequence

1. **01-data-inventory.ipynb** — reconnaissance of `s3://onc-compbio/`. Where does the TCGA-COAD/READ expression matrix live? Format? Dimensions? Barcode structure for tumor vs adjacent normal? Where is GTEx colon? DepMap 26Q1 location?
2. **02-global-COADREAD-dge.ipynb** — the expensive global compute. Load matrix, derive sample groups, run DGE across ~18K genes (BH FDR Tier 1), write Parquet to `s3://onc-compbio/data-catalog/derived/COADREAD-dge/{git-sha}/`.
3. **03-scd1-evidence.ipynb** — gene query proof-of-concept. Read SCD1's row using pyarrow predicate pushdown (NOT a full scan), assemble into `evidence.json`, write to `s3://onc-compbio/core-artifacts/COADREAD/all/SCD1/expression-rna/`.

Each notebook gets a corresponding entry in the `data-catalog` repo:
- Notebook 01 → fills the `s3_uri` and `md5` fields of seed source-release manifests (DepMap 26Q1, etc.) in `manifests/sources/`.
- Notebook 02 → produces a `derived/COADREAD-dge-…` manifest pinning `git_commit:` of the producing code.
- Notebook 03 → produces a manifest of the `COADREAD/all/SCD1/expression-rna/evidence.json` artifact, whose `derived_from:` points at the Notebook-02 derived dataset.

## After Phase-3 hardening

Notebook 02's logic is promoted to `batch/expression_rna_COADREAD/run_pipeline.R` (pure-R DESeq2 pipeline). Notebook 03's logic informs `skills/query-target-evidence/`, which is **retrieval-only** — it checks the artifact store, returns the stored `evidence.json` if fresh, and reports the batch job that produces it if missing.
