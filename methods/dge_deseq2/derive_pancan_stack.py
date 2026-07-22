"""dge_deseq2.derive_pancan_stack — build the pan-cancer stacked tumor-vs-normal product.

Slice C of the tumor_elevation_breadth vertical. Concatenates the 27 per-indication
`{indication}-dge-tumor-vs-normal-sensitivity-v1` products into ONE stacked parquet
(`pancan-dge-tumor-vs-normal-v1`) so an RNA breadth reader can count "elevated in K of
N indications" WITHOUT 27 S3 reads on the render path (the derived-product discipline).

Mirrors CPTAC's stacked shape (cptac-protein-tumor-vs-normal-per-cohort-v1): one row per
(indication, gene), a leading `indication` column, and a `cell_b_semantics` provenance
column that records WHICH cell-B model each indication ran.

## The cell-B vintage hazard (why cell_b_semantics exists)

The 27 products were emitted in THREE vintages with DIFFERENT cell-B meanings — a naive
concat would silently conflate them:
  - deef28a (coadread, 2026-07-06): cell B = an unspecified design-comparison variant.
  - acb0179 (24 indications, 2026-07-15): cell B = tumor-vs-adjacent, ComBat-seq
    batch-corrected on TCGA tissue-source-site.
  - 927a556 (ucec, 2026-07-16): cell B SKIPPED (SKIP_CELL_B=1 — ComBat-seq hit a
    match_quantiles perf cliff). UCEC's parquet has NO log2fc_B/padj_B columns at all
    (cells_ran maxes at 2).

Consequence, enforced downstream: the RNA breadth "elevated" predicate MUST key off the
VINTAGE-STABLE signal (dominant_direction + cells_supporting + max_abs_log2fc, all of which
mean the same thing in every vintage — cells A/C are identical across vintages), NEVER off
cell B. `cell_b_semantics` is carried so a consumer that DOES want cell B can filter to one
vintage, but breadth does not.

## Not a recompute

This is pure metadata assembly over already-published DESeq2 outputs — no DESeq2 re-run,
values byte-identical to each per-indication emit. UCEC's missing cell-B columns are
NaN-filled by the concat (union schema), which is honest: cell B was not run there.
"""
from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

STACKED_PRODUCT_ID = "pancan-dge-tumor-vs-normal-v1"
STACKED_S3_PREFIX = f"data-catalog/derived/{STACKED_PRODUCT_ID}"
STACKED_PARQUET_KEY = f"{STACKED_S3_PREFIX}/pancan_dge_tumor_vs_normal.parquet"
S3_BUCKET = "onc-compbio"
DEFAULT_AWS_PROFILE = "cbg"

# The 27 per-indication sensitivity products → cell_b_semantics, ground-truthed from each
# manifest's git_commit (data-catalog/manifests/derived/{ind}-dge-tumor-vs-normal-sensitivity-v1.yaml).
# The DEFAULT for a new indication is combat_seq_tcga_tss (the acb0179 majority vintage); the two
# exceptions are listed explicitly. Keep this in sync if new indications land on a new vintage.
_COMBAT_TSS = "combat_seq_tcga_tss"
_INDICATION_CELL_B_SEMANTICS = {
    "COADREAD": "design_comparison_unspecified",   # deef28a 2026-07-06
    "UCEC": "cell_b_skipped",                       # 927a556 2026-07-16 (SKIP_CELL_B=1)
    # all others → combat_seq_tcga_tss (acb0179 2026-07-15)
    "ACC": _COMBAT_TSS, "BLCA": _COMBAT_TSS, "BRCA": _COMBAT_TSS, "CESC": _COMBAT_TSS,
    "COAD": _COMBAT_TSS, "ESCA": _COMBAT_TSS, "GBM": _COMBAT_TSS, "HNSC": _COMBAT_TSS,
    "KICH": _COMBAT_TSS, "KIRC": _COMBAT_TSS, "KIRP": _COMBAT_TSS, "LGG": _COMBAT_TSS,
    "LIHC": _COMBAT_TSS, "LUAD": _COMBAT_TSS, "LUSC": _COMBAT_TSS, "OV": _COMBAT_TSS,
    "PAAD": _COMBAT_TSS, "PCPG": _COMBAT_TSS, "PRAD": _COMBAT_TSS, "READ": _COMBAT_TSS,
    "SKCM": _COMBAT_TSS, "STAD": _COMBAT_TSS, "TGCT": _COMBAT_TSS, "THCA": _COMBAT_TSS,
    "UCS": _COMBAT_TSS,
}

