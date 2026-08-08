#!/usr/bin/env python3
"""sclc-dge-tumor-vs-gtex — SCLC-tumor vs GTEx-lung DEG, emitted in the four-cell
sensitivity schema with ONLY cell C populated.

    python -m methods.sclc_dge_tumor_vs_gtex.cli            # dry-run (no upload)
    python -m methods.sclc_dge_tumor_vs_gtex.cli --upload   # emit to S3

WHY THIS EXISTS
---------------
SCLC has no TCGA cohort and, in the ingested George et al. 2015 cohort, ZERO
adjacent-normal samples — so cells A/B (TCGA tumor-vs-paired-adjacent) can never
run, exactly like OV (ov-dge-tumor-vs-normal-sensitivity-v1, n_adjacent=0,
cells_ran=C). This method produces the SAME sensitivity.parquet schema so the
existing selectivity reader (`read_tumor_vs_normal_sensitivity_gene_row`)
consumes it with zero reader changes, landing SCLC in the `tvn_gtex_only`
regime the tumor-vs-normal-selectivity card already handles.

WHY WELCH-ON-TPM, NOT DESeq2-ON-COUNTS (the sibling pipeline)
-------------------------------------------------------------
Every other sensitivity product is built by the DESeq2 R pipeline on RAW recount3
integer counts. SCLC has NO open raw counts: the George raw reads are EGA
controlled-access (EGAS00001000925 / EGAD00001001244), were never mirrored to
SRA, and no uniform-reprocessing project (recount3/ARCHS4/GREIN/DEE2) can expose
a counts matrix for a non-SRA study. The only open expression data is the
cBioPortal FPKM matrix, harmonized to `sclc-george-tpm-long-v1` = log2(TPM+1).
DESeq2 requires integer counts and cannot ingest TPM, so cell C here is computed
by Welch's t-test on log2(TPM+1) — the SAME kernel dge_tcga_gtex_precompute uses,
fed the TPM unit instead of CPM. This makes SCLC's cell C STATISTICALLY DISTINCT
from its DESeq2 siblings; the manifest records that loudly.

CROSS-COHORT BATCH CAVEAT (mandatory; stronger than the recount3-internal siblings)
-----------------------------------------------------------------------------------
George tumors are hg19/FPKM-derived (cBioPortal); GTEx-LUNG is hg38/recount3.
Same log2(TPM+1) UNIT but DIFFERENT gene models + sequencing pipelines. This is a
DIRECTIONAL over-expression screen vs canonical healthy lung — NOT paired-adjacent
rigor, NOT even within-recount3 tumor-vs-GTEx rigor. ComBat-seq is not applicable
(no shared count space; source-confounded-with-condition over-correction risk).
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path

import click


# Substrate products (both log2(TPM+1) on the recount3 unversioned-Ensembl axis).
TUMOR_PRODUCT = "sclc-george-tpm-long-v1"       # study='SCLC', 81 tumors
GTEX_PRODUCT = "gtex-tpm-recount3-long-v1"       # tissue='LUNG' filter → 655 normals
GTEX_TISSUE = "LUNG"
INDICATION = "SCLC"
S3_BUCKET = "onc-compbio"
OUTPUT_MANIFEST_ID = "sclc-dge-tumor-vs-normal-sensitivity-v1"

# Actionability thresholds — mirror the OV/DESeq2 sibling manifest so the
# emitted flags mean the same thing downstream.
SIG_Q = 0.05          # padj < 0.05 → significant
UP_ABS_LOG2FC = 1.0   # |log2FC| >= 1 → "upregulated cohort" (is_significant is the harder gate)


def _log(msg: str) -> None:
    click.echo(msg, err=True)


def _md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Stats kernel — REUSED from dge_tcga_gtex_precompute (identical math), fed
# log2(TPM+1) sample vectors instead of log2(CPM+1). Vendored here (not imported)
# so this method has no import-time dependency on the counts-based sibling and
# the reused-verbatim contract is explicit and testable in isolation.
# ---------------------------------------------------------------------------
def _welch_deg(log2_a, log2_b):
    """Per-gene Welch's t-test between two log2-scale sample vectors.

    Returns (log2_fold_change, p_value). log2_fold_change = mean(a) - mean(b);
    positive = up in a (tumor). < 2 samples per side → (0.0, 1.0);
    zero-variance both sides → (lfc, 1.0). Identical to
    dge_tcga_gtex_precompute._welch_deg (only the input unit differs).
    """
    import numpy as np
    from scipy import stats
    a = log2_a[~np.isnan(log2_a)]
    b = log2_b[~np.isnan(log2_b)]
    if len(a) < 2 or len(b) < 2:
        return 0.0, 1.0
    lfc = float(a.mean()) - float(b.mean())
    if a.std(ddof=1) == 0 and b.std(ddof=1) == 0:
        return lfc, 1.0
    try:
        _t, p = stats.ttest_ind(a, b, equal_var=False, nan_policy="omit")
        p = float(p) if p == p else 1.0
    except Exception:  # noqa: BLE001
        p = 1.0
    return lfc, p


def _bh_correct(pvals):
    """Benjamini-Hochberg FDR. Identical to dge_tcga_gtex_precompute._bh_correct."""
    import numpy as np
    n = len(pvals)
    if n == 0:
        return np.array([])
    order = np.argsort(pvals)
    ranked = pvals[order]
    q_ranked = ranked * n / (np.arange(n) + 1)
    q_ranked = np.minimum.accumulate(q_ranked[::-1])[::-1]
    q_ranked = np.clip(q_ranked, 0, 1)
    q = np.empty_like(q_ranked)
    q[order] = q_ranked
    return q


def _read_long_tpm(manifest_id: str, s3fs, group_col: str, group_val: str):
    """Read a long-TPM product filtered to one cohort group, return tidy DataFrame
    [gene_symbol, ensembl_gene_id, sample_id, log2_tpm]. Resolves the S3 URI from
    the data-catalog manifest (single source of truth for the path)."""
    import pyarrow.parquet as pq
    from methods.catalog_query.read import s3_uri_for
    s3_uri = s3_uri_for(manifest_id)
    path = s3_uri.replace("s3://", "")
    cols = ["gene_symbol", "ensembl_gene_id", "sample_id", group_col, "log2_tpm"]
    _log(f"    Reading {manifest_id} ({group_col}={group_val}) from {s3_uri}")
    tbl = pq.read_table(path, filesystem=s3fs,
                        filters=[(group_col, "=", group_val)], columns=cols)
    df = tbl.to_pandas()
    _log(f"    {df.shape[0]:,} rows, "
         f"{df['sample_id'].nunique():,} samples, {df['ensembl_gene_id'].nunique():,} genes")
    return df, s3_uri


def compute_cell_c(s3fs):
    """Compute the cell-C (SCLC-tumor vs GTEx-LUNG) Welch DEG on log2(TPM+1).

    Returns (result_df, provenance) where result_df carries the OV/DESeq2
    sensitivity schema (cells A/B as NaN) so the standard reader consumes it.
    """
    import numpy as np
    import pandas as pd

    tumor, tumor_uri = _read_long_tpm(TUMOR_PRODUCT, s3fs, "study", INDICATION)
    gtex, gtex_uri = _read_long_tpm(GTEX_PRODUCT, s3fs, "tissue", GTEX_TISSUE)

    n_tumor = tumor["sample_id"].nunique()
    n_gtex = gtex["sample_id"].nunique()

    # Pivot each to gene × sample matrices on the shared ensembl axis.
    # Both products are deduped to one row per (ensembl_gene_id, sample_id) upstream.
    tmat = tumor.pivot(index="ensembl_gene_id", columns="sample_id", values="log2_tpm")
    gmat = gtex.pivot(index="ensembl_gene_id", columns="sample_id", values="log2_tpm")

    # gene_symbol lookup (ensembl → symbol). Both products carry it; prefer tumor's.
    sym = (tumor.drop_duplicates("ensembl_gene_id")
           .set_index("ensembl_gene_id")["gene_symbol"])

    # INNER join on ensembl_gene_id — only genes measured in both cohorts.
    common = tmat.index.intersection(gmat.index)
    _log(f"  Genes: tumor={tmat.shape[0]:,} gtex={gmat.shape[0]:,} common={len(common):,}")
    tmat = tmat.loc[common]
    gmat = gmat.loc[common]

    tarr = tmat.to_numpy(dtype=np.float64)
    garr = gmat.to_numpy(dtype=np.float64)
    n = len(common)
    lfc = np.empty(n)
    pval = np.empty(n)
    for i in range(n):
        lfc[i], pval[i] = _welch_deg(tarr[i], garr[i])
    qval = _bh_correct(pval)

    ensembl = list(common)
    symbols = [sym.get(e) for e in ensembl]

    # Assemble in the OV sensitivity schema. Cell C = this contrast; A/B = NaN
    # (no TCGA adjacent-normal exists for SCLC). dominant_direction / cells_*
    # computed for the single cell that ran.
    sig_c = qval < SIG_Q
    direction = np.where(sig_c & (lfc > 0), "up",
                np.where(sig_c & (lfc < 0), "down", "none"))
    df = pd.DataFrame({
        "gene_symbol": symbols,
        "ensembl_gene_id": ensembl,
        "cells_ran": 1.0,
        # cells_supporting: 1 if the single cell produced a directional sig call, else 0.
        "cells_supporting": np.where(direction != "none", 1.0, 0.0),
        "dominant_direction": direction,
        "sig_all_cells": sig_c,
        "discordant": False,          # only one cell ran → never self-discordant
        "log2fc_A": np.nan,
        "padj_A": np.nan,
        "log2fc_B": np.nan,
        "padj_B": np.nan,
        "log2fc_C": lfc.astype(np.float64),
        "padj_C": qval.astype(np.float64),
        "max_abs_log2fc": np.abs(lfc).astype(np.float64),
    })
    # Drop genes with no HGNC symbol (consumers filter by gene_symbol).
    df = df[df["gene_symbol"].notna()].reset_index(drop=True)
    df = df.sort_values("gene_symbol").reset_index(drop=True)

    provenance = {
        "n_tumor": int(n_tumor),
        "n_adjacent": 0,
        "n_gtex": int(n_gtex),
        "n_genes": int(len(df)),
        "n_significant_up": int(((df["dominant_direction"] == "up") & df["sig_all_cells"]).sum()),
        "tumor_product_uri": tumor_uri,
        "gtex_product_uri": gtex_uri,
    }
    return df, provenance


def write_parquet(df, local_path: Path) -> int:
    """Write the sensitivity parquet in the OV/DESeq2 column schema + dtypes.

    NOTE: the sibling DESeq2 products emit gene_symbol as the sole row key (no
    ENSG column). We ADD ensembl_gene_id as an extra provenance column — a
    superset, harmless to the gene_symbol-filtering reader.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("ensembl_gene_id", pa.string()),
        pa.field("cells_ran", pa.float64()),
        pa.field("cells_supporting", pa.float64()),
        pa.field("dominant_direction", pa.string()),
        pa.field("sig_all_cells", pa.bool_()),
        pa.field("discordant", pa.bool_()),
        pa.field("log2fc_A", pa.float64()),
        pa.field("padj_A", pa.float64()),
        pa.field("log2fc_B", pa.float64()),
        pa.field("padj_B", pa.float64()),
        pa.field("log2fc_C", pa.float64()),
        pa.field("padj_C", pa.float64()),
        pa.field("max_abs_log2fc", pa.float64()),
    ])
    table = pa.Table.from_pydict(
        {f.name: df[f.name].tolist() for f in schema}, schema=schema)
    table = table.sort_by("gene_symbol")
    local_path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, str(local_path), compression="snappy", row_group_size=8192)
    return local_path.stat().st_size


