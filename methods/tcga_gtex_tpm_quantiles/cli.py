#!/usr/bin/env python3
"""tcga-gtex-tpm-quantiles — precompute per-(gene, source, group) log2(TPM+1) quantiles.

Aggregates the two multi-GB long TPM products into ONE small distribution-summary product so
the pan-cancer by-tissue tumor-vs-normal figure reads five-number summaries (fast) instead of
scanning ~800M raw rows on every render:

    tcga-tumor-tpm-recount3-long-v1  (study  -> tcga_tumor)   ┐
    gtex-tpm-recount3-long-v1        (tissue -> gtex_normal)  ┘ -> stacked quantile product

One DuckDB GROUP BY (gene, group) per product with quantile_cont over log2_tpm. Both products
are already log2(TPM+1) on the SAME recount3/GENCODE-v26 axis, so tumor + normal land on one
comparable unit — this method only aggregates, never re-normalizes.

Usage:
    python -m methods.tcga_gtex_tpm_quantiles.cli \\
        --tcga-long <path-or-s3>  --gtex-long <path-or-s3> \\
        --out ~/dev/framework-runs/tcga-gtex-tpm-quantiles-v1/tcga_gtex_tpm_tissue_quantiles.parquet \\
        [--no-upload]
Defaults for --tcga-long / --gtex-long resolve to the local batch copies if present, else the
S3 long products.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

DEPMAP_S3_BUCKET = "onc-compbio"
OUTPUT_S3_PREFIX = "data-catalog/derived/tcga-gtex-tpm-tissue-quantiles-v1"

# Default inputs: prefer local batch copies (fast, no S3), else the S3 long products.
_LOCAL_TCGA = Path.home() / "dev" / "framework-runs" / "tcga-tpm-long-v1" / "tcga_tpm_long.parquet"
_LOCAL_GTEX = Path.home() / "dev" / "framework-runs" / "gtex-tpm-long" / "gtex_tpm_long.parquet"
_S3_TCGA = "s3://onc-compbio/data-catalog/derived/tcga-tumor-tpm-recount3-long-v1/tcga_tpm_long.parquet"
_S3_GTEX = "s3://onc-compbio/data-catalog/derived/gtex-tpm-recount3-long-v1/gtex_tpm_long.parquet"

# Correctness spot-checks: (gene, source, group, approx expected median log2TPM). Verified against
# the live long products at build time; a broadly-expressed / marker gene per source.
CORRECTNESS_CHECKS = [
    ("GFAP", "tcga_tumor", "GBM", 11.2),    # astrocyte marker, high in glioblastoma tumor
    ("GFAP", "gtex_normal", "BRAIN", 8.9),  # and in normal brain
    ("EPCAM", "tcga_tumor", "COAD", 9.6),   # epithelial marker, colon carcinoma
]


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324 — integrity, not security
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _quantile_sql(src_uri: str, group_col: str, source_label: str) -> str:
    """DuckDB SQL: per-(gene, group) five-number summary of log2_tpm from one long product.
    quantile_cont = linear-interpolated continuous quantile (matches numpy's default 'linear')."""
    return f"""
    SELECT
        gene_symbol,
        ensembl_gene_id,
        '{source_label}'                              AS source,
        {group_col}                                   AS "group",
        COUNT(*)                                      AS n,
        MIN(log2_tpm)                                 AS min,
        quantile_cont(log2_tpm, 0.25)                 AS q1,
        quantile_cont(log2_tpm, 0.50)                 AS median,
        quantile_cont(log2_tpm, 0.75)                 AS q3,
        MAX(log2_tpm)                                 AS max,
        AVG(log2_tpm)                                 AS mean
    FROM read_parquet('{src_uri}')
    WHERE log2_tpm IS NOT NULL
    GROUP BY gene_symbol, ensembl_gene_id, {group_col}
    """


def _resolve(uri: str) -> str:
    """DuckDB reads s3:// via httpfs; local paths pass through. Return as-is (str)."""
    return uri


def build(tcga_long: str, gtex_long: str) -> "object":
    """Return the stacked quantile DataFrame (both sources) via two DuckDB aggregation passes."""
    import duckdb

    con = duckdb.connect()
    # Enable S3 reads only if an input is remote (avoids httpfs load when both are local).
    if str(tcga_long).startswith("s3://") or str(gtex_long).startswith("s3://"):
        con.execute("INSTALL httpfs; LOAD httpfs;")
        # DuckDB picks up the default AWS credential chain (AWS_PROFILE respected via env).
        con.execute("SET s3_region='us-east-1';")

    frames = []
    for uri, group_col, label in [(tcga_long, "study", "tcga_tumor"),
                                  (gtex_long, "tissue", "gtex_normal")]:
        t0 = time.monotonic()
        _log(f"[quantiles] aggregating {label} <- {uri}")
        df = con.execute(_quantile_sql(_resolve(uri), group_col, label)).fetch_df()
        _log(f"[quantiles]   {label}: {len(df):,} (gene,group) rows in {time.monotonic()-t0:.0f}s "
             f"({df['group'].nunique()} groups, {df['gene_symbol'].nunique()} genes)")
        frames.append(df)

    import pandas as pd
    allrows = pd.concat(frames, ignore_index=True)
    allrows = allrows.sort_values(["ensembl_gene_id", "source", "group"]).reset_index(drop=True)
    for c in ("min", "q1", "median", "q3", "max", "mean"):
        allrows[c] = allrows[c].astype("float32")
    allrows["n"] = allrows["n"].astype("int32")
    return allrows


def _run_correctness(allrows) -> None:
    """Log the correctness spot-checks — a (gene, source, group) median close to the expected."""
    for gene, source, group, expected in CORRECTNESS_CHECKS:
        hit = allrows[(allrows["gene_symbol"] == gene) & (allrows["source"] == source)
                      & (allrows["group"] == group)]
        if hit.empty:
            _log(f"[quantiles] CORRECTNESS MISS: {gene}/{source}/{group} not found")
            continue
        med = float(hit.iloc[0]["median"])
        ok = abs(med - expected) < 0.6
        _log(f"[quantiles] correctness {'OK ' if ok else 'CHECK'}: {gene}/{source}/{group} "
             f"median={med:.2f} (expected ~{expected})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tcga-long", default=None,
                    help="TCGA long product (path or s3://). Default: local batch copy else S3.")
    ap.add_argument("--gtex-long", default=None,
                    help="GTEx long product (path or s3://). Default: local batch copy else S3.")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--row-group-size", type=int, default=8192)
    ap.add_argument("--no-upload", action="store_true")
    args = ap.parse_args()

    tcga = args.tcga_long or (str(_LOCAL_TCGA) if _LOCAL_TCGA.exists() else _S3_TCGA)
    gtex = args.gtex_long or (str(_LOCAL_GTEX) if _LOCAL_GTEX.exists() else _S3_GTEX)
    _log(f"[quantiles] TCGA long: {tcga}")
    _log(f"[quantiles] GTEx long: {gtex}")

    import pyarrow as pa
    import pyarrow.parquet as pq

    allrows = build(tcga, gtex)
    _run_correctness(allrows)

    schema = pa.schema([
        pa.field("gene_symbol", pa.string()), pa.field("ensembl_gene_id", pa.string()),
        pa.field("source", pa.string()), pa.field("group", pa.string()),
        pa.field("n", pa.int32()),
        pa.field("min", pa.float32()), pa.field("q1", pa.float32()),
        pa.field("median", pa.float32()), pa.field("q3", pa.float32()),
        pa.field("max", pa.float32()), pa.field("mean", pa.float32()),
    ])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(allrows, schema=schema, preserve_index=False),
                   str(args.out), compression="snappy", row_group_size=args.row_group_size)
    size_bytes = args.out.stat().st_size
    md5 = _md5_hex(args.out)
    _log(f"[quantiles] wrote {args.out} ({size_bytes/1e6:.1f} MB) md5={md5}")
    _log(f"[quantiles] n_rows={len(allrows)} n_genes={allrows['gene_symbol'].nunique()} "
         f"n_ensembl={allrows['ensembl_gene_id'].nunique()} "
         f"sources={sorted(allrows['source'].unique())} "
         f"n_tcga_studies={allrows[allrows['source']=='tcga_tumor']['group'].nunique()} "
         f"n_gtex_tissues={allrows[allrows['source']=='gtex_normal']['group'].nunique()}")

    if not args.no_upload:
        import boto3
        key = f"{OUTPUT_S3_PREFIX}/{args.out.name}"
        _log(f"[quantiles] uploading -> s3://{DEPMAP_S3_BUCKET}/{key}")
        boto3.client("s3").upload_file(str(args.out), DEPMAP_S3_BUCKET, key,
                                       ExtraArgs={"Metadata": {"md5": md5}})
    _log("[quantiles] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
