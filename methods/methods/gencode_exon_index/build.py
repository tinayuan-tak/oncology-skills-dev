"""Parse GENCODE v26 primary_assembly GTF once, emit per-exon Parquet.

Consumes the on-catalog GENCODE v26 GTF
(s3://onc-compbio/data-catalog/sources/gencode/gencode-v26-primary-assembly/
gencode.v26.primary_assembly.annotation.gtf.gz), parses every `exon` feature
row, and emits a compact per-exon Parquet.

Output schema (14 columns):
    gene_id             str  - unversioned Ensembl (ENSG00000...)
    gene_id_versioned   str  - versioned Ensembl (ENSG00000...N)
    gene_name           str  - HGNC symbol from GTF attributes
    gene_type           str  - protein_coding / lncRNA / miRNA / etc.
    transcript_id       str  - unversioned Ensembl (ENST00000...)
    transcript_id_versioned str
    transcript_name     str  - canonical transcript name if provided
    transcript_type     str  - protein_coding / processed_transcript / etc.
    exon_id             str  - unversioned Ensembl (ENSE00000...)
    exon_id_versioned   str
    exon_number         int32
    chrom               str  - chr1..chr22, chrX, chrY, chrM (matches GENCODE)
    start               int32 - 1-indexed inclusive (GTF convention)
    end                 int32 - 1-indexed inclusive
    strand              str  - '+' or '-'

Row layout: sorted by (gene_id, transcript_id, exon_number) for
predicate-pushdown-friendly reads.

Cohort: ~58,278 gene records × varying exon counts per transcript in GENCODE
v26. Expected row count: ~1.4-1.6M exon-in-transcript rows.

Usage:
    python -m methods.gencode_exon_index.build \\
        --gtf-gz /path/to/gencode.v26.primary_assembly.annotation.gtf.gz \\
        --out-parquet exon_index_v26.parquet
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys
from pathlib import Path

import pandas as pd

# Attribute-extractor: GENCODE v26 mixes quoted string values (`gene_id "ENSG…"`)
# with unquoted integer values (`exon_number 1;`, `level 2;`). Matching only
# quoted forms silently drops exon_number and level — see build history.
_ATTR_RE = re.compile(r'(\w+) (?:"([^"]*)"|(\S+?));')


def _parse_attrs(attr_str: str) -> dict[str, str]:
    """Return dict from a GTF v9 attributes field. Handles both `k "v";`
    (string) and `k v;` (numeric) forms — GENCODE mixes them."""
    out: dict[str, str] = {}
    for m in _ATTR_RE.finditer(attr_str):
        key = m.group(1)
        val = m.group(2) if m.group(2) is not None else m.group(3)
        out[key] = val
    return out


def parse_gtf_to_exon_index(gtf_gz_path: Path) -> pd.DataFrame:
    """Parse GENCODE v26 GTF; return per-exon-in-transcript DataFrame.

    Streams the file line-by-line; keeps a running list of dict rows.
    ~1.4M rows fits comfortably in memory as a DataFrame.
    """
    rows: list[dict] = []

    with gzip.open(gtf_gz_path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) < 9 or fields[2] != "exon":
                continue
            chrom = fields[0]
            start = int(fields[3])
            end = int(fields[4])
            strand = fields[6]
            attrs = _parse_attrs(fields[8])

            gene_id_versioned = attrs.get("gene_id", "")
            transcript_id_versioned = attrs.get("transcript_id", "")
            exon_id_versioned = attrs.get("exon_id", "")

            rows.append(
                {
                    "gene_id": gene_id_versioned.split(".")[0],
                    "gene_id_versioned": gene_id_versioned,
                    "gene_name": attrs.get("gene_name", ""),
                    "gene_type": attrs.get("gene_type", ""),
                    "transcript_id": transcript_id_versioned.split(".")[0],
                    "transcript_id_versioned": transcript_id_versioned,
                    "transcript_name": attrs.get("transcript_name", ""),
                    "transcript_type": attrs.get("transcript_type", ""),
                    "exon_id": exon_id_versioned.split(".")[0],
                    "exon_id_versioned": exon_id_versioned,
                    "exon_number": int(attrs.get("exon_number", "0") or "0"),
                    "chrom": chrom,
                    "start": start,
                    "end": end,
                    "strand": strand,
                }
            )

    df = pd.DataFrame(rows)
    df = df.astype(
        {
            "exon_number": "int32",
            "start": "int32",
            "end": "int32",
        }
    )
    df = df.sort_values(["gene_id", "transcript_id", "exon_number"], kind="stable").reset_index(drop=True)
    return df


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--gtf-gz", required=True, type=Path, help="Path to gencode.v26.primary_assembly.annotation.gtf.gz")
    ap.add_argument("--out-parquet", required=True, type=Path)
    args = ap.parse_args()

    df = parse_gtf_to_exon_index(args.gtf_gz)

    args.out_parquet.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(args.out_parquet, index=False, compression="snappy")

    print(f"[build] wrote {len(df):,} exon-in-transcript rows -> {args.out_parquet}", file=sys.stderr)
    print(f"[build] n_genes: {df['gene_id'].nunique():,}", file=sys.stderr)
    print(f"[build] n_transcripts: {df['transcript_id'].nunique():,}", file=sys.stderr)
    print(f"[build] n_unique_exons: {df['exon_id'].nunique():,}", file=sys.stderr)
    print(f"[build] size on disk: {args.out_parquet.stat().st_size:,} bytes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
