#!/usr/bin/env python3
"""Build the ccle-rrbs-promoter-methylation-MEAN-per-gene product.

Precomputes the exact per-(gene, cell-line) MEAN fractional-methylation that
`read._load_ccle_methylation_for_gene` derives on every per-gene call, so the reader can
predicate-pushdown ONE gene's rows (~kB over the wire) instead of streaming + parsing the whole
~40 MB CCLE_RRBS_TSS1kb gzip each call.

WHY A SEPARATE PRODUCT (not the existing ccle-rrbs-promoter-methylation-per-gene-v1): that product
carries MIN beta / is_methylated (a boolean silencing call for functional_gene_state's model arm).
The cellline-methylation-expression-coherence card instead needs the CONTINUOUS mean beta, which it
Spearman-correlates against expression — a boolean/min would not reproduce the correlation.

BYTE-EQUIVALENCE (the whole point): the live loop accumulates, per CCLE column, sum/count of the
gene's TSS-window betas (skipping blank/NaN), then `methyl_by_model[model] = sum/count` for each
column with count>0, mapping column→StrippedCellLineName→ModelID, LAST column winning on a ModelID
collision. This product stores per (gene_symbol, ccle_column, col_index) the same `sum/count` mean;
the reader replays the column-ordered map+last-wins with the caller's Model.csv, so the reconstructed
{ModelID: mean} — and hence the Spearman — is identical for any release (the stripped→ModelID bridge
stays in the reader, so the product is release-independent).

One streaming pass over the gzip (not one-pass-per-gene). Run with --upload to materialize to S3.
"""

from __future__ import annotations

import argparse
import gzip
import io
from pathlib import Path

from onc_methods.depmap_methylation_silencing.read import (
    CCLE_RRBS_TSS1KB_FILE,
    CCLE_SOURCE_MANIFEST_ID,
    DEFAULT_AWS_PROFILE,
)

_NAN_TOKENS = ("", "NaN", "NA", "nan")
_DERIVED_S3_URI = (
    "s3://onc-compbio/data-catalog/derived/"
    "ccle-rrbs-promoter-methylation-mean-per-gene-v1/promoter_methylation_mean.parquet"
)


def _open_ccle_stream():
    """Return a text stream over the CCLE RRBS TSS-1kb gzip (cbg role; frozen-creds trap handled)."""
    import boto3

    from onc_methods.catalog_query.read import bucket_prefix_for

    bucket, prefix = bucket_prefix_for(CCLE_SOURCE_MANIFEST_ID)
    key = f"{prefix.rstrip('/')}/{CCLE_RRBS_TSS1KB_FILE}"
    try:
        s3 = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")
    except Exception:
        s3 = boto3.client("s3")
    body = s3.get_object(Bucket=bucket, Key=key)["Body"]
    return io.TextIOWrapper(gzip.GzipFile(fileobj=body), encoding="utf-8")


def build_table():
    """Single streaming pass → long DataFrame [gene_symbol, ccle_column, col_index, mean_beta],
    sorted by (gene_symbol, col_index). mean_beta is float64 (matches the live sum/count)."""
    import pandas as pd

    text = _open_ccle_stream()
    header = text.readline().rstrip("\n").split("\t")
    cell_cols = header[3:]  # 0..2 = locus_id, CpG_sites_hg19, avg_coverage
    ncol = len(cell_cols)

    # gene -> [sums(ncol), counts(ncol)] accumulated across ALL of the gene's TSS rows/columns.
    sums: dict[str, list[float]] = {}
    counts: dict[str, list[int]] = {}
    for line in text:
        parts = line.rstrip("\n").split("\t")
        # locus_id = GENE_chr_start_end → gene is everything before the trailing chr_start_end.
        gene = parts[0].rsplit("_", 3)[0]
        if gene not in sums:
            sums[gene] = [0.0] * ncol
            counts[gene] = [0] * ncol
        s_arr, c_arr = sums[gene], counts[gene]
        for i, v in enumerate(parts[3 : 3 + ncol]):
            s = v.strip()
            if s in _NAN_TOKENS:
                continue
            try:
                fv = float(s)
            except ValueError:
                continue
            if fv != fv:  # residual NaN guard
                continue
            s_arr[i] += fv
            c_arr[i] += 1

    rows = []
    for gene in sums:
        s_arr, c_arr = sums[gene], counts[gene]
        for i in range(ncol):
            if c_arr[i] > 0:
                rows.append((gene, cell_cols[i], i, s_arr[i] / c_arr[i]))

    df = pd.DataFrame(rows, columns=["gene_symbol", "ccle_column", "col_index", "mean_beta"])
    df["col_index"] = df["col_index"].astype("int32")
    df["mean_beta"] = df["mean_beta"].astype("float64")
    df = df.sort_values(["gene_symbol", "col_index"], kind="stable").reset_index(drop=True)
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="/tmp/promoter_methylation_mean.parquet", help="local parquet output path")
    ap.add_argument("--upload", action="store_true", help="upload to the derived S3 URI (cbg)")
    args = ap.parse_args()

    import pyarrow as pa
    import pyarrow.parquet as pq

    df = build_table()
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, args.out, compression="snappy", row_group_size=500_000)
    n_genes = df["gene_symbol"].nunique()
    print(f"wrote {args.out}: {len(df):,} rows / {n_genes:,} genes / {df['ccle_column'].nunique()} columns")

    if args.upload:
        import boto3

        path = _DERIVED_S3_URI.replace("s3://", "", 1)
        bucket, _, key = path.partition("/")
        try:
            s3 = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")
        except Exception:
            s3 = boto3.client("s3")
        s3.upload_file(args.out, bucket, key)
        import hashlib

        md5 = hashlib.md5(Path(args.out).read_bytes()).hexdigest()
        print(f"uploaded → {_DERIVED_S3_URI}\n  md5={md5}  size_bytes={Path(args.out).stat().st_size}")


if __name__ == "__main__":
    main()
