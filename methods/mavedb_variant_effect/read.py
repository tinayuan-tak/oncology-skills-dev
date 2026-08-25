"""mavedb_variant_effect.read — MEASURED multiplexed variant-effect (MAVE/DMS/SGE) per target.

Streamed pushdown read of the derived per-gene product `mavedb-variant-effect-per-gene-v1` via a
pyarrow S3FileSystem, pushing down the `gene_symbol` filter so only ONE gene's row transits the
wire (mirrors methods/tphp_normal_protein/read.py — the gene_symbol-keyed pushdown precedent). The
product's grain is one row per gene_symbol, so the pushdown returns 0 or 1 row.

VERDICT-INERT: this reader emits a measured-variant-effect summary that the genomic-alteration-profile
skill DISPLAYS (no interpretation rule keys any of these fields, no resolver rung). It is the
MEASURED functional axis complementing CIViC's curated CLINICAL interpretation (variant-level-
interpretation) and the gene-level alteration-role.

Absence discipline (mirrors tphp_normal_protein / collectri):
  * a GENUINE product-object absence (NoSuchKey/404 or FileNotFoundError) → honest `data_unavailable`
    (a coverage/read fault, never read as "not assayed");
  * a gene ABSENT from the product → the weak-negative `not_assayed` (measured absence of MAVE
    evidence — NOT a data fault); a matched-but-unmapped row (raw non-HGNC MAVEdb target name that
    still carries assay data) → `mave_unmapped_target` (surfaced with its counts, out of the clean
    HGNC universe — never a silent `not_assayed` on a gene that plainly was assayed);
  * a transient / credential / broken-env error is RE-RAISED (never masked as an empty footprint)
    so the live-read seam surfaces `_live_read_error` instead of a silent dead comparator.

Score SCALES ARE PER-ASSAY and not cross-comparable, and per-assay LoF calibration thresholds are
published for only a small minority of score sets — so we surface the pooled raw distribution
summary (score_min/median/max), NOT a thresholded functional-abnormal call (documented in the
product manifest, not a gap).
"""
from __future__ import annotations

import threading
from typing import Optional

from methods.catalog_query.read import bucket_key_for

DERIVED_MANIFEST_ID = "mavedb-variant-effect-per-gene-v1"
METHOD_VERSION = "0.1.0"

# mave_evidence_class thresholds on the count of distinct MAVE score sets assaying the gene (only
# HGNC-mapped rows count — the clean human-gene universe the product manifest steers toward).
WELL_CHARACTERIZED_SCORE_SETS = 2   # >=2 independent MAVE score sets → mave_well_characterized


# ── streamed pushdown read (pyarrow S3FileSystem; no whole-file download) ─────────────────────
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region us-east-1, the onc-compbio bucket).
    Built once and shared (safe for concurrent reads — the parallel card-read pool relies on that).
    Mirrors methods/tphp_normal_protein/read.py::_get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs
                _S3FS = pafs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_rows_from_derived(gene: str, product_path=None) -> list[dict]:
    """Streamed pushdown read of ONE gene's row from the derived product.

    Returns the list of row dicts (0 or 1 — the product grain is one row per gene_symbol).
    `product_path` (offline test seam): a local parquet bypasses S3. Raises on transient/creds/
    broken-env failure (NOT swallowed — the caller's boundary classifies a genuine 404/absence)."""
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


def _num_or_none(x):
    return x if _is_num(x) else None


def _int_or_zero(x) -> int:
    return int(x) if _is_num(x) else 0


def _evidence_class(has_hgnc_mapping: bool, n_score_sets: int) -> str:
    """MEASURED-evidence strength on the MAVE axis. Only HGNC-mapped rows count as CLEAN human-gene
    MAVE evidence (the product manifest steers target profiling to has_hgnc_mapping=true and treats
    raw-name rows as out-of-universe assay context). A matched-but-unmapped row (a raw MAVEdb target
    name that carries assay data but no HGNC mapping — e.g. score sets deposited without a mappedHgnc
    name, as happens for some heavily-assayed human genes) is surfaced as `mave_unmapped_target`, a
    weak-negative on the clean-universe axis that STILL reports the assay counts (never silently a
    'not_assayed' on a gene that plainly was assayed)."""
    if not has_hgnc_mapping:
        return "mave_unmapped_target"     # a raw non-HGNC MAVEdb target-name row (out of the clean universe)
    if n_score_sets >= WELL_CHARACTERIZED_SCORE_SETS:
        return "mave_well_characterized"
    if n_score_sets >= 1:
        return "mave_assayed"
    return "not_assayed"


def _not_assayed_summary() -> dict:
    """The weak-negative summary — the gene has NO HGNC-mapped MAVE score set (absent from the
    product, or only a raw non-HGNC target-name row matched). MEASURED absence of MAVE evidence for
    the clean human gene, NOT a data/read fault. Every card-declared field present (so a reader
    RENAME is caught by the card-field drift guard); numerics 0/None."""
    return {
        "mave_evidence_class": "not_assayed",
        "has_hgnc_mapping": False,
        "n_score_sets": 0,
        "n_variants_assayed": 0,
        "n_variants_scored": 0,
        "score_min": None,
        "score_median": None,
        "score_max": None,
        "target_categories": None,
        "urns": None,
        "mave_context": "no HGNC-mapped MAVEdb functional-assay evidence for this gene",
        "method_version": METHOD_VERSION,
    }


