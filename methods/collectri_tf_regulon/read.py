"""collectri_tf_regulon — read CollecTri TF-target edges per target.

Streamed pushdown (2026-08-22 data-layer hardening): reads the derived per-gene product
`collectri-tf-regulon-per-gene-v1` via a pyarrow S3FileSystem, pushing down the target_gene_symbol
filter so only ONE gene's edges transit the wire — no whole-CSV download. The derived product is a
pure RESHAPE of CollecTRI.csv (dual-emitted long rows keyed by target_gene_symbol); this reader owns
the MoA classification (shared with SIGNOR via moa_ontology) and applies it on-read, then aggregates
to the SIGNOR-compatible signaling-network-mechanism card shape.

Signed TF-target edges → same MoA-classification path as SIGNOR (via
methods/signor_mechanism_network/moa_ontology.py). CollecTri's weight column determines whether the
edge is a `transcriptional activation` (+1) or `transcriptional repression` (-1) — mechanism strings
that map to the ontology's upstream/downstream transcriptional activator/repressor classes.

Returns dict matching the SIGNOR read.py contract so consumers can union CollecTri + SIGNOR edges
without shape mismatches.

License: CollecTri wrapper is GPL-3.0 (Müller-Dott 2023). Per-row data inherits license from the
named `resources` column value; this reader emits `resources` per edge so governance can filter
downstream.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Optional

_METHODS_ROOT = Path(__file__).resolve().parent.parent
if str(_METHODS_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_METHODS_ROOT.parent))
from methods.signor_mechanism_network.moa_ontology import classify_edge, ONTOLOGY_VERSION
from methods.catalog_query.read import bucket_key_for

DERIVED_MANIFEST_ID = "collectri-tf-regulon-per-gene-v1"


# ── streamed pushdown read (pyarrow S3FileSystem; no whole-file download) ─────────────────────
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region us-east-1, the onc-compbio bucket).
    Built once and shared (safe for concurrent reads — the parallel card-read pool relies on that).
    Mirrors methods/dge_deseq2/read.py::_get_s3fs + methods/depmap_common/parquet.py."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs
                _S3FS = pafs.S3FileSystem(region="us-east-1")
    return _S3FS


def _weight_to_mechanism(weight: int) -> tuple[str, bool, bool, str]:
    """Signed CollecTRI weight → (mechanism_string, is_stimulation, is_inhibition, raw_effect).
    Mechanism strings match the extended MoA ontology entries (transcriptional activation/repression)."""
    if weight > 0:
        return "transcriptional activation", True, False, "up-regulates"
    if weight < 0:
        return "transcriptional repression", False, True, "down-regulates"
    return "transcriptional regulation", False, False, "regulates"


def _row_to_edge(row: dict) -> dict:
    """Map ONE derived-product row (target_gene_symbol/partner_gene_symbol/direction/weight/…) to the
    per-edge dict shape the SIGNOR contract uses. Direction is taken from the row (computed at derive
    time); MoA classified here via the shared ontology."""
    try:
        weight = int(row.get("weight") or 0)
    except (TypeError, ValueError):
        weight = 0
    mech_str, is_stim, is_inh, raw_effect = _weight_to_mechanism(weight)
    direction = row.get("direction") or ""
    cls = classify_edge(mech_str, direction)
    if cls is None:
        moa_class, modality_relevance = "unmapped", ()
    else:
        moa_class, modality_relevance = cls.moa_class, cls.modality_relevance
    return {
        "partner_uniprot_ac": "",   # CollecTri is symbol-only
        "partner_gene_symbol": row.get("partner_gene_symbol") or "",
        "direction": direction,
        "raw_mechanism": mech_str,
        "raw_effect": raw_effect,
        "moa_class": moa_class,
        "modality_relevance": list(modality_relevance),
        "is_stimulation": is_stim,
        "is_inhibition": is_inh,
        "direct_flag": True,   # CollecTri edges are direct-transcriptional by definition
        "references": row.get("references") or "",
        "resources": row.get("resources") or "",
        "tf_category": row.get("tf_category") or "",
        "sign_decision": row.get("sign_decision") or "",
    }, (cls is None)


def _read_edges_from_derived(target: str, product_path=None) -> tuple[list[dict], int, int]:
    """Streamed pushdown read of one target's edges from collectri-tf-regulon-per-gene-v1.

    Returns (edges, total, unmapped). `product_path` (offline test seam): a local parquet bypasses S3.
    Raises on a transient/creds/broken-env failure (NOT swallowed — the caller's boundary classifies a
    genuine 404/absence into data_unavailable via is_definitively_absent)."""
    import pyarrow.parquet as pq
    if product_path is not None:
        tbl = pq.read_table(str(product_path), filters=[("target_gene_symbol", "=", target)])
    else:
        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(),
                            filters=[("target_gene_symbol", "=", target)])
    edges: list[dict] = []
    total = unmapped = 0
    for row in tbl.to_pylist():
        edge, is_unmapped = _row_to_edge(row)
        edges.append(edge)
        total += 1
        if is_unmapped:
            unmapped += 1
    return edges, total, unmapped


def _aggregate_edges_to_summary(
    edges: list[dict], total: int, unmapped: int
) -> dict:
    """Aggregate per-edge records → per-target summary matching the SIGNOR read.py contract shape.
    Same keys, same categorical enum, so the composed Phase-D card can union CollecTri + SIGNOR
    outputs without reshape logic."""
    upstream = [e for e in edges if e["direction"] == "upstream"]
    downstream = [e for e in edges if e["direction"] == "downstream"]
    n_up = len(upstream)
    n_down = len(downstream)

    if n_up == 0 and n_down == 0:
        network_class = "data_unavailable"
    elif n_up >= 3 and n_down >= 3:
        network_class = "well_characterized"
    elif n_up + n_down <= 1:
        network_class = "sparse"
    else:
        network_class = "partial"

    moa_classes_present = sorted({e["moa_class"] for e in upstream})
    pd_marker_classes_present = sorted({e["moa_class"] for e in downstream})
    unmapped_frac = (unmapped / total) if total > 0 else 0.0

    return {
        "network_class": network_class,
        "n_upstream_regulators": n_up,
        "n_downstream_effectors": n_down,
        "upstream_regulators": upstream,
        "downstream_effectors": downstream,
        "moa_classes_present": moa_classes_present,
        "pd_marker_classes_present": pd_marker_classes_present,
        "has_actionable_moa": n_up >= 1,
        "has_pd_marker": n_down >= 1,
        "moa_ontology_version": ONTOLOGY_VERSION,
        "moa_ontology_unmapped_fraction": unmapped_frac,
        "_data_source": DERIVED_MANIFEST_ID,
    }


def read_target_summary(target: str, indication: str = None, product_path=None) -> dict:
    """Per-target CollecTri TF-regulon summary via streamed pushdown.

    Args:
        target: HGNC gene symbol (e.g., 'KRAS' or 'NFE2L2'). CollecTri keys on HGNC symbol directly.
        indication: unused (CollecTri is indication-agnostic); accepted for dispatcher signature.
        product_path: offline test seam — a local parquet path bypasses S3.

    Returns:
        dict matching the SIGNOR-derived signaling-network-mechanism card shape. Never raises on
        target-not-found — returns network_class='data_unavailable'.
    """
    try:
        edges, total, unmapped = _read_edges_from_derived(target, product_path=product_path)
        return _aggregate_edges_to_summary(edges, total, unmapped)
    except Exception as e:
        # A GENUINE product-object absence (NoSuchKey/404 or FileNotFoundError) → honest
        # data_unavailable. A transient/creds/broken-env error must NOT be masked as an empty regulon
        # — re-raise so the live-read seam surfaces _live_read_error instead of a silent dead axis.
        from methods.target_id_sidecar import is_definitively_absent
        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        return {
            "network_class": "data_unavailable",
            "n_upstream_regulators": 0,
            "n_downstream_effectors": 0,
            "upstream_regulators": [],
            "downstream_effectors": [],
            "moa_classes_present": [],
            "pd_marker_classes_present": [],
            "has_actionable_moa": False,
            "has_pd_marker": False,
            "moa_ontology_version": ONTOLOGY_VERSION,
            "moa_ontology_unmapped_fraction": 0.0,
            "_data_note": f"read_failed: {type(e).__name__}: {e}",
        }
