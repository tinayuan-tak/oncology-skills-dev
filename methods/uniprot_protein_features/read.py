"""uniprot_protein_features.read — per-target domain architecture + protein class (UniProt-curated).

The INDICATION-INDEPENDENT domain/class view of a target: its curated domain architecture (FT DOMAIN)
and its molecular protein class(es) (mapped from UniProt keywords). Target-intrinsic; consumed by the
target-intrinsic dossier. Descriptive, no verdict.

CONSUMES the derived product uniprot-protein-features-v1 (payload + resolver sidecar), NOT the DAT.
Symbol→AC via the sidecar (never a source symbol column). A target absent from the payload has no
curated domain AND no class-bearing keyword → data_unavailable (coverage/annotation gap, not a claim).
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

METHOD_VERSION = "1.0.0"
S3_BUCKET = "onc-compbio"
DERIVED_MANIFEST_ID = "uniprot-protein-features-v1"
_PREFIX = f"data-catalog/derived/{DERIVED_MANIFEST_ID}"
PAYLOAD_KEY = f"{_PREFIX}/uniprot_protein_features_v1.parquet"
SIDECAR_KEY = f"{_PREFIX}/uniprot_protein_features_v1.target_resolution.parquet"
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
    """(payload_by_ac, symbol_to_ac). None if payload unavailable."""
    try:
        payload = _read_parquet(payload_path, S3_BUCKET, PAYLOAD_KEY)
    except Exception:  # noqa: BLE001
        return None
    by_ac = {}
    for rec in payload.to_dict("records"):
        ac = str(rec.get("uniprot_ac", "")).strip()
        if ac:
            by_ac[ac] = rec
    symbol_to_ac = {}
    try:
        sc = _read_parquet(sidecar_path, S3_BUCKET, SIDECAR_KEY)
        if "hgnc_primary_symbol_at_resolution" in sc.columns and "native_row_key" in sc.columns:
            for sym, ac in zip(sc["hgnc_primary_symbol_at_resolution"].values, sc["native_row_key"].values):
                if isinstance(sym, str) and sym.strip() and isinstance(ac, str) and ac.strip():
                    symbol_to_ac.setdefault(sym.strip().upper(), ac.strip())
    except Exception:  # noqa: BLE001
        pass
    return by_ac, symbol_to_ac


def _as_list(v):
    # parquet round-trips list columns as numpy arrays; normalize to plain list
    if v is None:
        return []
    try:
        return list(v)
    except TypeError:
        return [v]


def read_target_summary(target: str, indication: str = None,
                        payload_path: Optional[str] = None, sidecar_path: Optional[str] = None) -> dict:
    """Per-target domain architecture + protein class. `indication` unused (target-intrinsic)."""
    idx = _load_indexed(payload_path, sidecar_path)
    if idx is None:
        return _empty("protein_features_derived_product_unavailable")
    by_ac, symbol_to_ac = idx
    key = target.strip()
    ac = key if key in by_ac else symbol_to_ac.get(key.upper())
    rec = by_ac.get(ac) if ac else None
    if rec is None:
        return _empty(f"{target!r} has no curated UniProt domain or class-bearing keyword "
                      f"(annotation gap, not 'featureless')")
    domain_names = _as_list(rec.get("domain_names"))
    protein_class = _as_list(rec.get("protein_class"))
    n_dom = int(rec.get("n_domains") or 0)
    # a compact class for quick reads: has_domains + primary class
    features_class = ("multi_domain" if n_dom >= 2 else
                      "single_domain" if n_dom == 1 else
                      "no_curated_domain")
    return {
        "protein_features_class": features_class,   # PRIMARY (multi_domain | single_domain | no_curated_domain)
        "n_domains": n_dom,
        "domain_names": domain_names,
        "domain_architecture": rec.get("domain_architecture"),
        "protein_class": protein_class,
        "protein_class_primary": rec.get("protein_class_primary"),
        "uniprot_ac": ac,
        "method_version": METHOD_VERSION,
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "protein_features_class": "data_unavailable",
        "n_domains": 0, "domain_names": [], "domain_architecture": None,
        "protein_class": [], "protein_class_primary": None, "uniprot_ac": None,
        "method_version": METHOD_VERSION, "_data_source": DERIVED_MANIFEST_ID, "_data_note": note,
    }
