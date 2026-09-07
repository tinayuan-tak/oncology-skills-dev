#!/usr/bin/env python3
"""Re-sort the three derived parquets whose physical sort order didn't match their hot read-path
filter column.

Products addressed:
  1. pancan-dge-tumor-vs-normal-v1        → sort (gene_symbol, indication), row_group_size=64
  2. cptac-protein-tumor-vs-normal-per-cohort-v1 → sort (gene_symbol, cohort), row_group_size=64
  3. cptac-rna-protein-matched-per-sample-v1     → sort (gene, cohort, patient_id), row_group_size=4096

Reads from S3 (AWS_PROFILE=cbg), writes re-sorted parquet to /tmp/resort_out/, uploads back to the
same S3 key, prints new md5 + size_bytes for each. Safe to re-run (idempotent once re-sorted).

Usage:
    AWS_PROFILE=cbg python3 scripts/resort_sort_mismatch_products.py [--dry-run] [--product ID]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

S3_BUCKET = "onc-compbio"
AWS_PROFILE = "cbg"

PRODUCTS = [
    {
        "id": "pancan-dge-tumor-vs-normal-v1",
        "s3_key": "data-catalog/derived/pancan-dge-tumor-vs-normal-v1/pancan_dge_tumor_vs_normal.parquet",
        "sort_columns": ["gene_symbol", "indication"],
        "row_group_size": 64,
    },
    {
        "id": "cptac-protein-tumor-vs-normal-per-cohort-v1",
        "s3_key": "data-catalog/derived/cptac-protein-tumor-vs-normal-per-cohort-v1/cptac_protein_deg.parquet",
        "sort_columns": ["gene_symbol", "cohort"],
        "row_group_size": 64,
    },
    {
        "id": "cptac-rna-protein-matched-per-sample-v1",
        "s3_key": "data-catalog/derived/cptac-rna-protein-matched-per-sample-v1/cptac_rna_protein_matched.parquet",
        "sort_columns": ["gene", "cohort", "patient_id"],
        "row_group_size": 4096,
    },
]


def _md5(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def resort_product(product: dict, work_dir: Path, s3, dry_run: bool) -> dict:
    pid = product["id"]
    s3_key = product["s3_key"]
    sort_cols = product["sort_columns"]
    rg_size = product["row_group_size"]

    local_in = work_dir / f"{pid}_original.parquet"
    local_out = work_dir / f"{pid}_resorted.parquet"

    print(f"\n[{pid}] downloading from s3://{S3_BUCKET}/{s3_key} ...", flush=True)
    s3.download_file(S3_BUCKET, s3_key, str(local_in))
    in_size = local_in.stat().st_size
    print(f"[{pid}] downloaded {in_size:,} bytes", flush=True)

    print(f"[{pid}] reading + sorting by {sort_cols} ...", flush=True)
    tbl = pq.read_table(str(local_in))
    df = tbl.to_pandas()
    df = df.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)
    print(f"[{pid}] sorted {len(df):,} rows; writing row_group_size={rg_size} ...", flush=True)

    tbl_sorted = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(tbl_sorted, str(local_out), compression="snappy", row_group_size=rg_size)

    new_md5 = _md5(local_out)
    new_size = local_out.stat().st_size
    n_rg = pq.read_metadata(str(local_out)).num_row_groups
    print(f"[{pid}] re-sorted: {new_size:,} bytes, md5={new_md5}, {n_rg} row groups", flush=True)

    if dry_run:
        print(f"[{pid}] DRY RUN — skipping S3 upload", flush=True)
    else:
        print(f"[{pid}] uploading to s3://{S3_BUCKET}/{s3_key} ...", flush=True)
        s3.upload_file(str(local_out), S3_BUCKET, s3_key,
                       ExtraArgs={"Metadata": {"md5": new_md5}})
        print(f"[{pid}] upload complete", flush=True)

    return {"id": pid, "md5": new_md5, "size_bytes": new_size, "n_row_groups": n_rg}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="skip S3 upload")
    ap.add_argument("--product", default=None, help="run only this product id")
    ap.add_argument("--work-dir", type=Path, default=None,
                    help="local scratch dir (default: /tmp/resort_sort_mismatch)")
    args = ap.parse_args()

    os.environ.setdefault("AWS_PROFILE", AWS_PROFILE)
    session = boto3.Session(profile_name=AWS_PROFILE)
    s3 = session.client("s3")

    work_dir = args.work_dir or Path("/tmp/resort_sort_mismatch")
    work_dir.mkdir(parents=True, exist_ok=True)

    products = PRODUCTS if not args.product else [p for p in PRODUCTS if p["id"] == args.product]
    if not products:
        print(f"ERROR: unknown product {args.product!r}", file=sys.stderr)
        return 1

    results = []
    for product in products:
        result = resort_product(product, work_dir, s3, dry_run=args.dry_run)
        results.append(result)

    print("\n\n=== MANIFEST UPDATE SUMMARY ===")
    print("Copy these values into each manifest's md5: and size_bytes: fields,")
    print("then add the query_optimization block.\n")
    for r in results:
        print(f"id: {r['id']}")
        print(f"  md5: {r['md5']}")
        print(f"  size_bytes: {r['size_bytes']}")
        print(f"  n_row_groups: {r['n_row_groups']}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
