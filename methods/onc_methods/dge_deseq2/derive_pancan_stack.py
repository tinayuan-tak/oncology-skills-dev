"""dge_deseq2.derive_pancan_stack — build the pan-cancer stacked tumor-vs-normal product.

Slice C of the tumor_elevation_breadth vertical. Concatenates the 27 per-indication
`{indication}-dge-tumor-vs-normal-sensitivity-v1` products into ONE stacked parquet
(`pancan-dge-tumor-vs-normal-v1`) so an RNA breadth reader can count "elevated in K of
N indications" WITHOUT 27 S3 reads on the render path (the derived-product discipline).

Mirrors CPTAC's stacked shape (cptac-protein-tumor-vs-normal-per-cohort-v1): one row per
(indication, gene) with a leading `indication` column.

## Only vintage-stable signals survive (cell B removed, #727)

The RNA breadth "elevated" predicate keys off dominant_direction + cells_supporting + an
A/C-only magnitude — cells A (TCGA tumor-vs-adjacent) and C (tumor-vs-GTEx) mean the same
thing in every historical product. The ComBat-seq cell B was removed from the four-cell
pipeline in analysis-methods#727 (it re-ran cell A on the identical samples and corrupted
log2FC); newly-emitted per-indication products carry no log2fc_B/padj_B columns, and the
stack no longer reads or carries them. Older materialized products may still hold B columns
— the union projection below simply drops them (only `_UNION_COLUMNS` is retained).

## Not a recompute

This is pure metadata assembly over already-published DESeq2 outputs — no DESeq2 re-run.
A product missing a `_UNION_COLUMNS` entry is NaN-filled by the concat (union schema).
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

from onc_methods.dge_deseq2.config import (
    composite_indications,
    pancan_stack_excluded_from_roster,
    published_indications,
)

STACKED_PRODUCT_ID = "pancan-dge-tumor-vs-normal-v1"
STACKED_S3_PREFIX = f"data-catalog/derived/{STACKED_PRODUCT_ID}"
STACKED_PARQUET_KEY = f"{STACKED_S3_PREFIX}/pancan_dge_tumor_vs_normal.parquet"
S3_BUCKET = "onc-compbio"
DEFAULT_AWS_PROFILE = "cbg"

# The 27 published per-indication sensitivity products (the stack roster). Declared in
# config/indications.yaml (S1, #693) via `published: true`. Add a new indication there, not here.
_PUBLISHED_INDICATIONS = set(published_indications())

# The union of columns the stacked schema carries. A per-indication product missing any of
# these (an older one, or one whose cell C was skipped) is NaN-filled by the concat. Order is
# stable for the stacked schema. Cell B (log2fc_B/padj_B) was removed in #727 and is no longer
# carried — an older product's B columns are dropped by the projection below.
_UNION_COLUMNS = [
    "gene_symbol",
    "cells_ran",
    "cells_supporting",
    "dominant_direction",
    "sig_all_cells",
    "discordant",
    "log2fc_A",
    "padj_A",
    "log2fc_C",
    "padj_C",
    "max_abs_log2fc",
]

# Sensitivity products intentionally excluded from the pancan-stack roster (#791): they
# legitimately exist on S3 under a *-dge-tumor-vs-normal-sensitivity-v1 prefix but are NOT
# pancan members (NSCLC = pooled LUAD+LUSC composite; SCLC = different-method product).
# assert_roster_matches_published subtracts this set from the live S3 listing before diffing.
_EXCLUDED_FROM_ROSTER = pancan_stack_excluded_from_roster()

# Composite (OncoTree parent) indications that are the UNION of finer sibling cohorts also
# present in the stack. COADREAD = COAD (colon) ∪ READ (rectal): the SAME tumor samples feed
# all three per-indication DGE products (verified: the raw per-sample substrate has only COAD
# + READ, no COADREAD label, 0 samples under >1 study — COADREAD is built by merging the two).
# The stacked product deliberately keeps all three as separate per-indication SLICES (a
# per-indication LOOKUP legitimately wants any one of them), but a pan-cancer BREADTH roll-up
# that counts K-of-N indications must NOT count colorectal ~2× (COAD + READ + their union). At
# breadth-count time we DROP the composite whenever a child is present, keeping the finer
# COAD/READ granularity. Scan (2026-08-08) confirmed COADREAD is the ONLY composite in the
# 27-indication stack (NSCLC/GBMLGG/KIPAN/STES are absent — only their single-study children
# appear). Add a `composite_children:` entry in config/indications.yaml if a merged-parent
# indication ever lands alongside its children (S1, #693).
_COMPOSITE_INDICATIONS = composite_indications()


def _dedupe_overlapping_indications(rows: list) -> list:
    """Drop composite-parent indication rows whose finer children are also present.

    Prevents a breadth roll-up from double-counting the same underlying tumor samples when a
    merged OncoTree parent (e.g. COADREAD) and its children (COAD, READ) both appear in the
    stack. If neither child is present the composite is KEPT (it is then the only colorectal
    signal available). Rows for non-composite indications pass through untouched. Idempotent."""
    present = {str(r.get("indication")).upper() for r in rows}
    drop = {parent for parent, children in _COMPOSITE_INDICATIONS.items() if parent in present and (children & present)}
    if not drop:
        return rows
    return [r for r in rows if str(r.get("indication")).upper() not in drop]


from onc_methods.target_id_sidecar import ensure_aws_profile


def _sensitivity_s3_uri(indication: str) -> str:
    return (
        f"s3://{S3_BUCKET}/data-catalog/derived/"
        f"{indication.lower()}-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet"
    )


def all_indications() -> list[str]:
    """The 28 indications with a published sensitivity product (upper-case)."""
    return sorted(_PUBLISHED_INDICATIONS)


_SENSITIVITY_SUFFIX = "-dge-tumor-vs-normal-sensitivity-v1"


def list_published_sensitivity_indications(s3fs=None) -> set[str]:
    """List the published ``{indication}-dge-tumor-vs-normal-sensitivity-v1/`` product prefixes
    under ``s3://onc-compbio/data-catalog/derived/`` and return the set of indication codes
    (upper-case). ``s3fs`` is injectable for testing; defaults to a real pyarrow S3FileSystem."""
    import pyarrow.fs as pafs

    ensure_aws_profile()
    if s3fs is None:
        s3fs = pafs.S3FileSystem()
    base = f"{S3_BUCKET}/data-catalog/derived"
    selector = pafs.FileSelector(base, recursive=False, allow_not_found=True)
    inds: set[str] = set()
    for info in s3fs.get_file_info(selector):
        name = info.base_name  # last path segment = the product-dir name
        if name.endswith(_SENSITIVITY_SUFFIX):
            inds.add(name[: -len(_SENSITIVITY_SUFFIX)].upper())
    return inds


def assert_roster_matches_published(published: set[str] | None = None, s3fs=None) -> None:
    """Assert the declared ``_PUBLISHED_INDICATIONS`` roster matches the set of published
    sensitivity products. Raises on drift.

    Without this, the stack roster is a static 27-key set: a NEW sensitivity product that lands on
    S3 is silently omitted from the stack (``build_stack`` iterates ``all_indications()``), so the
    breadth reader keeps reporting ``n_indications_tested`` over the stale 27 and UNDER-counts
    ``fraction_elevated``. The roster is declared in config/indications.yaml (``published: true``)
    rather than auto-derived from S3 so a maintainer consciously adds a newly-published product.
    This assertion is that forcing function: it fails loud on either a published-but-undeclared
    indication or a declared-but-unpublished one.

    Some sensitivity products intentionally live on S3 but are NOT pancan-stack members (e.g.
    NSCLC's pooled LUAD+LUSC composite, SCLC's different-method product) — declared in
    ``config/indications.yaml`` (``pancan_stack_excluded_from_roster``, #791). Those are
    subtracted from the S3-published set before comparing, so a reviewed, intentional exclusion
    doesn't false-positive as roster drift; a genuinely new, undeclared prefix still raises."""
    if published is None:
        published = list_published_sensitivity_indications(s3fs=s3fs)
    published = published - _EXCLUDED_FROM_ROSTER
    declared = set(_PUBLISHED_INDICATIONS)
    undeclared = published - declared  # published on S3 but missing from the roster
    unpublished = declared - published  # in the roster but no published product
    if undeclared or unpublished:
        raise RuntimeError(
            "pancan-dge stack roster drift vs published "
            f"*{_SENSITIVITY_SUFFIX} prefixes: "
            f"published-but-undeclared={sorted(undeclared)} "
            "(add each to config/indications.yaml with published: true before rebuilding the stack); "
            f"declared-but-unpublished={sorted(unpublished)} "
            "(remove from the config or restore the product). The roster must stay in sync with "
            "the published sensitivity products so the RNA breadth reader's n_indications_tested is "
            "not stale."
        )


def build_stack(indications: list[str] | None = None):
    """Read each per-indication sensitivity parquet and concat into the stacked frame.

    Returns a pandas.DataFrame with a leading `indication` column and the union of the
    per-indication columns (`_UNION_COLUMNS`; an absent column NaN-filled). One row per
    (indication, gene). Never re-runs DESeq2.
    """
    import pandas as pd
    import pyarrow.fs as pafs
    import pyarrow.parquet as pq

    ensure_aws_profile()
    # Full-roster build (no explicit subset): verify the declared roster still matches the
    # published sensitivity products, so a newly-landed indication can't be silently dropped from the
    # stack (which would leave the breadth reader's n_indications_tested stale). An explicit subset
    # (indications=...) is a deliberate partial/test build and skips the drift check.
    if indications is None:
        assert_roster_matches_published()
    inds = indications or all_indications()
    s3 = pafs.S3FileSystem()
    frames = []
    for ind in inds:
        uri = _sensitivity_s3_uri(ind)
        path = uri[5:]  # strip s3://
        table = pq.read_table(path, filesystem=s3)
        df = table.to_pandas()
        # union-align to _UNION_COLUMNS: NaN-fill an absent column, and drop any extra a
        # product carries (e.g. an older product's log2fc_B/padj_B, removed in #727).
        for col in _UNION_COLUMNS:
            if col not in df.columns:
                df[col] = float("nan")
        df = df[_UNION_COLUMNS].copy()
        df.insert(0, "indication", ind)
        frames.append(df)
    stacked = pd.concat(frames, ignore_index=True)
    # Sort by (gene_symbol, indication) so pyarrow predicate pushdown on gene_symbol
    # prunes to ~1 row-group per gene (27 rows/gene × default row_group_size=64).
    stacked = stacked.sort_values(["gene_symbol", "indication"], kind="mergesort").reset_index(drop=True)
    return stacked


def write_stack(out_path: Path, indications: list[str] | None = None) -> dict:
    """Build the stack and write it to `out_path` (local parquet). Returns a summary dict
    (n_rows, n_indications, md5, size_bytes, per-indication row counts) for the manifest +
    a provenance sidecar. Deterministic (indications sorted)."""
    stacked = build_stack(indications)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    import pyarrow as pa
    import pyarrow.parquet as pq

    tbl = pa.Table.from_pandas(stacked, preserve_index=False)
    pq.write_table(tbl, out_path, compression="snappy", row_group_size=64)
    raw = out_path.read_bytes()
    per_ind = stacked.groupby("indication").size().to_dict()
    return {
        "product_id": STACKED_PRODUCT_ID,
        "out_path": str(out_path),
        "n_rows": int(len(stacked)),
        "n_indications": int(stacked["indication"].nunique()),
        "md5": hashlib.md5(raw).hexdigest(),
        "size_bytes": len(raw),
        "columns": list(stacked.columns),
        "rows_per_indication": {k: int(v) for k, v in sorted(per_ind.items())},
    }


# ---------------------------------------------------------------------------------------------
# RNA tumor-elevation breadth reader (Slice C-3) — the RNA analogue of the CPTAC protein breadth.
# ---------------------------------------------------------------------------------------------
# Reads the stacked product this module produces and rolls up "elevated in K of N indications"
# for one target. This is the additive SECOND input to the tumor_elevation_breadth measurement_type
# (alongside the CPTAC-protein reader) — breadth over INDICATIONS for one target (allowed), NOT a
# ranking over targets.
#
# THE A/C-ONLY PREDICATE (load-bearing): "elevated" keys off dominant_direction +
# cells_supporting + an A/C-ONLY magnitude — the surviving comparators (cell A = TCGA
# tumor-vs-adjacent, cell C = tumor-vs-GTEx). A gene is elevated in an indication iff it is
# up-dominant, supported by >=2 cells that ran, magnitude >=1.0, and NOT discordant.
#
# WHY A/C-ONLY (still load-bearing after #727 removed cell B): the ComBat-seq cell B was deleted
# from the four-cell pipeline in analysis-methods#727 — it re-ran cell A on the identical samples
# and both inflated/sign-flipped log2FC. But this reader reads the MATERIALIZED product, which was
# NOT rebuilt by #727, so an older product's rows can still carry log2fc_B/padj_B AND a
# `max_abs_log2fc` column built over all-cells-including-B.
#
# M2 FIX (2026-08-15): the magnitude gate previously read the `max_abs_log2fc` column, but that
# column is built in r/live/06_four_cell_driver.R as apply(abs(lfc_mat),1,max) over ALL ran cells,
# so on an older product it INCLUDES cell B — a gene elevated only via an inflated/sign-flipped
# ComBat cell B (the documented GAPDH COADREAD B=4.8 vs A=1.0/C=1.5 pattern) scored as
# tumor-elevated. The gate recomputes magnitude from cells A + C ONLY (max(|log2fc_A|,|log2fc_C|)),
# mirroring the sibling selectivity classifier's FIX 1 (read.py::classify_selectivity, raw_max_lfc
# over log2fc_cell_a/c). Backtested on the real materialized pancan-dge-tumor-vs-normal-v1 (38004
# genes): strictly monotone (A/C-max <= all-cells-max, so breadth can only DROP, never rise — 0
# up-flips), 1000 genes flip verdict downward, ALL housekeeping/passenger-like (the 61 losing
# `broadly` are ribosomal/glycolytic/pseudogenes); 82 validated onco/antigen targets (EPCAM/MSLN/
# ERBB2/FOLR1/TACSTD2/CEACAM5/NECTIN4/CD70/DLL3/...) unchanged — 0 dangerous false-negatives. The
# `max_abs_log2fc` column is retained in the stacked product (secondary magnitude signal for forest
# plots); breadth just no longer gates on it.

_RNA_STACKED_S3_URI = f"s3://{S3_BUCKET}/{STACKED_PARQUET_KEY}"
# The RNA "tumor-elevated in this indication" bar. NOTE (M4 — cross-modality bar asymmetry): this RNA
# magnitude bar (|log2fc| >= 1.0, supported by >=2 concordant cells, no separate q-gate on magnitude)
# is INTENTIONALLY DIFFERENT from the PROTEIN elevated bar in cptac_protein_deg/read.py (q < 0.05 AND
# effect >= 0.5). The asymmetry is by assay, not oversight: bulk RNA-seq has a lower dynamic range and
# the vintage-stable cells already encode direction+support, so a magnitude floor is the robust signal;
# CPTAC TMT-MS is significance-gated. Consequence a consumer must know: when the tumor-elevation-breadth
# card reports breadth_layer_concordance == "discordant", that can reflect this THRESHOLD asymmetry
# (the stricter RNA magnitude bar), not necessarily a biological RNA-vs-protein disagreement. Do not
# read "discordant" as "the biology conflicts". (The concordance label itself is derived skill-side in
# compose-dashboard/_live_readers.py::_breadth_layer_concordance.)
_RNA_ELEVATED_MIN_SUPPORTING = 2
_RNA_ELEVATED_MIN_LOG2FC = 1.0


def _rna_ac_max_log2fc(row: dict) -> float:
    """A/C-only magnitude: max(|log2fc_A|, |log2fc_C|) over cells A (TCGA-adjacent-raw) and
    C (GTEx-raw) ONLY — the surviving comparators. Mirrors the selectivity classifier's FIX 1
    (read.py raw_max_lfc). NaN/absent cells contribute nothing; empty -> 0.0."""
    vals = []
    for k in ("log2fc_A", "log2fc_C"):
        v = row.get(k)
        if isinstance(v, (int, float)) and v == v:  # not None, not NaN
            vals.append(abs(v))
    return max(vals) if vals else 0.0


def _rna_row_is_elevated(row: dict) -> bool:
    """'tumor-elevated in this indication' predicate. NEVER uses cell B (see the M2 FIX note
    above: the magnitude gate recomputes from cells A/C only, not max_abs_log2fc, which on an
    older materialized product was built over all cells including the removed ComBat cell B)."""
    if row.get("discordant"):
        return False
    if row.get("dominant_direction") != "up":
        return False
    supporting = row.get("cells_supporting") or 0
    ac_max_lfc = _rna_ac_max_log2fc(row)
    return supporting >= _RNA_ELEVATED_MIN_SUPPORTING and ac_max_lfc >= _RNA_ELEVATED_MIN_LOG2FC


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

    ensure_aws_profile()
    empty = {
        "rna_tumor_elevation_breadth_class": "data_unavailable",
        "n_indications_tested": 0,
        "n_indications_elevated": 0,
        "fraction_elevated": None,
        "median_max_log2fc_across_elevated": None,
        "most_elevated_indications": [],
        "indications_tested": [],
    }
    # pyarrow's S3FileSystem path is BUCKET-qualified (onc-compbio/data-catalog/...), NOT the
    # bare key — passing the key alone makes pyarrow read the first segment as the bucket (301).
    # Mirrors the sibling readers' _s3_uri_to_path (strips only the s3:// prefix, keeps bucket).
    read_path = _RNA_STACKED_S3_URI[len("s3://") :]
    try:
        s3 = pafs.S3FileSystem()
        table = pq.read_table(read_path, filesystem=s3, filters=[("gene_symbol", "=", target)])
    except Exception:
        return empty
    if table.num_rows == 0:
        return empty
    rows = table.to_pandas().to_dict(orient="records")

    # Drop composite-parent indications (COADREAD) when their children (COAD, READ) are also
    # present, so the K-of-N breadth roll-up does not double-count the same colorectal samples.
    # A per-indication LOOKUP keeps all slices; only this breadth COUNT dedupes. See
    # _COMPOSITE_INDICATIONS.
    rows = _dedupe_overlapping_indications(rows)

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
        (
            {
                "indication": r.get("indication"),
                "max_abs_log2fc": r.get("max_abs_log2fc"),
                "cells_supporting": r.get("cells_supporting"),
                "dominant_direction": r.get("dominant_direction"),
            }
            for r in elevated
        ),
        key=lambda x: x["max_abs_log2fc"] or 0.0,
        reverse=True,
    )

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
    ap.add_argument("--indications", nargs="*", default=None, help="subset of indications (default: all 27)")
    args = ap.parse_args()
    summary = write_stack(Path(args.out), indications=args.indications)
    print(json.dumps(summary, indent=2))