def _unavailable_summary() -> dict:
    """The data_unavailable summary — a genuine product-object absence / read fault (NOT a measured
    'not assayed'). Distinct primary categorical so a coverage gap never reads as measured absence."""
    out = _not_assayed_summary()
    out["mave_evidence_class"] = "data_unavailable"
    out["mave_context"] = "MAVEdb variant-effect product could not be read (coverage/read fault)"
    return out


def compute_summary(gene: str, rows: list[dict]) -> dict:
    """Build the measured-variant-effect comparator summary from the gene's product row(s)."""
    if not rows:
        return _not_assayed_summary()

    r = rows[0]   # grain = one row per gene_symbol; pushdown returns at most one
    has_map = bool(r.get("has_hgnc_mapping"))
    n_score_sets = _int_or_zero(r.get("n_score_sets"))
    n_assayed = _int_or_zero(r.get("n_variants_assayed"))
    n_scored = _int_or_zero(r.get("n_variants_scored"))
    cls = _evidence_class(has_map, n_score_sets)

    if cls == "mave_unmapped_target":
        # A row matched but it is out-of-HGNC-universe (raw MAVEdb target name) — surface the raw
        # assay counts for transparency, but flag it as not a clean human-gene HGNC mapping.
        context = (f"MAVEdb row present for '{gene}' ({n_score_sets} score set(s), {n_scored} variants "
                   f"scored) but NOT HGNC-mapped — out-of-universe raw target name, not counted as "
                   f"clean human-gene MAVE evidence")
    else:
        context = (f"{n_score_sets} MAVE score set(s) assaying {gene}: "
                   f"{n_scored} of {n_assayed} variants scored (pooled per-assay functional scores)")

    return {
        "mave_evidence_class": cls,
        "has_hgnc_mapping": has_map,
        "n_score_sets": n_score_sets,
        "n_variants_assayed": n_assayed,
        "n_variants_scored": n_scored,
        # per-assay scale, nullable — NOT cross-comparable, NOT a thresholded LoF call.
        "score_min": _num_or_none(r.get("score_min")),
        "score_median": _num_or_none(r.get("score_median")),
        "score_max": _num_or_none(r.get("score_max")),
        "target_categories": r.get("target_categories") if isinstance(r.get("target_categories"), str) else None,
        "urns": r.get("urns") if isinstance(r.get("urns"), str) else None,
        "mave_context": context,
        "method_version": METHOD_VERSION,
    }


def load_and_classify(gene: str, product_path=None) -> dict:
    """Full pipeline: pushdown-read the gene's MAVE row → measured-variant-effect summary."""
    rows = _read_rows_from_derived(gene, product_path=product_path)
    return compute_summary(gene, rows)


def read_target_summary(target: str, indication: Optional[str] = None, product_path=None) -> dict:
    """Per-target MAVEdb measured-variant-effect comparator via streamed pushdown.

    Args:
        target: HGNC gene symbol (the product's `gene_symbol` pushdown key).
        indication: unused (a gene's MAVE functional-assay footprint is a gene-level property);
            accepted for the generic-dispatch contract signature but NOT consumed.
        product_path: offline test seam — a local parquet path bypasses S3.

    Returns:
        The measured-variant-effect summary. Never raises on target-not-found — returns
        mave_evidence_class='not_assayed' (measured absence). A genuine 404-class product fault →
        mave_evidence_class='data_unavailable' + _live_read_error. A transient/creds/broken-env
        fault is RE-RAISED (so the compose path degrades honestly instead of masking infra failure).
    """
    try:
        return load_and_classify(target, product_path=product_path)
    except Exception as e:  # noqa: BLE001
        # A GENUINE product-object absence (NoSuchKey/404 or FileNotFoundError) → honest
        # data_unavailable. A transient/creds/broken-env error must NOT be masked as an empty
        # footprint — re-raise so the live-read seam surfaces _live_read_error instead of a silent
        # dead comparator (mirrors tphp_normal_protein.read).
        from methods.target_id_sidecar import is_definitively_absent
        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        out = _unavailable_summary()
        out["_live_read_error"] = "mavedb_variant_effect_read_failed"
        out["_remediation"] = (
            f"Could not read the MAVEdb variant-effect product ({DERIVED_MANIFEST_ID}) "
            f"for {target}: {e}")
        return out


def _main(argv=None):
    import argparse
    import json
    ap = argparse.ArgumentParser(description="MAVEdb measured variant-effect summary for a target.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--product-path", default=None, help="offline: local parquet path (bypasses S3)")
    args = ap.parse_args(argv)
    print(json.dumps(read_target_summary(args.target, product_path=args.product_path),
                     indent=2, default=str))


if __name__ == "__main__":
    _main()
