"""Build tcga-patient-cn-per-sample-v1 — per-(gene, patient) GISTIC discrete CN, LONG + gene-sorted.

    python -m methods.tcga_patient_cn_per_sample.build --out <dir>/tcga_patient_cn_per_sample.parquet [--no-upload]

Pipeline
--------
1. Read the PanCanAtlas GISTIC all_thresholded.by_genes_whitelisted.tsv (genes x DNA-aliquot
   columns; discrete calls in {-2,-1,0,1,2}).
2. Build the aliquot -> (case_barcode, sample_barcode) map from the column headers (barcode
   prefixes) and the case_barcode -> cancer_type map from merged_sample_quality_annotations
   (the SAME crosswalk tcga_patient_cn / tcga_aneuploidy_burden use).
3. Sort genes, then MELT in gene-chunks and stream to a ParquetWriter so the output is
   gene-sorted (predicate pushdown) without materializing the full 172M-row melt at once.
   One row per (gene_symbol, case_barcode): where a patient has >1 GISTIC aliquot, keep the
   first (matches tcga_patient_cn's "one tumour aliquot per patient" collapse).
4. Emit gene_symbol, case_barcode, sample_barcode, gistic_aliquot_barcode, gistic_call (int8),
   cancer_type. Deterministic: sorted, no timestamps -> stable md5.

Consumers join case_barcode <-> tcga-sample-id-crosswalk-v1.case_barcode to reach patient
expression (and methylation.patient_barcode directly).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
from pathlib import Path

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

S3_BUCKET = "onc-compbio"
PANCAN_PREFIX = "data-catalog/sources/gdc-pancanatlas/2018-snapshot-2026-06-27"
GISTIC_KEY = f"{PANCAN_PREFIX}/all_thresholded.by_genes_whitelisted.tsv"
SAMPLE_ANNOT_KEY = f"{PANCAN_PREFIX}/merged_sample_quality_annotations.tsv"
OUTPUT_S3_PREFIX = "data-catalog/derived/tcga-patient-cn-per-sample-v1"
DEFAULT_AWS_PROFILE = "cbg"

_META_COLS = {"Gene Symbol", "Locus ID", "Cytoband"}
_GENE_CHUNK = 2000  # genes per melt chunk (2000 x ~6900 = ~14M rows/chunk, bounded memory)

_SCHEMA = pa.schema(
    [
        pa.field("gene_symbol", pa.string()),
        pa.field("case_barcode", pa.string()),
        pa.field("sample_barcode", pa.string()),
        pa.field("gistic_aliquot_barcode", pa.string()),
        pa.field("gistic_call", pa.int8()),
        pa.field("cancer_type", pa.string()),
    ]
)


def _log(msg: str) -> None:
    print(msg, flush=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324  content-integrity only
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _s3(profile: str):
    return boto3.Session(profile_name=profile).client("s3")


def _barcode_to_case(aliquot: str) -> str:
    parts = str(aliquot).split("-")
    return "-".join(parts[:3]) if len(parts) >= 3 else str(aliquot)


def _barcode_to_sample(aliquot: str) -> str:
    parts = str(aliquot).split("-")
    return "-".join(parts[:4]) if len(parts) >= 4 else str(aliquot)


def _load_cancer_types(s3) -> dict[str, str]:
    raw = s3.get_object(Bucket=S3_BUCKET, Key=SAMPLE_ANNOT_KEY)["Body"].read()
    df = pd.read_csv(io.BytesIO(raw), sep="\t", usecols=["patient_barcode", "cancer type"], dtype=str)
    df = df.dropna(subset=["patient_barcode", "cancer type"])
    out = dict(zip(df["patient_barcode"], df["cancer type"]))
    if not out:
        raise ValueError("empty patient_barcode->cancer_type map (broken source, not a data gap)")
    return out


def build(out_path: Path, profile: str) -> dict:
    s3 = _s3(profile)
    _log("[1/4] reading GISTIC all_thresholded.by_genes (589 MB) …")
    raw = s3.get_object(Bucket=S3_BUCKET, Key=GISTIC_KEY)["Body"].read()
    df = pd.read_csv(io.BytesIO(raw), sep="\t", low_memory=False)
    sample_cols = [c for c in df.columns if c not in _META_COLS]
    _log(f"  {len(df):,} genes x {len(sample_cols):,} DNA aliquots")

    # aliquot -> case / sample barcode (computed once on the 6.9k column headers).
    col_case = {c: _barcode_to_case(c) for c in sample_cols}
    col_sample = {c: _barcode_to_sample(c) for c in sample_cols}
    cancer_types = _load_cancer_types(s3)

    # One tumour aliquot per patient: keep the FIRST column per case_barcode (deterministic in
    # header order) so the melt yields exactly one row per (gene, patient).
    seen_cases: set[str] = set()
    kept_cols: list[str] = []
    for c in sample_cols:
        case = col_case[c]
        if case in seen_cases:
            continue
        seen_cases.add(case)
        kept_cols.append(c)
    _log(
        f"  {len(kept_cols):,} aliquots kept (one per patient; dropped "
        f"{len(sample_cols) - len(kept_cols):,} duplicate-patient columns)"
    )

    df = df.rename(columns={"Gene Symbol": "gene_symbol"})
    df = df.dropna(subset=["gene_symbol"])
    df = df[["gene_symbol"] + kept_cols]
    genes_sorted = sorted(df["gene_symbol"].astype(str).unique())
    _log(f"[2/4] {len(genes_sorted):,} genes, melting in chunks of {_GENE_CHUNK} → {out_path}")

    writer = pq.ParquetWriter(str(out_path), _SCHEMA, compression="snappy")
    n_rows = 0
    df = df.set_index("gene_symbol")
    try:
        for i in range(0, len(genes_sorted), _GENE_CHUNK):
            chunk_genes = genes_sorted[i : i + _GENE_CHUNK]
            sub = df.loc[chunk_genes]  # gene rows for this chunk (index = gene_symbol)
            long = sub.reset_index().melt(
                id_vars=["gene_symbol"],
                value_vars=kept_cols,
                var_name="gistic_aliquot_barcode",
                value_name="gistic_call",
            )
            # keep only genuine integer calls; drop NaN/blank cells
            long = long[pd.to_numeric(long["gistic_call"], errors="coerce").notna()]
            long["gistic_call"] = long["gistic_call"].astype("int8")
            long["case_barcode"] = long["gistic_aliquot_barcode"].map(col_case)
            long["sample_barcode"] = long["gistic_aliquot_barcode"].map(col_sample)
            long["cancer_type"] = long["case_barcode"].map(cancer_types)
            long = long.sort_values(["gene_symbol", "case_barcode"])
            table = pa.Table.from_pandas(long[[f.name for f in _SCHEMA]], schema=_SCHEMA, preserve_index=False)
            writer.write_table(table)
            n_rows += len(long)
            _log(f"  genes {i:,}-{i + len(chunk_genes):,} → {n_rows:,} rows")
    finally:
        writer.close()

    md5, size = _md5_hex(out_path), out_path.stat().st_size
    _log(f"[3/4] wrote {n_rows:,} rows | {size / 1e6:.1f} MB | md5={md5}")
    return {
        "md5": md5,
        "size_bytes": size,
        "n_rows": n_rows,
        "n_genes": len(genes_sorted),
        "n_patients": len(kept_cols),
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build tcga-patient-cn-per-sample-v1 (gene-sorted long CN).")
    p.add_argument("--out", type=Path, required=True, help="local parquet output path")
    p.add_argument("--profile", default=DEFAULT_AWS_PROFILE)
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args(argv)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    meta = build(args.out, args.profile)

    if not args.no_upload:
        key = f"{OUTPUT_S3_PREFIX}/{args.out.name}"
        _s3(args.profile).upload_file(str(args.out), S3_BUCKET, key, ExtraArgs={"Metadata": {"md5": meta["md5"]}})
        _log(f"[4/4] uploaded → s3://{S3_BUCKET}/{key}")
    else:
        _log("[4/4] upload skipped (--no-upload)")
    print(
        f"md5={meta['md5']} size_bytes={meta['size_bytes']} n_rows={meta['n_rows']} "
        f"n_genes={meta['n_genes']} n_patients={meta['n_patients']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
