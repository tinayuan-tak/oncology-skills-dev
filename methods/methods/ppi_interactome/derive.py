"""ppi_interactome.derive — gene-sorted STRING high-confidence edge product (perf optimization).

WHY: the live reader streamed the full 83MB 9606.protein.links.v12.0.txt.gz per call to find one
protein's edges (~6.6s/call — measured). This derive pre-resolves STRING links into a parquet
PHYSICALLY SORTED by source gene_symbol (== the read key), with partner symbol + score already joined
from 9606.protein.info, and pre-filtered to high-confidence edges (combined_score >= 700). The reader
then does a predicate-pushdown `pq.read_table(filters=[("gene_symbol","==",target)])` that prunes to
the target's row-group(s) — dropping the 6.6s scan to sub-second. Gene-keyed-product invariant
(physically-sorted-on-read-key + query_optimization + pushdown), same pattern as the genomic-two-hit
+ tpm-long products.

The read OUTPUT is unchanged (same n_high_confidence_interactors + top_interactors); this is a pure
substrate reshape behind the identical read_target_summary interface.

Output: uniprot-string-hc-edges-per-gene-v1/string_hc_edges_per_gene_v1.parquet
  columns: gene_symbol (source, sort key), partner_symbol, combined_score
Only edges with combined_score >= 700 and BOTH endpoints resolvable to a symbol are kept (an
unresolvable ENSP partner is dropped — it can't be surfaced as a named interactor anyway).

Usage: python -m methods.ppi_interactome.derive --out /tmp/string_hc.parquet
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import sys
from pathlib import Path
from typing import Optional

S3_BUCKET = "onc-compbio"
_STRING_PREFIX = "data-catalog/sources/string/v12-human-snapshot-2026-06-30"
STRING_LINKS_KEY = f"{_STRING_PREFIX}/9606.protein.links.v12.0.txt.gz"
STRING_INFO_KEY = f"{_STRING_PREFIX}/9606.protein.info.v12.0.txt.gz"
DEFAULT_AWS_PROFILE = "cbg"
HIGH_CONFIDENCE = 700


def _boto3():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE
    import boto3

    return boto3.client("s3")


def _load_id_to_symbol() -> dict:
    raw = _boto3().get_object(Bucket=S3_BUCKET, Key=STRING_INFO_KEY)["Body"].read()
    out = {}
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            c = line.rstrip("\n").split("\t")
            if len(c) >= 2 and c[0].strip() and c[1].strip():
                out[c[0].strip()] = c[1].strip()
    return out


def build_payload(links_local: Optional[str] = None, info_local: Optional[str] = None):
    """Return the gene-sorted high-confidence edge DataFrame (gene_symbol, partner_symbol, combined_score)."""
    import pandas as pd

    id_to_sym = {} if info_local is None else None
    if info_local is not None:
        # test path: parse local info
        id_to_sym = {}
        with gzip.open(info_local, "rt") if str(info_local).endswith(".gz") else open(info_local) as fh:
            for line in fh:
                if line.startswith("#"):
                    continue
                c = line.rstrip("\n").split("\t")
                if len(c) >= 2:
                    id_to_sym[c[0].strip()] = c[1].strip()
    else:
        id_to_sym = _load_id_to_symbol()

    if links_local is not None:
        raw = Path(links_local).read_bytes()
    else:
        raw = _boto3().get_object(Bucket=S3_BUCKET, Key=STRING_LINKS_KEY)["Body"].read()

    rows = []
    with gzip.open(io.BytesIO(raw), "rt", encoding="utf-8", errors="replace") as fh:
        fh.readline()  # skip header: protein1 protein2 combined_score
        for line in fh:
            p1, p2, score = line.rstrip("\n").split(" ")
            s = int(score)
            if s < HIGH_CONFIDENCE:
                continue
            sym1 = id_to_sym.get(p1)
            sym2 = id_to_sym.get(p2)
            if not sym1 or not sym2:
                continue
            rows.append((sym1, sym2, s))
    df = pd.DataFrame(rows, columns=["gene_symbol", "partner_symbol", "combined_score"])
    # PHYSICAL sort on the read key (gene_symbol) — the pushdown depends on it.
    df = df.sort_values(["gene_symbol", "combined_score"], ascending=[True, False]).reset_index(drop=True)
    return df


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--links-local", default=None)
    ap.add_argument("--info-local", default=None)
    args = ap.parse_args(argv)
    df = build_payload(args.links_local, args.info_local)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # row_group_size tuned so a gene's edges land in 1-2 groups; sorted key → pushdown prunes.
    import pyarrow as pa
    import pyarrow.parquet as pq

    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), args.out, compression="snappy", row_group_size=50000)
    print(
        f"[ppi_string_derive] {len(df):,} HC edges, {df['gene_symbol'].nunique():,} source genes -> {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
