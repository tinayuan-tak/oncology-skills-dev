"""pooled_snv_recurrence.cli — materialize the pooled-snv-recurrence-v1 derived product.

Loops the requested indications, builds each per-gene pooled recurrence table (TCGA-MC3 + GENIE +
MSK-CHORD), concatenates into ONE pan-indication parquet (sort key gene_symbol), writes locally, and
(optionally) uploads to the derived-product S3 URI with an md5 metadata tag.

Usage:
    AWS_PROFILE=cbg python -m methods.pooled_snv_recurrence.cli \
        --indications COADREAD,NSCLC,PAAD,GC,BRCA,PRAD --out /tmp/pooled_recurrence.parquet
    # add --upload to push to s3://onc-compbio/data-catalog/derived/pooled-snv-recurrence-v1/recurrence.parquet
    DRY_RUN=1 ... --upload   # prints the S3 key + md5 without uploading
"""
from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from .read import build_pooled_recurrence_table, _schema

S3_BUCKET = "onc-compbio"
S3_KEY = "data-catalog/derived/pooled-snv-recurrence-v1/recurrence.parquet"
DEFAULT_INDICATIONS = ["COADREAD", "NSCLC", "PAAD", "GC", "BRCA", "PRAD"]


def build(indications: list[str]):
    """Concatenate per-indication pooled tables into one pan-indication pyarrow Table, sorted by
    (indication, gene_symbol). Indications with no rankable pooled gene contribute nothing (logged)."""
    import pyarrow as pa
    tables = []
    for ind in indications:
        tbl = build_pooled_recurrence_table(ind)
        print(f"  {ind}: {tbl.num_rows} pooled-covered genes", file=sys.stderr)
        if tbl.num_rows:
            tables.append(tbl)
    if not tables:
        return pa.Table.from_pylist([], schema=_schema())
    combined = pa.concat_tables(tables)
    order = pa.compute.sort_indices(combined, sort_keys=[("indication", "ascending"),
                                                         ("gene_symbol", "ascending")])
    return combined.take(order)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Materialize pooled-snv-recurrence-v1.")
    ap.add_argument("--indications", default=",".join(DEFAULT_INDICATIONS),
                    help="comma-separated framework indication codes")
    ap.add_argument("--out", required=True, type=Path, help="local parquet output path")
    ap.add_argument("--upload", action="store_true",
                    help="upload to the derived-product S3 URI (respects DRY_RUN=1)")
    args = ap.parse_args(argv)

    import pyarrow.parquet as pq
    indications = [s.strip() for s in args.indications.split(",") if s.strip()]
    print(f"building pooled recurrence for: {indications}", file=sys.stderr)
    tbl = build(indications)
    pq.write_table(tbl, args.out, compression="snappy")
    md5 = hashlib.md5(args.out.read_bytes()).hexdigest()
    print(f"wrote {tbl.num_rows} rows -> {args.out}  (md5 {md5}, {args.out.stat().st_size} bytes)")

    if args.upload:
        target = f"s3://{S3_BUCKET}/{S3_KEY}"
        if os.environ.get("DRY_RUN"):
            print(f"[DRY_RUN] would upload {args.out} -> {target}  (md5 {md5})")
            return 0
        import boto3
        s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "cbg")).client("s3")
        s3.upload_file(str(args.out), S3_BUCKET, S3_KEY, ExtraArgs={"Metadata": {"md5": md5}})
        print(f"uploaded -> {target}  (md5 {md5}). Hand-author manifests/derived/pooled-snv-recurrence-v1.yaml "
              f"with this md5 + size_bytes {args.out.stat().st_size} + cohort.n_rows {tbl.num_rows}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
