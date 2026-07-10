"""surfaceome_family_fusion.read — SURFY + HPA + UniProt + IUPHAR family reader.

Consumer: surfaceome-family-classification evidence card (Phase F) via
tractability-and-modality skill. Emits per-target surface-protein family
classification fused from 4 upstream sources with source-agreement scoring.

Iter-1 wiring approach:
  - Reads the derived parquet at
    s3://onc-compbio/data-catalog/derived/surfaceome-family-classification-per-uniprot-v1/
  - Falls back to `data_unavailable` gracefully when the derived product
    isn't in S3 (SURFY XLSX extractor + HPA parse + UniProt EC + IUPHAR
    REST is a batch ETL, not per-target compute).

Runtime discipline: @lru_cache + module-level negative cache.

Companion:
  data-catalog:manifests/derived/surfaceome-family-classification-per-uniprot-v1.yaml
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional


DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DERIVED_MANIFEST_ID = "surfaceome-family-classification-per-uniprot-v1"
DERIVED_S3_KEY = (
    "data-catalog/derived/surfaceome-family-classification-per-uniprot-v1/"
    "surfaceome_family.parquet"
)

CACHE_DIR = Path.home() / ".cache" / "framework-surfaceome-family"
CACHE_PARQUET = CACHE_DIR / "surfaceome_family.parquet"

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
def _load_indexed() -> dict:
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
        rec = row.to_dict()
        if sym:
            idx[sym] = rec
        if ac:
            idx[ac] = rec
    return idx


def read_target_summary(target: str, indication: str = None) -> dict:
    try:
        idx = _load_indexed()
    except Exception as e:
        return _empty(f"surfaceome_family_load_failed: {type(e).__name__}: {e}")
    if not idx:
        return _empty("surfaceome_family_data_unavailable")

    row = idx.get(target.upper().strip()) or idx.get(target.strip())
    if row is None:
        return _empty("target_not_in_surfaceome_family")

    return {
        "family_class": row.get("family_class", "data_unavailable"),
        "surface_protein_family": row.get("surface_protein_family", "Other"),
        "is_surface_protein": bool(row.get("is_surface_protein", False)),
        "surfaceome_confidence_score": row.get("surfaceome_confidence_score"),
        "source_surfy_positive": bool(row.get("source_surfy_positive", False)),
        "source_hpa_plasma_membrane": bool(row.get("source_hpa_plasma_membrane", False)),
        "source_uniprot_ec_number": row.get("source_uniprot_ec_number", ""),
        "source_iuphar_family": row.get("source_iuphar_family", ""),
        "hpa_protein_class_verbatim": row.get("hpa_protein_class_verbatim", ""),
        "fusion_provenance": row.get("fusion_provenance") or [],
        "method_version": "0.1.0",
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "family_class": "data_unavailable",
        "surface_protein_family": "Not_surface",
        "is_surface_protein": False,
        "surfaceome_confidence_score": None,
        "source_surfy_positive": False,
        "source_hpa_plasma_membrane": False,
        "source_uniprot_ec_number": "",
        "source_iuphar_family": "",
        "hpa_protein_class_verbatim": "",
        "fusion_provenance": [],
        "method_version": "0.1.0",
        "_data_note": note,
    }
