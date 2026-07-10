"""kinome_atlas_prediction.read — Johnson 2023 + Yaron-Barir 2024 substrate reader.

Returns predicted kinase-substrate edges for a target, sourced from a
Layer-3 derived parquet materialized once from the two Nature-supplementary
Excel files (see methods.kinome_atlas_prediction.derive).

When target is a KINASE, returns its predicted substrates (target-as-source).
When target is a SUBSTRATE, returns kinases predicted to phosphorylate it
(target-as-target).

Runtime discipline:
  - @lru_cache(maxsize=1) on parquet load + dual-index build
    (~2M rows → ~2s cold, <5ms warm per-target)
  - Module-level negative cache for missing parquet (avoid boto3 404 retry)
  - Returns 'data_unavailable' gracefully when the derived parquet isn't
    yet on S3

Emitted edges carry source="kinome_atlas_prediction" so consumers can
distinguish from curated SIGNOR/CollecTri/Reactome edges and weight
accordingly. confidence_bucket is derived from the paper's percentile-rank
of the PWM log-odds score.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional


DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

DERIVED_MANIFEST_ID = "kinome-atlas-long-edges-v1"
DERIVED_S3_KEY = (
    "data-catalog/derived/kinome-atlas-long-edges-v1/kinome_atlas_long_edges.parquet"
)

CACHE_DIR = Path.home() / ".cache" / "framework-kinome-atlas"
CACHE_PARQUET = CACHE_DIR / "kinome_atlas_long_edges.parquet"


_DERIVED_STATUS: Optional[bool] = None


def _boto3_client():
    import boto3
    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


def _ensure_derived_cached() -> Optional[Path]:
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_PARQUET.exists() and CACHE_PARQUET.stat().st_size > 0:
        _DERIVED_STATUS = True
        return CACHE_PARQUET
    if _DERIVED_STATUS is None:
        try:
            s3 = _boto3_client()
            s3.download_file(S3_BUCKET, DERIVED_S3_KEY, str(CACHE_PARQUET))
            _DERIVED_STATUS = True
            return CACHE_PARQUET
        except Exception:
            _DERIVED_STATUS = False
            return None
    return None


@lru_cache(maxsize=1)
def _load_atlas_indexed() -> tuple[list[dict], dict, dict]:
    """Load derived parquet + build kinase and substrate indices.

    Returns:
        (all_edges, kinase_index, substrate_index)
        - all_edges: list[dict] one per predicted (kinase, substrate, site)
        - kinase_index: dict[kinase_symbol -> list[edge_index]]
        - substrate_index: dict[substrate_gene -> list[edge_index]]
    """
    path = _ensure_derived_cached()
    if path is None:
        return [], {}, {}

    try:
        import pandas as pd
        df = pd.read_parquet(path)
    except Exception:
        return [], {}, {}

    if df.empty:
        return [], {}, {}

    all_edges: list[dict] = []
    kinase_index: dict[str, list[int]] = {}
    substrate_index: dict[str, list[int]] = {}

    # Iterate as dicts. This is the cold-path bottleneck (~2s for 2.8M rows)
    # but only runs once per process.
    for rec in df.to_dict(orient="records"):
        kinase = str(rec.get("kinase_symbol") or "").strip().upper()
        substrate = str(rec.get("substrate_gene") or "").strip().upper()
        if not kinase or not substrate:
            continue
        idx = len(all_edges)
        all_edges.append(rec)
        kinase_index.setdefault(kinase, []).append(idx)
        substrate_index.setdefault(substrate, []).append(idx)

    return all_edges, kinase_index, substrate_index


def _classify_confidence(percentile) -> str:
    if percentile is None:
        return "unranked"
    try:
        pct = float(percentile)
    except (ValueError, TypeError):
        return "unranked"
    if pct >= 99:
        return "top_percentile"
    if pct >= 95:
        return "high"
    if pct >= 90:
        return "moderate"
    return "low"


def _edge_to_downstream(edge: dict) -> dict:
    return {
        "partner_gene_symbol": str(edge.get("substrate_gene") or "").strip().upper(),
        "partner_uniprot_ac": str(edge.get("substrate_ac") or "").strip(),
        "direction": "downstream",
        "raw_mechanism": f"predicted phosphorylation ({edge.get('kinome', '')})",
        "moa_class": "downstream_predicted_phospho_readout",
        "modality_relevance": ["pd_biomarker_phospho"],
        "site_residue": str(edge.get("phos_res") or "").strip(),
        "site_position": edge.get("phosphosite"),
        "motif_15mer": str(edge.get("motif_15mer") or "").strip(),
        "pwm_percentile": edge.get("percentile"),
        "rank": edge.get("rank"),
        "confidence_bucket": _classify_confidence(edge.get("percentile")),
        "sources": ["kinome_atlas_prediction"],
        "kinome": edge.get("kinome"),
    }


def _edge_to_upstream(edge: dict) -> dict:
    return {
        "partner_gene_symbol": str(edge.get("kinase_symbol") or "").strip().upper(),
        "partner_uniprot_ac": "",  # kinase AC not stored per-edge; derivable from atlas metadata
        "direction": "upstream",
        "raw_mechanism": f"predicted phosphorylation ({edge.get('kinome', '')})",
        "moa_class": "upstream_predicted_kinase_modulation",
        "modality_relevance": ["small_molecule_kinase_inhibitor_predicted"],
        "site_residue": str(edge.get("phos_res") or "").strip(),
        "site_position": edge.get("phosphosite"),
        "motif_15mer": str(edge.get("motif_15mer") or "").strip(),
        "pwm_percentile": edge.get("percentile"),
        "rank": edge.get("rank"),
        "confidence_bucket": _classify_confidence(edge.get("percentile")),
        "sources": ["kinome_atlas_prediction"],
        "kinome": edge.get("kinome"),
    }


def _rank_key(e: dict):
    try:
        return -float(e.get("pwm_percentile") or 0)
    except (ValueError, TypeError):
        return 0


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target kinome-atlas prediction summary.

    Args:
        target: HGNC gene symbol (kinome-atlas keys on symbol directly).
        indication: unused (atlas is context-agnostic).

    Returns:
        dict matching signor_mechanism_network.read output shape.
    """
    try:
        edges_all, kinase_idx, substrate_idx = _load_atlas_indexed()
    except Exception as e:
        return _empty_result(f"atlas_load_failed: {type(e).__name__}: {e}")

    if not edges_all:
        return _empty_result("kinome_atlas_data_unavailable")

    sym = target.upper().strip()

    downstream_effectors = [
        _edge_to_downstream(edges_all[i]) for i in kinase_idx.get(sym, [])
    ]
    upstream_regulators = [
        _edge_to_upstream(edges_all[i]) for i in substrate_idx.get(sym, [])
    ]

    n_up = len(upstream_regulators)
    n_down = len(downstream_effectors)

    if n_up == 0 and n_down == 0:
        network_class = "data_unavailable"
    elif n_up >= 3 and n_down >= 3:
        network_class = "well_characterized"
    elif n_up + n_down <= 1:
        network_class = "sparse"
    else:
        network_class = "partial"

    moa_present = sorted({e["moa_class"] for e in upstream_regulators})
    pd_present = sorted({e["moa_class"] for e in downstream_effectors})

    upstream_regulators.sort(key=_rank_key)
    downstream_effectors.sort(key=_rank_key)

    return {
        "network_class": network_class,
        "n_upstream_regulators": n_up,
        "n_downstream_effectors": n_down,
        "upstream_regulators": upstream_regulators,
        "downstream_effectors": downstream_effectors,
        "moa_classes_present": moa_present,
        "pd_marker_classes_present": pd_present,
        "has_actionable_moa": n_up >= 1,
        "has_pd_marker": n_down >= 1,
        "moa_ontology_version": "1.0.0",
        "moa_ontology_unmapped_fraction": 0.0,
        "_data_source": DERIVED_MANIFEST_ID,
        "_source_note": (
            "Kinome-atlas edges are PREDICTIONS from PWM specificity models "
            "(Johnson 2023 + Yaron-Barir 2024 Nature). Distinct from curated "
            "SIGNOR/CollecTri/Reactome edges — weight lower in Tier-3 synthesis. "
            "Filter: percentile >= 90 (paper's meaningful-prediction threshold)."
        ),
    }


def _empty_result(note: str) -> dict:
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
        "moa_ontology_version": "1.0.0",
        "moa_ontology_unmapped_fraction": 0.0,
        "_data_note": note,
    }
