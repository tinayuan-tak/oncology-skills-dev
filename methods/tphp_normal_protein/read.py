"""tphp_normal_protein.read — TPHP normal-tissue PROTEIN abundance per target.

Streamed pushdown read of the derived per-gene product `normal-tissue-protein-abundance-per-gene-v1`
via a pyarrow S3FileSystem, pushing down the `gene_symbol` filter so only ONE gene's per-tissue rows
transit the wire (mirrors methods/collectri_tf_regulon/read.py — the gene_symbol-keyed pushdown
precedent). The product stores DETECTED-only rows (a (gene, tissue) with n_detected==0 is not stored),
so every row is a tissue where the protein was quantified in >=1 normal sample.

This reader is VERDICT-INERT: it emits a normal-tissue-protein comparator summary that the
tumor-selectivity skill DISPLAYS (no interpretation rule keys on any of these fields). It is the
quantitative NORMAL-tissue PROTEIN baseline the skill lacked — GTEx gives normal RNA, HPA gives
categorical IHC breadth; this gives DIA-MS protein abundance across 70 adult tissues + 4 fetal
germ-layer groups.

Absence discipline (mirrors the collectri reader): a GENUINE product-object absence (NoSuchKey/404
or FileNotFoundError) or a gene simply absent from the product → honest `data_unavailable`. A
transient / credential / broken-env error is RE-RAISED (never masked as an empty normal footprint)
so the live-read seam surfaces `_live_read_error` instead of a silent dead comparator.
"""
from __future__ import annotations

import statistics
import threading
from typing import Optional

from methods.catalog_query.read import bucket_key_for

DERIVED_MANIFEST_ID = "normal-tissue-protein-abundance-per-gene-v1"
METHOD_VERSION = "0.1.0"

# Denominators sourced from the derived manifest `parameters` block (n_adult_tissues / n_fetal_groups)
# — the population of normal-tissue groups the DIA-MS panel spans. Surfaced so a consumer can read
# "detected in K of N adult tissues" without a full-product scan (the per-gene pushdown only sees the
# gene's own rows). Breadth thresholds below are ABSOLUTE counts, so the denominator is informational.
N_ADULT_TISSUES_TOTAL = 70
N_FETAL_GROUPS_TOTAL = 4

# normal_protein_breadth_class thresholds on the count of ADULT tissues the protein is detected in
# (the safety-relevant breadth — fetal groups are developmental context, not an adult on-target-off-
# tumor footprint). ABSOLUTE counts against the ~70-adult-tissue panel.
BROAD_ADULT_TISSUE_COUNT = 35        # >=50% of adult tissues → broad normal-protein footprint
MODERATE_ADULT_TISSUE_COUNT = 10     # >=~15% → moderate

_FETAL_CLASS = "fetal"
_ADULT_CLASS = "adult_normal"


# ── streamed pushdown read (pyarrow S3FileSystem; no whole-file download) ─────────────────────
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region us-east-1, the onc-compbio bucket).
    Built once and shared (safe for concurrent reads — the parallel card-read pool relies on that).
    Mirrors methods/collectri_tf_regulon/read.py::_get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs
                _S3FS = pafs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_rows_from_derived(gene: str, product_path=None) -> list[dict]:
    """Streamed pushdown read of ONE gene's per-tissue rows from the derived product.

    Returns the list of row dicts (may be empty if the gene has no detected tissue). `product_path`
    (offline test seam): a local parquet bypasses S3. Raises on transient/creds/broken-env failure
    (NOT swallowed — the caller's boundary classifies a genuine 404/absence into data_unavailable)."""
    import pyarrow.parquet as pq
    filters = [("gene_symbol", "=", gene)]
    if product_path is not None:
        tbl = pq.read_table(str(product_path), filters=filters)
    else:
        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=filters)
    return tbl.to_pylist()


def _is_num(x) -> bool:
    import math
    return isinstance(x, (int, float)) and not (isinstance(x, float) and math.isnan(x))


def _breadth_class(n_adult: int) -> str:
    if n_adult >= BROAD_ADULT_TISSUE_COUNT:
        return "broad_normal_protein"
    if n_adult >= MODERATE_ADULT_TISSUE_COUNT:
        return "moderate_normal_protein"
    if n_adult >= 1:
        return "restricted_normal_protein"
    return "not_detected_in_normal_protein"   # rows exist but none adult (fetal-only detection)


def _fetal_vs_adult_flag(n_adult: int, n_fetal: int) -> str:
    if n_adult and n_fetal:
        return "adult_and_fetal"
    if n_adult:
        return "adult_only"
    if n_fetal:
        return "fetal_only"
    return "none"


def _empty_summary() -> dict:
    """The data_unavailable summary — gene absent from the product, or a genuine read fault. Every
    field the card declares is present (so a reader RENAME is caught by the card-field drift guard);
    the numerics are None/0 and the primary categorical is data_unavailable (honest coverage gap,
    NEVER read as a favorable / narrow normal footprint)."""
    return {
        "normal_protein_breadth_class": "data_unavailable",
        "n_tissues_detected": 0,
        "n_adult_tissues_detected": 0,
        "n_fetal_groups_detected": 0,
        "n_adult_tissues_total": N_ADULT_TISSUES_TOTAL,
        "n_fetal_groups_total": N_FETAL_GROUPS_TOTAL,
        "max_median_log2_abundance": None,
        "median_across_tissues_log2_abundance": None,
        "highest_abundance_tissue": None,
        "highest_abundance_tissue_class": None,
        "fetal_vs_adult_flag": "data_unavailable",
        "max_detection_rate": None,
        "uniprot_ac": None,
        "per_tissue_abundance": [],
        "method_version": METHOD_VERSION,
    }