# The union of columns any per-indication sensitivity parquet carries. UCEC lacks
# log2fc_B/padj_B; the concat fills them NaN. Order is stable for the stacked schema.
_UNION_COLUMNS = [
    "gene_symbol", "cells_ran", "cells_supporting", "dominant_direction",
    "sig_all_cells", "discordant",
    "log2fc_A", "padj_A", "log2fc_B", "padj_B", "log2fc_C", "padj_C",
    "max_abs_log2fc",
]


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _sensitivity_s3_uri(indication: str) -> str:
    return (f"s3://{S3_BUCKET}/data-catalog/derived/"
            f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet")


def all_indications() -> list[str]:
    """The 27 indications with a published sensitivity product (upper-case)."""
    return sorted(_INDICATION_CELL_B_SEMANTICS)


def build_stack(indications: list[str] | None = None):
    """Read each per-indication sensitivity parquet and concat into the stacked frame.

    Returns a pandas.DataFrame with a leading `indication` column, a `cell_b_semantics`
    provenance column, and the union of the per-indication columns (UCEC's absent cell-B
    columns NaN-filled). One row per (indication, gene). Never re-runs DESeq2.
    """
    import pandas as pd
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq

    _ensure_aws_profile()
    inds = indications or all_indications()
    s3 = pafs.S3FileSystem()
    frames = []
    for ind in inds:
        uri = _sensitivity_s3_uri(ind)
        path = uri[5:]  # strip s3://
        table = pq.read_table(path, filesystem=s3)
        df = table.to_pandas()
        # union-align columns (UCEC is missing log2fc_B/padj_B)
        for col in _UNION_COLUMNS:
            if col not in df.columns:
                df[col] = float("nan")
        df = df[_UNION_COLUMNS].copy()
        df.insert(0, "indication", ind)
        df["cell_b_semantics"] = _INDICATION_CELL_B_SEMANTICS.get(ind, _COMBAT_TSS)
        frames.append(df)
    stacked = pd.concat(frames, ignore_index=True)
    return stacked


def write_stack(out_path: Path, indications: list[str] | None = None) -> dict:
    """Build the stack and write it to `out_path` (local parquet). Returns a summary dict
    (n_rows, n_indications, md5, size_bytes, per-indication row counts, vintage counts)
    for the manifest + a provenance sidecar. Deterministic (indications sorted)."""
    stacked = build_stack(indications)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stacked.to_parquet(out_path, index=False)
    raw = out_path.read_bytes()
    per_ind = stacked.groupby("indication").size().to_dict()
    vintages = stacked.groupby("cell_b_semantics")["indication"].nunique().to_dict()
    return {
        "product_id": STACKED_PRODUCT_ID,
        "out_path": str(out_path),
        "n_rows": int(len(stacked)),
        "n_indications": int(stacked["indication"].nunique()),
        "md5": hashlib.md5(raw).hexdigest(),
        "size_bytes": len(raw),
        "columns": list(stacked.columns),
        "rows_per_indication": {k: int(v) for k, v in sorted(per_ind.items())},
        "indications_per_cell_b_semantics": {k: int(v) for k, v in sorted(vintages.items())},
    }


# ---------------------------------------------------------------------------------------------
# RNA tumor-elevation breadth reader (Slice C-3) — the RNA analogue of the CPTAC protein breadth.
# ---------------------------------------------------------------------------------------------
# Reads the stacked product this module produces and rolls up "elevated in K of N indications"
# for one target. This is the additive SECOND input to the tumor_elevation_breadth measurement_type
# (alongside the CPTAC-protein reader) — breadth over INDICATIONS for one target (allowed), NOT a
# ranking over targets.
#
# THE VINTAGE-STABLE PREDICATE (load-bearing): "elevated" keys off dominant_direction +
# cells_supporting + max_abs_log2fc — the signals that mean the SAME thing in every cell-B vintage
# (cells A/C are identical across vintages). It deliberately does NOT use cell B (log2fc_B/padj_B),
# which is design-comparison in COADREAD, ComBat-TSS in 24 indications, and ABSENT in UCEC. Using
# cell B would silently mis-score across vintages. A gene is elevated in an indication iff it is
# up-dominant, supported by >=2 cells that ran, magnitude >=1.0, and NOT discordant.

_RNA_STACKED_S3_URI = (f"s3://{S3_BUCKET}/{STACKED_PARQUET_KEY}")
_RNA_ELEVATED_MIN_SUPPORTING = 2
_RNA_ELEVATED_MIN_LOG2FC = 1.0


def _rna_row_is_elevated(row: dict) -> bool:
    """Vintage-stable 'tumor-elevated in this indication' predicate. NEVER uses cell B."""
    if row.get("discordant"):
        return False
    if row.get("dominant_direction") != "up":
        return False
    supporting = row.get("cells_supporting") or 0
    max_lfc = row.get("max_abs_log2fc") or 0.0
    return supporting >= _RNA_ELEVATED_MIN_SUPPORTING and max_lfc >= _RNA_ELEVATED_MIN_LOG2FC


@lru_cache(maxsize=64)
def read_rna_tumor_elevation_breadth(target: str) -> dict:
    """Pan-cancer RNA tumor-elevation breadth for a target across the 27 stacked indications.

    Reads the stacked pancan-dge-tumor-vs-normal-v1 product (ONE S3 read, predicate-pushed on
    gene_symbol) and rolls up K-of-N indications elevated.

    Memoized on `target` (retrieval-opt #4): previously opened a fresh pyarrow S3FileSystem +
    predicate-read the 44 MB product COLD on every call, with no cache (unlike the CPTAC + DepMap
    readers which cache). The breadth dispatcher calls this per render; caching makes a repeat query
    for the same target within a process free. Returns a plain dict (safe to share; the dispatcher
    reads it read-only). Mirrors the CPTAC-protein breadth
    reader's return shape (methods/cptac_protein_deg/read.py::read_tumor_elevation_breadth) so the
    two can fuse in the card:
        {rna_tumor_elevation_breadth_class, n_indications_tested, n_indications_elevated,
         fraction_elevated, median_max_log2fc_across_elevated, most_elevated_indications[],
         indications_tested[]}
    breadth_class ladder mirrors the protein reader:
        broadly_tumor_elevated  -> fraction_elevated >= 0.5 AND n_elevated >= 3
        multi_tumor_elevated    -> n_elevated >= 2
        single_tumor_elevated   -> n_elevated == 1
        not_tumor_elevated      -> tested >= 1, elevated 0
        data_unavailable        -> target absent from the stacked product / product unavailable
    """
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq

    _ensure_aws_profile()
    empty = {
        "rna_tumor_elevation_breadth_class": "data_unavailable",
        "n_indications_tested": 0, "n_indications_elevated": 0,
        "fraction_elevated": None, "median_max_log2fc_across_elevated": None,
        "most_elevated_indications": [], "indications_tested": [],
    }
    # pyarrow's S3FileSystem path is BUCKET-qualified (onc-compbio/data-catalog/...), NOT the
    # bare key — passing the key alone makes pyarrow read the first segment as the bucket (301).
    # Mirrors the sibling readers' _s3_uri_to_path (strips only the s3:// prefix, keeps bucket).
    read_path = _RNA_STACKED_S3_URI[len("s3://"):]
    try:
        s3 = pafs.S3FileSystem()
        table = pq.read_table(read_path, filesystem=s3,
                              filters=[("gene_symbol", "=", target)])
    except Exception:
        return empty
    if table.num_rows == 0:
        return empty
    rows = table.to_pandas().to_dict(orient="records")

    n_tested = len(rows)
    elevated = [r for r in rows if _rna_row_is_elevated(r)]
    n_elev = len(elevated)
    fraction = n_elev / n_tested if n_tested else None

    median_lfc = None
    if elevated:
        lfcs = sorted(float(r.get("max_abs_log2fc") or 0.0) for r in elevated)
        m = len(lfcs)
        median_lfc = lfcs[m // 2] if m % 2 else (lfcs[m // 2 - 1] + lfcs[m // 2]) / 2.0

    if fraction is not None and fraction >= 0.5 and n_elev >= 3:
        cls = "broadly_tumor_elevated"
    elif n_elev >= 2:
        cls = "multi_tumor_elevated"
    elif n_elev == 1:
        cls = "single_tumor_elevated"
    else:
        cls = "not_tumor_elevated"

    most_elevated = sorted(
        ({"indication": r.get("indication"),
          "max_abs_log2fc": r.get("max_abs_log2fc"),
          "cells_supporting": r.get("cells_supporting"),
          "dominant_direction": r.get("dominant_direction")} for r in elevated),
        key=lambda x: (x["max_abs_log2fc"] or 0.0), reverse=True)

    return {
        "rna_tumor_elevation_breadth_class": cls,
        "n_indications_tested": n_tested,
        "n_indications_elevated": n_elev,
        "fraction_elevated": fraction,
        "median_max_log2fc_across_elevated": median_lfc,
        "most_elevated_indications": most_elevated,
        "indications_tested": sorted(str(r.get("indication")) for r in rows),
    }


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Build pancan-dge-tumor-vs-normal-v1 stacked product.")
    ap.add_argument("--out", required=True, help="local output parquet path")
    ap.add_argument("--indications", nargs="*", default=None,
                    help="subset of indications (default: all 27)")
    args = ap.parse_args()
    summary = write_stack(Path(args.out), indications=args.indications)
    print(json.dumps(summary, indent=2))
