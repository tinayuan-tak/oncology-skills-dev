#!/usr/bin/env python3
"""Build the reactome-pathway-per-uniprot product.

Precomputes the per-UniProt-AC Reactome pathway rows analysis-methods reactome_pathway_context
derives, with the top-level-pathway rollup already WALKED in, so read_target_summary can
predicate-pushdown ONE accession's rows (~kB) instead of downloading + parsing the whole 117 MB
UniProt2Reactome (all species) + the pathway hierarchy on cold start (all lru + disk cached, so this
is a per-PROCESS cold-start win, not a per-target one).

BYTE-EQUIVALENT to the live path: rows preserve the per-AC source ORDER (row_order) so the reader's
`pathways[:20]` specific_pathways slice is identical; top_level_pathway_name = id_to_name.get(
_walk_to_top(pathway_id), top_pid) exactly as the live rollup computes it. The reader rebuilds the
ordered pathway list + the top-level name set from the AC's rows; classification, is_signaling and
the emitted fields are unchanged.

Run with --upload to materialize to S3.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from methods.reactome_pathway_context.read import (
    _load_uniprot_to_reactome, _load_pathway_hierarchy, _walk_to_top, DEFAULT_AWS_PROFILE,
)

_DERIVED_S3_URI = ("s3://onc-compbio/data-catalog/derived/"
                   "reactome-pathway-per-uniprot-v1/reactome_pathway_per_uniprot.parquet")


def build_table():
    """Long DataFrame [uniprot_ac, row_order, pathway_id, pathway_name, evidence_code, url,
    top_level_pathway_name], sorted by (uniprot_ac, row_order)."""
    import pandas as pd
    from methods.target_id_sidecar import ensure_aws_profile
    ensure_aws_profile()
    uniprot_map = _load_uniprot_to_reactome()          # {AC: [{pathway_id, pathway_name, evidence_code, url}]}
    id_to_name, child_to_parent = _load_pathway_hierarchy()
    top_cache: dict[str, str] = {}                     # pathway_id -> top-level pathway NAME (memoized)

    def _top_name(pid: str) -> str:
        if pid not in top_cache:
            top_pid = _walk_to_top(pid, child_to_parent)
            top_cache[pid] = id_to_name.get(top_pid, top_pid)
        return top_cache[pid]

    rows = []
    for ac, pathways in uniprot_map.items():
        for i, p in enumerate(pathways):               # preserve source order for specific_pathways[:20]
            rows.append((ac, i, p["pathway_id"], p["pathway_name"], p["evidence_code"],
                         p["url"], _top_name(p["pathway_id"])))
    df = pd.DataFrame(rows, columns=["uniprot_ac", "row_order", "pathway_id", "pathway_name",
                                     "evidence_code", "url", "top_level_pathway_name"])
    df["row_order"] = df["row_order"].astype("int32")
    df = df.sort_values(["uniprot_ac", "row_order"], kind="stable").reset_index(drop=True)
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="/tmp/reactome_pathway_per_uniprot.parquet")
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args()

    import pyarrow as pa
    import pyarrow.parquet as pq
    df = build_table()
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), args.out,
                   compression="snappy", row_group_size=200_000)
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
