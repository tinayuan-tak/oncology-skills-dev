"""collectri_tf_regulon — read CollecTri TF-target edges per target.

Hybrid cache-then-compute pattern:
  1. Try to load pre-computed derived parquet (per-target aggregated view)
  2. If not found, load the full CollecTri CSV from S3 + filter to target-
     involved edges + emit per-target summary
  3. Cache result to local ~/.cache/framework-collectri/

Signed TF-target edges → same MoA-classification path as SIGNOR (via
methods/signor_mechanism_network/moa_ontology.py). CollecTri's weight
column determines whether the edge is a `transcriptional activation`
(+1) or `transcriptional repression` (-1) — mechanism strings that map
to the ontology's `upstream_transcriptional_activator` +
`upstream_transcriptional_repressor` (or downstream analogs).

Returns dict matching the SIGNOR read.py contract so consumers can union
CollecTri + SIGNOR edges without shape mismatches.

License: CollecTri wrapper is GPL-3.0 (Müller-Dott 2023). Per-row data
inherits license from the named `resources` column value; commercial-use
consumers should filter by resources OR emit resources verbatim so
governance can filter downstream. This reader emits `resources` per edge.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Reuse the shared MoA ontology from the SIGNOR method — cross-source
# consistency. If we needed CollecTri-specific classes, we'd extend the
# shared ontology (already done for `transcriptional activation` /
# `transcriptional repression` entries).
import sys
_METHODS_ROOT = Path(__file__).resolve().parent.parent
if str(_METHODS_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_METHODS_ROOT.parent))
from methods.signor_mechanism_network.moa_ontology import classify_edge, ONTOLOGY_VERSION
from methods.catalog_query.read import bucket_prefix_for

DEFAULT_AWS_PROFILE = "cbg"
COLLECTRI_SOURCE_MANIFEST_ID = "collectri-snapshot-2026-06-30"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, _SOURCE_PREFIX = bucket_prefix_for(COLLECTRI_SOURCE_MANIFEST_ID)
COLLECTRI_S3_KEY = f"{_SOURCE_PREFIX}CollecTRI.csv"

CACHE_DIR = Path.home() / ".cache" / "framework-collectri"
CACHE_CSV = CACHE_DIR / "CollecTRI.csv"


def _boto3_client():
    """Return a boto3 s3 client with AWS_PROFILE=cbg explicitly pinned.

    Same discipline as signor_mechanism_network.read._boto3_client — the
    default SSO role (Developer-Dev) lacks GetObject on onc-compbio;
    setdefault() no-ops if AWS_PROFILE is already set to something else.
    """
    import boto3
    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


def _ensure_collectri_cached() -> Path:
    """Download CollecTRI.csv from S3 to local cache. Idempotent."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_CSV.exists() and CACHE_CSV.stat().st_size > 0:
        return CACHE_CSV
    s3 = _boto3_client()
    s3.download_file(S3_BUCKET, COLLECTRI_S3_KEY, str(CACHE_CSV))
    return CACHE_CSV


from functools import lru_cache


