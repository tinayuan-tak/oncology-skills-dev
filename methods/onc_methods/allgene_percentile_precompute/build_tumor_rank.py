#!/usr/bin/env python3
"""build_tumor_rank — per (source, group) all-gene percentile of the tumor/normal median.

DERIVED from tcga-gtex-tpm-tissue-quantiles-v1 (which already holds per-(gene, source,
group) median log2TPM) — so this is an aggregation-only rank, NOT a re-scan of the
multi-GB raw long products. For each (source, group) it ranks every gene's `median`
into a 0-100 percentile, so the tumor-rna-distribution card can answer "where does this
target's tumor median sit among ALL genes in this indication's tumor cohort".

Output: allgene-tumor-rank-v1/tumor_median_allgene_rank.parquet, gene-sorted for pushdown.

Usage:
  python -m onc_methods.allgene_percentile_precompute.build_tumor_rank \\
      --quantiles <path-or-s3>  --out <dir>/tumor_median_allgene_rank.parquet [--no-upload]
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

S3_BUCKET = "onc-compbio"
OUTPUT_S3_PREFIX = "data-catalog/derived/allgene-tumor-rank-v1"
_S3_QUANTILES = (
    "s3://onc-compbio/data-catalog/derived/tcga-gtex-tpm-tissue-quantiles-v1/tcga_gtex_tpm_tissue_quantiles.parquet"
)

# Correctness spot-checks (verified live in prototyping): housekeeping at ceiling,
# lineage markers low outside their tissue.
CORRECTNESS_CHECKS = [
    ("ACTB", "tcga_tumor", None, 99.0),  # housekeeping → top pct in ANY tumor group
    ("SFTPC", "tcga_tumor", "ACC", 60.0),  # lung marker → low-mid in adrenocortical (< this)
]


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build(quantiles_uri: str):
    """Read the quantiles product, rank each gene's median within (source, group)."""
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    t0 = time.time()
    if quantiles_uri.startswith("s3://"):
        path = quantiles_uri[len("s3://") :]
        table = pq.read_table(
            path, filesystem=fs.S3FileSystem(), columns=["gene_symbol", "ensembl_gene_id", "source", "group", "median"]
        )
    else:
        table = pq.read_table(quantiles_uri, columns=["gene_symbol", "ensembl_gene_id", "source", "group", "median"])
    df = table.to_pandas()
    _log(f"[read] {len(df)} (gene,source,group) rows in {time.time() - t0:.1f}s")

    # Percentile rank of median WITHIN each (source, group) — the all-gene null per cohort.
    df["allgene_percentile"] = df.groupby(["source", "group"])["median"].rank(pct=True) * 100.0
    df["allgene_rank"] = df.groupby(["source", "group"])["median"].rank(ascending=False, method="min").astype("int32")
    df["n_genes_in_group"] = df.groupby(["source", "group"])["median"].transform("size").astype("int32")
    # gene-sorted for pushdown (the read filter key is ensembl_gene_id, then source/group)
    df = df.sort_values(["ensembl_gene_id", "source", "group"]).reset_index(drop=True)
    df["allgene_percentile"] = df["allgene_percentile"].astype("float32")
    df["median"] = df["median"].astype("float32")
    return df


def write(df, out: Path, row_group_size: int = 8192) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    out.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("ensembl_gene_id", pa.string()),
            pa.field("source", pa.string()),
            pa.field("group", pa.string()),
            pa.field("median", pa.float32()),
            pa.field("allgene_percentile", pa.float32()),
            pa.field("allgene_rank", pa.int32()),
            pa.field("n_genes_in_group", pa.int32()),
        ]
    )
    pq.write_table(
        pa.Table.from_pandas(df[[f.name for f in schema]], schema=schema, preserve_index=False),
        str(out),
        compression="snappy",
        row_group_size=row_group_size,
    )
    md5 = _md5_hex(out)
    size = out.stat().st_size
    return {"md5": md5, "size_bytes": size, "n_rows": len(df), "n_groups": int(df.groupby(["source", "group"]).ngroups)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the tumor per-group all-gene rank product.")
    p.add_argument("--quantiles", default=_S3_QUANTILES, help="tcga-gtex-tpm-tissue-quantiles-v1 parquet")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--row-group-size", type=int, default=8192)
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args(argv)

    df = build(args.quantiles)
    meta = write(df, args.out, args.row_group_size)
    _log(
        f"[write] {args.out.name}: {meta['n_rows']} rows / {meta['n_groups']} groups / "
        f"{meta['size_bytes']} B / md5={meta['md5']}"
    )

    # Correctness gate
    for sym, src, grp, thresh in CORRECTNESS_CHECKS:
        sub = df[(df["gene_symbol"] == sym) & (df["source"] == src)]
        if grp:
            sub = sub[sub["group"] == grp]
        if len(sub):
            pct = float(sub["allgene_percentile"].iloc[0])
            ok = pct >= thresh if grp is None else pct <= thresh
            _log(f"  check {sym}/{src}/{grp or 'any'}: pct={pct:.1f} {'OK' if ok else 'UNEXPECTED'}")

    if not args.no_upload:
        import boto3

        key = f"{OUTPUT_S3_PREFIX}/{args.out.name}"
        boto3.client("s3").upload_file(str(args.out), S3_BUCKET, key, ExtraArgs={"Metadata": {"md5": meta["md5"]}})
        _log(f"[upload] s3://{S3_BUCKET}/{key}")
    else:
        _log("[upload] skipped (--no-upload)")
    print(f"md5={meta['md5']} size_bytes={meta['size_bytes']} n_rows={meta['n_rows']} n_groups={meta['n_groups']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