def compute_summary(gene: str, rows: list[dict]) -> dict:
    """Build the normal-tissue-protein comparator summary from the gene's per-tissue rows."""
    if not rows:
        return _empty_summary()

    # Per-tissue records (the DISPLAY list) + the abundance / breadth aggregates. The product stores
    # detected-only rows, so each row is a (tissue, tissue_class) where the protein was quantified.
    per_tissue: list[dict] = []
    adult_tissues: set[str] = set()
    fetal_tissues: set[str] = set()
    for r in rows:
        tissue = r.get("tissue")
        tclass = r.get("tissue_class")
        med = r.get("median_log2_abundance")
        det = r.get("detection_rate")
        per_tissue.append({
            "tissue": tissue,
            "tissue_class": tclass,
            "median_log2_abundance": med if _is_num(med) else None,
            "median_intensity": r.get("median_intensity") if _is_num(r.get("median_intensity")) else None,
            "n_samples": r.get("n_samples"),
            "n_detected": r.get("n_detected"),
            "detection_rate": det if _is_num(det) else None,
        })
        if tclass == _FETAL_CLASS:
            fetal_tissues.add(tissue)
        else:
            adult_tissues.add(tissue)

    # Sort the display list by abundance descending (highest normal-tissue expression first).
    per_tissue.sort(key=lambda t: (t["median_log2_abundance"] is not None,
                                    t["median_log2_abundance"] or 0.0), reverse=True)

    abundances = [t["median_log2_abundance"] for t in per_tissue if t["median_log2_abundance"] is not None]
    det_rates = [t["detection_rate"] for t in per_tissue if t["detection_rate"] is not None]

    # Highest-abundance tissue (across adult + fetal): the top of the sorted display list with a value.
    top = next((t for t in per_tissue if t["median_log2_abundance"] is not None), None)

    n_adult = len(adult_tissues)
    n_fetal = len(fetal_tissues)

    # uniprot_ac: 1:1 with the gene in this product (no ;-joined groups); take the first row's value.
    uniprot_ac = rows[0].get("uniprot_ac")

    return {
        "normal_protein_breadth_class": _breadth_class(n_adult),
        "n_tissues_detected": len(adult_tissues | fetal_tissues),
        "n_adult_tissues_detected": n_adult,
        "n_fetal_groups_detected": n_fetal,
        "n_adult_tissues_total": N_ADULT_TISSUES_TOTAL,
        "n_fetal_groups_total": N_FETAL_GROUPS_TOTAL,
        "max_median_log2_abundance": max(abundances) if abundances else None,
        "median_across_tissues_log2_abundance": (
            round(statistics.median(abundances), 6) if abundances else None),
        "highest_abundance_tissue": top["tissue"] if top else None,
        "highest_abundance_tissue_class": top["tissue_class"] if top else None,
        "fetal_vs_adult_flag": _fetal_vs_adult_flag(n_adult, n_fetal),
        "max_detection_rate": max(det_rates) if det_rates else None,
        "uniprot_ac": uniprot_ac,
        "per_tissue_abundance": per_tissue,
        "method_version": METHOD_VERSION,
    }


def load_and_classify(gene: str, product_path=None) -> dict:
    """Full pipeline: pushdown-read the gene's per-tissue normal-protein rows → comparator summary."""
    rows = _read_rows_from_derived(gene, product_path=product_path)
    return compute_summary(gene, rows)


def read_target_summary(target: str, indication: Optional[str] = None, product_path=None) -> dict:
    """Per-target TPHP normal-tissue-protein comparator via streamed pushdown.

    Args:
        target: HGNC gene symbol (the product's `gene_symbol` pushdown key).
        indication: unused (a normal-tissue footprint is a gene-level property); accepted for the
            generic-dispatch contract signature but NOT consumed.
        product_path: offline test seam — a local parquet path bypasses S3.

    Returns:
        The normal-tissue-protein comparator summary. Never raises on target-not-found — returns
        normal_protein_breadth_class='data_unavailable'. A transient/creds/broken-env fault surfaces
        _live_read_error (so the compose path degrades honestly instead of crashing).
    """
    try:
        return load_and_classify(target, product_path=product_path)
    except Exception as e:  # noqa: BLE001
        # A GENUINE product-object absence (NoSuchKey/404 or FileNotFoundError) → honest
        # data_unavailable. A transient/creds/broken-env error must NOT be masked as an empty normal
        # footprint — re-raise so the live-read seam surfaces _live_read_error instead of a silent
        # dead comparator (mirrors collectri_tf_regulon.read).
        from methods.target_id_sidecar import is_definitively_absent
        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        out = _empty_summary()
        out["_live_read_error"] = "tphp_normal_protein_read_failed"
        out["_remediation"] = (
            f"Could not read the TPHP normal-tissue protein product ({DERIVED_MANIFEST_ID}) "
            f"for {target}: {e}")
        return out


def _main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="TPHP normal-tissue protein abundance for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--product-path", default=None, help="offline: local parquet path (bypasses S3)")
    args = ap.parse_args(argv)
    print(json.dumps(read_target_summary(args.target, product_path=args.product_path),
                     indent=2, default=str))


if __name__ == "__main__":
    _main()
