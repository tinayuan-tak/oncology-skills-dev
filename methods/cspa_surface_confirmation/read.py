"""cspa_surface_confirmation.read — wet-lab MEASURED surface confirmation from the Cell Surface
Protein Atlas (CSPA, Bausch-Fluck et al. 2015 PLOS ONE).

The live-firing provider of the `surface_confirmation` measurement_type (DATA_TO_SKILL_CONTRACT).
CSPA is the wet-lab (CSC-technology MS) companion to SURFY's in-silico prediction — this reader lets
a gate distinguish "measured on the surface" (evidence_tier: measured) from "predicted surface"
(inferred). It resolves the CSPA-orphan the doc opens with.

CONSUMES the DERIVED product, NOT the source xlsx (data-catalog discipline: methods read derived
manifests; ingestion goes through the id-resolver). Two artifacts under
derived/cspa-surface-confirmation-per-uniprot-v1/:
  - payload parquet: one row per UniProt AC (native key) → {surface_confirmation_class,
    cspa_category, n_celllines_detected}.
  - resolver SIDECAR parquet: native_row_key (UniProt AC) → canonical HGNC symbol/Ensembl/Entrez
    (target_id_resolver). The payload has NO symbol column, so a symbol lookup MUST join via the
    sidecar (same discipline as the topology + Gygi-proteomics readers).

Runtime: S3 get → in-process cache via lru_cache on the built index; single lookup per call.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for, sidecar_bucket_key_for

METHOD_VERSION = "0.1.0"
DERIVED_MANIFEST_ID = "cspa-surface-confirmation-per-uniprot-v1"
# payload + resolver-sidecar keys resolved from the data-catalog manifest (single
# source of truth): s3_uri is the payload; target_resolution.sidecar_s3_uri the sidecar.
S3_BUCKET, PAYLOAD_KEY = bucket_key_for(DERIVED_MANIFEST_ID)
_, SIDECAR_KEY = sidecar_bucket_key_for(DERIVED_MANIFEST_ID)
DEFAULT_AWS_PROFILE = "cbg"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _read_parquet(path_or_none, bucket, key):
    import pandas as pd
    if path_or_none is not None:
        return pd.read_parquet(path_or_none)
    _ensure_aws_profile()
    import boto3
    body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


@lru_cache(maxsize=1)
def _load_indexed(payload_path: Optional[str] = None, sidecar_path: Optional[str] = None):
    """Build (payload_by_ac, symbol_to_ac). None on unavailable source.

    payload_by_ac: uniprot_ac -> row dict (class, category, n_celllines).
    symbol_to_ac : UPPER(hgnc symbol) -> uniprot_ac, from the resolver sidecar."""
    try:
        payload = _read_parquet(payload_path, S3_BUCKET, PAYLOAD_KEY)
    except Exception:  # noqa: BLE001
        return None
    payload_by_ac = {}
    for rec in payload.to_dict("records"):
        ac = str(rec.get("uniprot_ac", "")).strip()
        if ac:
            payload_by_ac[ac] = rec
    symbol_to_ac = {}
    try:
        sc = _read_parquet(sidecar_path, S3_BUCKET, SIDECAR_KEY)
        sym_col = "hgnc_primary_symbol_at_resolution"
        if sym_col in sc.columns and "native_row_key" in sc.columns:
            for sym, ac in zip(sc[sym_col].values, sc["native_row_key"].values):
                if isinstance(sym, str) and sym.strip() and isinstance(ac, str):
                    symbol_to_ac[sym.strip().upper()] = ac.strip()
    except Exception:  # noqa: BLE001 — sidecar optional at read time; AC lookups still work
        pass
    return payload_by_ac, symbol_to_ac


def read_surface_confirmation(target: str, indication: Optional[str] = None,
                              payload_path: Optional[str] = None,
                              sidecar_path: Optional[str] = None) -> dict:
    """CSPA surface-confirmation summary for `target` (HGNC symbol or UniProt AC).

    A target absent from the CSPA high-confidence master is an HONEST measured negative in the CSPA
    panel (`not_surface`, measured_in_cspa=False) — NOT data_unavailable. data_unavailable is
    reserved for the case where the derived product itself couldn't be loaded."""
    idx = _load_indexed(payload_path, sidecar_path)
    if idx is None:
        return _empty("cspa_derived_product_unavailable")
    payload_by_ac, symbol_to_ac = idx

    key = target.strip()
    ac = key if key in payload_by_ac else symbol_to_ac.get(key.upper())
    rec = payload_by_ac.get(ac) if ac else None
    if rec is None:
        return {
            "surface_confirmation_class": "not_surface",
            "cspa_category": None,
            "n_celllines_detected": 0,
            "measured_in_cspa": False,
            "evidence_tier": "measured",
            "uniprot_ac": None,
            "method_version": METHOD_VERSION,
            "_data_source": DERIVED_MANIFEST_ID,
            "_data_note": f"{target!r} not in the CSPA high-confidence surfaceome master "
                          f"(measured-absent in the 41-cell-line panel, not a coverage gap)",
        }
    n = rec.get("n_celllines_detected")
    return {
        "surface_confirmation_class": rec.get("surface_confirmation_class", "not_surface"),
        "cspa_category": rec.get("cspa_category"),
        "n_celllines_detected": int(n) if n is not None and n == n else None,
        "measured_in_cspa": True,
        "evidence_tier": "measured",
        "uniprot_ac": rec.get("uniprot_ac"),
        "method_version": METHOD_VERSION,
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "surface_confirmation_class": "data_unavailable",
        "cspa_category": None,
        "n_celllines_detected": None,
        "measured_in_cspa": None,
        "evidence_tier": "measured",
        "uniprot_ac": None,
        "method_version": METHOD_VERSION,
        "_data_source": DERIVED_MANIFEST_ID,
        "_data_note": note,
    }
