"""Producer for pancan-arm-cnv-per-sample-v1: read the TCGA PanCanAtlas GISTIC gene-level thresholded
matrix + sample→indication annotation from S3, derive the per-(sample,arm) call table + the
per-(arm,indication) frequency companion (pure logic in read.py), and write both parquets.

Run (materialization; needs onc-compbio read+write via the cbg profile):
  AWS_PROFILE=cbg python -m methods.pancan_arm_cnv.derive --out-dir /tmp/armcnv --upload
"""

from __future__ import annotations

import argparse
import io
import os
from pathlib import Path

import pandas as pd

from .read import _patient_of, build_arm_calls, build_arm_indication_freq

S3_BUCKET = "onc-compbio"
_SRC = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27"
GISTIC_KEY = f"{_SRC}/all_thresholded.by_genes_whitelisted.tsv"
SAMPLE_ANNOT_KEY = f"{_SRC}/merged_sample_quality_annotations.tsv"
OUT_PREFIX = "data-catalog/derived/pancan-arm-cnv-per-sample-v1"
DEFAULT_AWS_PROFILE = "cbg"

# candidate (barcode_col, indication_col) pairs in merged_sample_quality_annotations.tsv
_ANNOT_CANDIDATES = [
    ("patient_barcode", "cancer type"),
    ("patient_barcode", "cancer_type"),
    ("aliquot_barcode", "cancer type"),
    ("bcr_patient_barcode", "type"),
]


def _s3():
    import boto3

    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


def _read_bytes(key: str) -> bytes:
    return _s3().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()


def read_gistic() -> pd.DataFrame:
    return pd.read_csv(io.BytesIO(_read_bytes(GISTIC_KEY)), sep="\t", low_memory=False)


def read_indication_map() -> dict:
    """{patient_barcode -> indication} from merged_sample_quality_annotations.tsv. Tries the known
    barcode/cancer-type column pairs; raises with the real columns if none match (surfaces at
    materialization rather than silently emitting an empty map)."""
    df = pd.read_csv(io.BytesIO(_read_bytes(SAMPLE_ANNOT_KEY)), sep="\t", low_memory=False)
    for bcol, icol in _ANNOT_CANDIDATES:
        if bcol in df.columns and icol in df.columns:
            m = {}
            for _, r in df[[bcol, icol]].dropna().iterrows():
                m[_patient_of(str(r[bcol]))] = str(r[icol]).upper()
            return m
    raise KeyError(f"no known (barcode, cancer-type) columns in sample annot; have {list(df.columns)[:20]}")


def build_and_write(out_dir: Path, upload: bool = False, threshold: float = 0.5) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    gistic = read_gistic()
    arm_calls = build_arm_calls(gistic, threshold=threshold)
    freq = build_arm_indication_freq(arm_calls, read_indication_map())
    calls_path = out_dir / "pancan_arm_cnv_per_sample.parquet"
    freq_path = out_dir / "pancan_arm_cnv_indication_frequency.parquet"
    arm_calls.to_parquet(calls_path, index=False)
    freq.to_parquet(freq_path, index=False)
    written = {
        "per_sample": str(calls_path),
        "indication_frequency": str(freq_path),
        "n_sample_arm_rows": len(arm_calls),
        "n_arm_indication_rows": len(freq),
        "threshold": threshold,
    }
    if upload:
        # Only the per-sample table is the catalogued product; the per-(arm,indication) frequency is a
        # trivial GROUP-BY the SL find-mode scan computes on the fly, so it is NOT uploaded/manifested
        # (avoids an un-manifested S3 orphan). freq_path stays a local convenience output.
        _s3().upload_file(str(calls_path), S3_BUCKET, f"{OUT_PREFIX}/pancan_arm_cnv_per_sample.parquet")
        written["s3_uri"] = f"s3://{S3_BUCKET}/{OUT_PREFIX}/pancan_arm_cnv_per_sample.parquet"
    return written


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Derive pancan-arm-cnv-per-sample-v1 parquet(s).")
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--upload", action="store_true", help="also upload to s3://onc-compbio/.../derived/")
    args = p.parse_args(argv)
    info = build_and_write(args.out_dir, upload=args.upload, threshold=args.threshold)
    print(info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
