#!/usr/bin/env python3
"""Build the go-annotation-per-uniprot product.

Precomputes the per-UniProt-AC GO annotations analysis-methods gene_ontology_annotation derives, with
the OBO term NAME already joined in, so read_target_summary can predicate-pushdown ONE accession's
rows (~kB) instead of downloading + parsing the whole 15 MB GAF + 32 MB OBO on cold start (both are
lru-cached, so this is a per-PROCESS cold-start win, not a per-target one).

BYTE-EQUIVALENT to the live path: rows are the SAME deduped (AC, go_id, namespace) → evidence set the
reader's `_load_gaf` produces (this reuses it), and go_name = obo_names.get(go_id, go_id) exactly as
the reader's `_top` computes it. The reader rebuilds terms + a names map from the AC's rows; grouping,
counts, `_top` ranking and annotation_class are unchanged, so the summary is identical.

Run with --upload to materialize to S3.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from methods.gene_ontology_annotation.read import _load_gaf, _load_obo_names, DEFAULT_AWS_PROFILE

_DERIVED_S3_URI = "s3://onc-compbio/data-catalog/derived/go-annotation-per-uniprot-v1/go_annotation_per_uniprot.parquet"


def build_table():
    """Long DataFrame [uniprot_ac, go_id, namespace, evidence, go_name], sorted by uniprot_ac."""
    import pandas as pd
    from methods.target_id_sidecar import ensure_aws_profile

    ensure_aws_profile()
    gaf = _load_gaf()  # {AC: [{go_id, namespace, evidence}]} (deduped, live logic)
    names = _load_obo_names()  # {go_id: term name}
    rows = []
    for ac, terms in gaf.items():
        for t in terms:
            gid = t["go_id"]
            rows.append((ac, gid, t["namespace"], t["evidence"], names.get(gid, gid)))
    df = pd.DataFrame(rows, columns=["uniprot_ac", "go_id", "namespace", "evidence", "go_name"])
    df = df.sort_values("uniprot_ac", kind="stable").reset_index(drop=True)
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="/tmp/go_annotation_per_uniprot.parquet")
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()

    import pyarrow as pa
    import pyarrow.parquet as pq

    df = build_table()
    pq.write_table(
        pa.Table.from_pandas(df, preserve_index=False), args.out, compression="snappy", row_group_size=200_000
    )
    print(f"wrote {args.out}: {len(df):,} rows / {df['uniprot_ac'].nunique():,} accessions")

    if args.upload:
        import boto3
        import hashlib

        path = _DERIVED_S3_URI.replace("s3://", "", 1)
        bucket, _, key = path.partition("/")
        try:
            s3 = boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")
        except Exception:
            s3 = boto3.client("s3")
        s3.upload_file(args.out, bucket, key)
        md5 = hashlib.md5(Path(args.out).read_bytes()).hexdigest()
        print(f"uploaded → {_DERIVED_S3_URI}\n  md5={md5}  size_bytes={Path(args.out).stat().st_size}")


if __name__ == "__main__":
    main()
