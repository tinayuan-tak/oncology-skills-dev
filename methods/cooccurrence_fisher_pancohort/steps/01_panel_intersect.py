"""Stage 01 — GENIE panel-intersect gene set computation.

Emits the panel-intersect gene set for pan-cohort (PANCAN) pooling.
The BLOCKER-fix discipline (reviewer feedback 2026-07-08) requires
that pooled q-values be restricted to gene pairs where BOTH the target
and partner are covered on all GENIE panels contributing to the pool —
otherwise genes absent from GENIE panels are silently treated as
"not co-mutated" when the truth is "not sequenced."

## v1 strategy: intersection of the 8 largest workhorse panels

Full intersection across all 166 GENIE panels collapses toward the
smallest panels (~50-100 genes), which is too restrictive for the
downstream Phase-E differentiation-landscape use case. Practical
v1 heuristic: intersection of the 8 workhorse panels that cover the
majority of GENIE samples:

  - MSK-IMPACT341, MSK-IMPACT410, MSK-IMPACT468, MSK-IMPACT505
  - DFCI-ONCOPANEL-1, DFCI-ONCOPANEL-2, DFCI-ONCOPANEL-3, DFCI-ONCOPANEL-3.1
  - Foundation Medicine T7 (F1-T7) + DX1 (F1-DX1)

Emits `panel_intersect_by_cohort.tsv` with columns:
  cohort              str    'PANCAN' (v1) or per-cancer-type in future
  gene_symbol         str    HGNC symbol in the intersection
  in_msk_impact_505   bool
  in_dfci_op_3        bool
  ... (per-panel booleans for provenance)

## Reads

- s3://onc-compbio/data-catalog/sources/synapse/genie-public-v19-0/
    gene_panels/data_gene_panel_<PANEL_ID>.txt (166 files)
- s3://.../genie-public-v19-0/data_clinical_sample.txt (for panel usage stats)

## Writes

- <work_dir>/panel_intersect_by_cohort.tsv
- <work_dir>/panel_membership.parquet (full 166-panel × N-gene matrix
  for future refinement)

## Usage (called by derive.py)

    python -m methods.cooccurrence_fisher_pancohort.steps.01_panel_intersect \\
        --work-dir /path/to/work_dir

## v2 upgrade path (deferred)

Compute per-cohort panel-intersect using the actual cohort-to-panel
membership from data_gene_matrix.txt. Requires cohort labeling
(GENIE cancer types → TCGA study codes mapping). Not v1.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterable


DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
GENIE_PREFIX = "data-catalog/sources/synapse/genie-public-v19-0"

# The 8+ workhorse panels for pan-GENIE coverage (per plan).
# Panel IDs match filenames: data_gene_panel_<PANEL_ID>.txt.
WORKHORSE_PANELS = [
    # MSK-IMPACT series (Memorial Sloan Kettering)
    "MSK-IMPACT341",
    "MSK-IMPACT410",
    "MSK-IMPACT468",
    "MSK-IMPACT505",
    # DFCI ONCOPANEL series (Dana-Farber)
    "DFCI-ONCOPANEL-1",
    "DFCI-ONCOPANEL-2",
    "DFCI-ONCOPANEL-3",
    "DFCI-ONCOPANEL-3.1",
    # Foundation Medicine (F1)
    "VICC-01-T7",
    "VICC-01-D2",
]


def _boto3_client():
    import boto3
    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


def _parse_gene_panel_file(text: str) -> list[str]:
    """Parse a GENIE data_gene_panel_<ID>.txt file.

    Format is:
        stable_id: <panel_id>
        description: <human-readable panel description>
        gene_list: TP53 KRAS BRAF EGFR ... (space or tab separated)

    Returns the list of HGNC symbols in the panel.
    """
    genes = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("gene_list:"):
            # After the colon, gene symbols are whitespace-separated
            payload = line.split(":", 1)[1].strip()
            # Both spaces and tabs are used; normalize
            genes.extend(payload.split())
    return genes


def _list_panel_files(s3) -> list[str]:
    """List all data_gene_panel_*.txt keys under GENIE gene_panels/."""
    prefix = f"{GENIE_PREFIX}/gene_panels/"
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            if k.endswith(".txt"):
                keys.append(k)
    return keys


def _load_panel_genes(s3, keys: Iterable[str]) -> dict[str, list[str]]:
    """Load {panel_id: [gene_symbol, ...]} for all panel files."""
    panels: dict[str, list[str]] = {}
    for k in keys:
        # Panel ID from filename: data_gene_panel_<ID>.txt
        fname = Path(k).name
        panel_id = fname.replace("data_gene_panel_", "").replace(".txt", "")
        obj = s3.get_object(Bucket=S3_BUCKET, Key=k)
        text = obj["Body"].read().decode("utf-8", errors="replace")
        panels[panel_id] = _parse_gene_panel_file(text)
    return panels


def compute_intersection(panels: dict[str, list[str]]) -> tuple[set[str], dict[str, set[str]]]:
    """Compute the intersection of the workhorse panels.

    Returns (intersect_gene_set, per_panel_gene_sets).
    """
    per_panel = {pid: set(genes) for pid, genes in panels.items()}
    workhorse_present = [p for p in WORKHORSE_PANELS if p in per_panel]
    if len(workhorse_present) < 3:
        raise RuntimeError(
            f"Only {len(workhorse_present)} of {len(WORKHORSE_PANELS)} workhorse "
            f"panels found in GENIE. Found: {workhorse_present}. Check panel IDs."
        )
    intersect = set(per_panel[workhorse_present[0]])
    for pid in workhorse_present[1:]:
        intersect &= per_panel[pid]
    return intersect, per_panel


def write_panel_intersect_tsv(
    intersect: set[str], per_panel: dict[str, set[str]], out_path: Path
) -> None:
    """Write panel_intersect_by_cohort.tsv with per-panel membership booleans.

    v1: cohort column is 'PANCAN' for all rows.
    """
    workhorse_present = [p for p in WORKHORSE_PANELS if p in per_panel]
    header = ["cohort", "gene_symbol"] + [
        f"in_{p.replace('-', '_').replace('.', '_').lower()}" for p in workhorse_present
    ]
    with out_path.open("w") as f:
        f.write("\t".join(header) + "\n")
        for gene in sorted(intersect):
            row = ["PANCAN", gene]
            for pid in workhorse_present:
                row.append("TRUE" if gene in per_panel[pid] else "FALSE")
            f.write("\t".join(row) + "\n")


def write_panel_membership_parquet(
    per_panel: dict[str, set[str]], out_path: Path
) -> None:
    """Write panel_membership.parquet — full 166-panel × N-gene boolean matrix."""
    import pandas as pd
    all_genes = sorted(set().union(*per_panel.values()))
    all_panels = sorted(per_panel.keys())
    print(
        f"[01_panel_intersect] building membership matrix: "
        f"{len(all_genes):,} genes × {len(all_panels)} panels",
        file=sys.stderr,
    )
    rows = []
    for gene in all_genes:
        rec = {"gene_symbol": gene}
        for pid in all_panels:
            rec[pid] = gene in per_panel[pid]
        rows.append(rec)
    df = pd.DataFrame(rows)
    df.to_parquet(out_path, engine="pyarrow", compression="snappy", index=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--work-dir", required=True, type=Path)
    args = ap.parse_args(argv)
    args.work_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    print("[01_panel_intersect] loading GENIE panel files from S3...", file=sys.stderr)
    s3 = _boto3_client()
    keys = _list_panel_files(s3)
    print(f"[01_panel_intersect] found {len(keys)} panel files", file=sys.stderr)

    panels = _load_panel_genes(s3, keys)
    print(
        f"[01_panel_intersect] loaded {len(panels)} panels "
        f"({time.perf_counter()-t0:.1f}s)",
        file=sys.stderr,
    )

    intersect, per_panel = compute_intersection(panels)
    workhorse_present = [p for p in WORKHORSE_PANELS if p in per_panel]
    print(
        f"[01_panel_intersect] intersection of {len(workhorse_present)} workhorse "
        f"panels: {len(intersect):,} genes",
        file=sys.stderr,
    )
    print(f"[01_panel_intersect]   workhorse panels used: {workhorse_present}", file=sys.stderr)

    out_tsv = args.work_dir / "panel_intersect_by_cohort.tsv"
    write_panel_intersect_tsv(intersect, per_panel, out_tsv)
    print(f"[01_panel_intersect] wrote {out_tsv}", file=sys.stderr)

    out_parquet = args.work_dir / "panel_membership.parquet"
    write_panel_membership_parquet(per_panel, out_parquet)
    print(
        f"[01_panel_intersect] wrote {out_parquet} "
        f"({out_parquet.stat().st_size/1e6:.1f}MB)",
        file=sys.stderr,
    )

    print(
        f"[01_panel_intersect] DONE ({time.perf_counter()-t0:.1f}s total)",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
