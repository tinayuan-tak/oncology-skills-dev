"""structure_features_static.read — PDB + AlphaFold scalar-features reader.

Consumer: structure-features-static evidence card (Phase F) via
tractability-and-modality skill. Emits per-target scalar structural
features (PDB coverage + AlphaFold pLDDT summary + hotspot-pocket-adjacency
call) — no atomic coordinates, no interactive viewer.

Iter-1 wiring approach:
  - Reads the derived parquet at
    s3://onc-compbio/data-catalog/derived/pdb-alphafold-structure-features-per-uniprot-v1/
    when it exists.
  - Otherwise emits `data_unavailable` gracefully (avoids 20k API calls
    against PDB + AlphaFold REST at read-time; those belong in a batch
    ETL that produces the derived parquet).

Runtime discipline: @lru_cache + module-level negative cache — same patterns
as SIGNOR/CollecTri/Reactome (Sprint 2).

Companion:
  data-catalog:manifests/derived/pdb-alphafold-structure-features-per-uniprot-v1.yaml
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional


DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DERIVED_MANIFEST_ID = "pdb-alphafold-structure-features-per-uniprot-v1"
DERIVED_S3_KEY = (
    "data-catalog/derived/pdb-alphafold-structure-features-per-uniprot-v1/"
    "structure_features.parquet"
)

CACHE_DIR = Path.home() / ".cache" / "framework-structure-features"
CACHE_PARQUET = CACHE_DIR / "structure_features.parquet"

_DERIVED_STATUS: Optional[bool] = None  # negative cache


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
        except Exception as e:
            # Distinguish "genuinely not published yet" (a definitive 404 /
            # NoSuchKey / access-denied) from a TRANSIENT failure (expired
            # creds, network blip, throttling). Only latch _DERIVED_STATUS =
            # False on the definitive case — that safely short-circuits every
            # later call in the process. For a transient error, LEAVE
            # _DERIVED_STATUS = None so a subsequent call retries instead of
            # poisoning the whole process with a false data_unavailable.
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (code in ("404", "NoSuchKey", "403", "AccessDenied")
                          or e.__class__.__name__ in ("NoSuchKey", "404"))
            if definitive:
                _DERIVED_STATUS = False
            return None
    return None


@lru_cache(maxsize=1)
def _load_structure_indexed() -> dict:
    """Load structure-features parquet ONCE, index by both gene_symbol and
    uniprot_ac for O(1) per-target lookup.
    """
    path = _ensure_derived_cached()
    if path is None:
        return {}
    try:
        import pandas as pd
        df = pd.read_parquet(path)
    except Exception:
        return {}
    if df.empty:
        return {}
    idx: dict[str, dict] = {}
    for _, row in df.iterrows():
        sym = str(row.get("gene_symbol", "")).strip().upper()
        ac = str(row.get("uniprot_ac", "")).strip()
        record = row.to_dict()
        if sym:
            idx[sym] = record
        if ac:
            idx[ac] = record
    return idx


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target structural features from the pre-computed derived parquet.

    Args:
        target: HGNC gene symbol OR UniProt-AC.
        indication: unused.

    Returns:
        dict matching structure-features-static card summary shape.
    """
    try:
        idx = _load_structure_indexed()
    except Exception as e:
        return _empty_result(f"structure_load_failed: {type(e).__name__}: {e}")
    if not idx:
        return _empty_result("structure_data_unavailable")

    target_up = target.upper().strip()
    row = idx.get(target_up) or idx.get(target.strip())
    if row is None:
        return _empty_result("target_not_in_structure_features")

    return {
        "hotspot_pocket_adjacency_call": row.get("hotspot_pocket_adjacency_call", "no_structure"),
        "mutation_hotspot_in_druggable_pocket": bool(row.get("mutation_hotspot_in_druggable_pocket", False)),
        "pdb_coverage_class": _classify_pdb_coverage(row),
        "alphafold_confidence_class": _classify_alphafold_confidence(row),
        "pdb_ids_available": row.get("pdb_ids_available") or [],
        "pdb_best_resolution_angstrom": row.get("pdb_best_resolution_angstrom"),
        "pdb_best_method": row.get("pdb_best_method", "none"),
        "alphafold_plddt_mean": row.get("alphafold_plddt_mean"),
        "alphafold_plddt_min": row.get("alphafold_plddt_min"),
        "alphafold_plddt_min_domain": row.get("alphafold_plddt_min_domain"),
        "n_domains_low_plddt": row.get("n_domains_low_plddt", 0),
        "disordered_fraction": row.get("disordered_fraction"),
        "method_version": "0.1.0",
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _classify_pdb_coverage(row) -> str:
    ids = row.get("pdb_ids_available") or []
    if isinstance(ids, str):
        ids = [ids] if ids else []
    if len(ids) >= 5:
        return "strong"
    if len(ids) >= 1:
        return "partial"
    if row.get("alphafold_prediction_id"):
        return "af_only"
    return "none"


def _classify_alphafold_confidence(row) -> str:
    mean = row.get("alphafold_plddt_mean")
    if mean is None:
        return "unavailable"
    try:
        m = float(mean)
    except (ValueError, TypeError):
        return "unavailable"
    if m >= 90:
        return "high"
    if m >= 70:
        return "moderate"
    return "low"


def _empty_result(note: str) -> dict:
    return {
        "hotspot_pocket_adjacency_call": "no_structure",
        "mutation_hotspot_in_druggable_pocket": False,
        "pdb_coverage_class": "none",
        "alphafold_confidence_class": "unavailable",
        "pdb_ids_available": [],
        "pdb_best_resolution_angstrom": None,
        "pdb_best_method": "none",
        "alphafold_plddt_mean": None,
        "alphafold_plddt_min": None,
        "alphafold_plddt_min_domain": None,
        "n_domains_low_plddt": 0,
        "disordered_fraction": None,
        "method_version": "0.1.0",
        "_data_note": note,
    }
