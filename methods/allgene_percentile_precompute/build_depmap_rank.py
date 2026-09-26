#!/usr/bin/env python3
"""build_depmap_rank — pan-cancer all-gene percentile of the DepMap panel median.

Reads the wide OmicsExpressionTPMLogp1... matrix (cell-lines × gene columns), computes
each gene's panel median log2(TPM+1) across all cell lines, and ranks genes into a
0-100 percentile. Lets the cellline-rna-distribution card answer "where does this
target's panel median sit among ALL protein-coding genes in the DepMap panel".

Output: allgene-depmap-rank-26q3-v1/depmap_panel_median_allgene_rank.parquet (gene-sorted).

Usage:
  python -m methods.allgene_percentile_precompute.build_depmap_rank \\
      --matrix <path-or-s3>  --out <dir>/depmap_panel_median_allgene_rank.parquet [--no-upload]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path

S3_BUCKET = "onc-compbio"
OUTPUT_S3_PREFIX = "data-catalog/derived/allgene-depmap-rank-26q3-v1"
_S3_MATRIX = (
    "s3://onc-compbio/data-catalog/derived/depmap-26q3-parquet-v1/"
    "OmicsExpressionTPMLogp1HumanProteinCodingGenes.parquet"
)

# DepMap wide columns are 'SYMBOL (ENTREZ)'; split to (symbol, entrez).
_COL_RE = re.compile(r"^(?P<sym>.+?)\s+\((?P<entrez>\d+)\)$")

CORRECTNESS_CHECKS = [  # (symbol, comparator, threshold_pct)
    ("ACTB", ">=", 99.0),  # housekeeping → ceiling
    ("SFTPC", "<=", 20.0),  # lung marker → bottom in pan-cancer panel
]


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(matrix_uri: str):
    import pandas as pd
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    t0 = time.time()
    if matrix_uri.startswith("s3://"):
        table = pq.read_table(matrix_uri[len("s3://") :], filesystem=fs.S3FileSystem())
    else:
        table = pq.read_table(matrix_uri)
    df = table.to_pandas()
    _log(f"[read] {df.shape[0]} lines × {df.shape[1]} cols in {time.time() - t0:.1f}s")

    idcol = df.columns[0]
    gene_cols = [c for c in df.columns if c != idcol and not c.startswith("IsDefault")]
    med = df[gene_cols].median(axis=0, numeric_only=True)  # panel median per gene column

    rows = []
    for col, m in med.items():
        mo = _COL_RE.match(col)
        sym = mo.group("sym") if mo else col
        entrez = mo.group("entrez") if mo else None
        rows.append((sym, entrez, float(m)))
    out = pd.DataFrame(rows, columns=["gene_symbol", "entrez_gene_id", "panel_median_log2tpm"])
    out["allgene_percentile"] = (out["panel_median_log2tpm"].rank(pct=True) * 100.0).astype("float32")
    out["allgene_rank"] = out["panel_median_log2tpm"].rank(ascending=False, method="min").astype("int32")
    out["n_genes"] = len(out)
    out["panel_median_log2tpm"] = out["panel_median_log2tpm"].astype("float32")
    out = out.sort_values("gene_symbol").reset_index(drop=True)
    return out


def write(df, out: Path, row_group_size: int = 8192) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    out.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("entrez_gene_id", pa.string()),
            pa.field("panel_median_log2tpm", pa.float32()),
            pa.field("allgene_percentile", pa.float32()),
            pa.field("allgene_rank", pa.int32()),
            pa.field("n_genes", pa.int32()),
        ]
    )
    pq.write_table(
        pa.Table.from_pandas(df[[f.name for f in schema]], schema=schema, preserve_index=False),
        str(out),
        compression="snappy",
        row_group_size=row_group_size,
    )
    md5 = _md5_hex(out)
    return {"md5": md5, "size_bytes": out.stat().st_size, "n_rows": len(df)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the DepMap panel-median all-gene rank product.")
    p.add_argument("--matrix", default=_S3_MATRIX)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--row-group-size", type=int, default=8192)
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args(argv)

    df = build(args.matrix)
    meta = write(df, args.out, args.row_group_size)
    _log(f"[write] {args.out.name}: {meta['n_rows']} genes / {meta['size_bytes']} B / md5={meta['md5']}")

    for sym, cmp_, thresh in CORRECTNESS_CHECKS:
        sub = df[df["gene_symbol"] == sym]
        if len(sub):
            pct = float(sub["allgene_percentile"].iloc[0])
            ok = pct >= thresh if cmp_ == ">=" else pct <= thresh
            _log(f"  check {sym}: pct={pct:.1f} {cmp_} {thresh} {'OK' if ok else 'UNEXPECTED'}")

    if not args.no_upload:
        import boto3

        key = f"{OUTPUT_S3_PREFIX}/{args.out.name}"
        boto3.client("s3").upload_file(str(args.out), S3_BUCKET, key, ExtraArgs={"Metadata": {"md5": meta["md5"]}})
        _log(f"[upload] s3://{S3_BUCKET}/{key}")
    else:
        _log("[upload] skipped (--no-upload)")
    print(f"md5={meta['md5']} size_bytes={meta['size_bytes']} n_rows={meta['n_rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