@click.command()
@click.option("--local-dir", type=click.Path(file_okay=False, path_type=Path),
              default=Path.home() / "dev" / "framework-runs" / "sclc-dge-tumor-vs-gtex",
              help="Local staging directory.")
@click.option("--upload", is_flag=True,
              help="Upload parquet to S3. Default is dry-run (local only).")
def main(local_dir: Path, upload: bool) -> None:
    """Compute + emit sclc-dge-tumor-vs-normal-sensitivity-v1 (cell C only)."""
    import pyarrow.fs as fs
    s3fs = fs.S3FileSystem()

    local_dir = local_dir / INDICATION
    local_dir.mkdir(parents=True, exist_ok=True)
    s3_prefix = f"data-catalog/derived/{OUTPUT_MANIFEST_ID}"

    _log(f"\n=== SCLC-tumor vs GTEx-{GTEX_TISSUE} DEG (Welch on log2(TPM+1), cell C only) ===")
    _log(f"  Output product: {OUTPUT_MANIFEST_ID}  (upload={'yes' if upload else 'DRY-RUN'})")

    _log("\n[1/2] Computing cell C")
    df, prov = compute_cell_c(s3fs)
    _log(f"  n_tumor={prov['n_tumor']}  n_gtex={prov['n_gtex']}  genes={prov['n_genes']:,}")
    _log(f"  significant up in tumor (q<{SIG_Q}): {prov['n_significant_up']:,}")

    _log("\n[2/2] Writing parquet")
    parquet_path = local_dir / "sensitivity.parquet"
    size = write_parquet(df, parquet_path)
    md5 = _md5_file(parquet_path)
    _log(f"  Wrote {parquet_path} ({size/1e6:.2f} MB, md5={md5})")

    # Spot-check the canonical SCLC biology so a dry-run is self-validating.
    for g in ("DLL3", "ASCL1", "GAPDH", "ACTB"):
        r = df[df["gene_symbol"] == g]
        if len(r):
            row = r.iloc[0]
            _log(f"    {g:6s} log2fc_C={row['log2fc_C']:+.2f} padj_C={row['padj_C']:.2e} "
                 f"dir={row['dominant_direction']}")

    if upload:
        import boto3
        s3 = boto3.client("s3")
        key = f"{s3_prefix}/sensitivity.parquet"
        _log(f"\n  Uploading → s3://{S3_BUCKET}/{key}")
        s3.upload_file(str(parquet_path), S3_BUCKET, key,
                       ExtraArgs={"Metadata": {"md5": md5}})
        _log("  Upload complete.")
    else:
        _log("\n  DRY-RUN — not uploaded. Re-run with --upload to emit.")

    _log(f"\n  md5={md5}  size_bytes={size}  n_genes={prov['n_genes']}")
    _log(f"  (record these in manifests/derived/{OUTPUT_MANIFEST_ID}.yaml)")
    _log("\n=== done ===")


if __name__ == "__main__":
    main()