@lru_cache(maxsize=1)
def _load_collectri_rows_indexed() -> tuple[list[dict], dict]:
    """Parse CollecTri CSV ONCE and cache in-memory. Returns (all_rows,
    entity_index) where entity_index[symbol] → list of row indexes that
    involve that HGNC symbol (as either source TF or regulated target).

    Runtime discipline (2026-07-10 perf fix, same pattern as SIGNOR):
    per-target reads become O(k) where k = rows-involving-target.
    """
    import csv
    path = _ensure_collectri_cached()
    rows: list[dict] = []
    entity_index: dict[str, list[int]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = len(rows)
            rows.append(row)
            for col in ("source", "target"):
                sym = row.get(col, "").strip()
                if sym:
                    entity_index.setdefault(sym, []).append(idx)
    return rows, entity_index


def _stream_collectri_rows():
    """Legacy API-compat path. Delegates to cached parse — no more per-call
    CSV re-reading.
    """
    rows, _ = _load_collectri_rows_indexed()
    yield from rows


def _iter_collectri_rows_for_target(target: str):
    """O(k) iteration over CollecTri rows involving the target."""
    rows, entity_index = _load_collectri_rows_indexed()
    for idx in entity_index.get(target, []):
        yield rows[idx]


def _compute_edges_for_target(target: str) -> tuple[list[dict], int, int]:
    """Filter CollecTri to edges where target appears as either the TF
    (source) or the regulated gene (target). Classify each edge via MoA
    ontology. Return (edges, total, unmapped).
    """
    edges: list[dict] = []
    unmapped = 0
    total = 0

    # Fast path (2026-07-10 perf fix): use pre-indexed target lookup.
    for row in _iter_collectri_rows_for_target(target):
        src = row.get("source", "").strip()  # TF (HGNC symbol)
        tgt = row.get("target", "").strip()  # regulated gene (HGNC symbol)
        if target not in (src, tgt):
            continue

        weight_str = row.get("weight", "0").strip()
        try:
            weight = int(weight_str) if weight_str else 0
        except ValueError:
            weight = 0

        # Signed weight → mechanism string that matches the extended MoA
        # ontology entries added 2026-07-10.
        if weight > 0:
            mech_str = "transcriptional activation"
            is_stim, is_inh = True, False
        elif weight < 0:
            mech_str = "transcriptional repression"
            is_stim, is_inh = False, True
        else:
            mech_str = "transcriptional regulation"
            is_stim, is_inh = False, False

        resources = row.get("resources", "").strip()
        pmid = row.get("PMID", "").strip()
        tf_category = row.get("TF.category", "").strip()
        sign_decision = row.get("sign.decision", "").strip()

        # Direction from target's perspective:
        #   target == src → target is the TF; partner is downstream regulated gene
        #   target == tgt → target is regulated; partner is the upstream TF
        if target == src:
            partner_symbol = tgt
            direction = "downstream"
        else:
            partner_symbol = src
            direction = "upstream"

        cls = classify_edge(mech_str, direction)
        total += 1
        if cls is None:
            unmapped += 1
            moa_class = "unmapped"
            modality_relevance: tuple = ()
        else:
            moa_class = cls.moa_class
            modality_relevance = cls.modality_relevance

        edges.append({
            "partner_uniprot_ac": "",   # CollecTri is symbol-only; leave AC empty
            "partner_gene_symbol": partner_symbol,
            "direction": direction,
            "raw_mechanism": mech_str,
            "raw_effect": (
                "up-regulates" if weight > 0
                else ("down-regulates" if weight < 0 else "regulates")
            ),
            "moa_class": moa_class,
            "modality_relevance": list(modality_relevance),
            "is_stimulation": is_stim,
            "is_inhibition": is_inh,
            "direct_flag": True,  # CollecTri edges are direct-transcriptional by definition
            "references": pmid,
            "resources": resources,
            "tf_category": tf_category,
            "sign_decision": sign_decision,
        })

    return edges, total, unmapped


def _aggregate_edges_to_summary(
    edges: list[dict], total: int, unmapped: int
) -> dict:
    """Aggregate per-edge records → per-target summary matching the SIGNOR
    read.py contract shape. Same keys, same categorical enum, so the
    composed Phase-D card can union CollecTri + SIGNOR outputs without
    reshape logic.
    """
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
        "_data_source": "collectri-tf-regulon-per-gene-v1",
        "_data_source_upstream": COLLECTRI_SOURCE_MANIFEST_ID,
    }


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target CollecTri TF-regulon summary. Hybrid cache-then-compute.

    Args:
        target: HGNC gene symbol (e.g., 'KRAS' or 'NFE2L2'). CollecTri
            keys on HGNC symbol directly.
        indication: unused (CollecTri is indication-agnostic); accepted
            for dispatcher signature consistency across cards.

    Returns:
        dict matching the SIGNOR-derived signaling-network-mechanism card
        shape. Never raises on target-not-found — returns
        network_class='data_unavailable'.
    """
    try:
        edges, total, unmapped = _compute_edges_for_target(target)
        return _aggregate_edges_to_summary(edges, total, unmapped)
    except Exception as e:
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
            "_data_note": f"compute_failed: {type(e).__name__}: {e}",
        }
