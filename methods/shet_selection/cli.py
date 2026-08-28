#!/usr/bin/env python3
"""shet_selection CLI — GeneBayes s_het per-gene lookup (pyarrow gene_symbol pushdown).

Reads shet-selection-per-gene-v1. classify_shet lives here (the product carries the raw s_het + a
precomputed shet_class; the method re-derives the class from the raw value so thresholds are auditable
in one place, mirroring gnomad_constraint.classify_constraint)."""
from __future__ import annotations

from typing import Optional

from methods.catalog_query.read import bucket_key_for
from methods.target_id_sidecar import ensure_aws_profile, is_definitively_absent

METHOD_VERSION = "1.0.0"
SOURCE_MANIFEST_ID = "shet-selection-per-gene-v1"
S3_BUCKET, S3_KEY = bucket_key_for(SOURCE_MANIFEST_ID)
COL_GENE = "gene_symbol"

# s_het class thresholds (mirror the product's binning + shet-lof-intolerance card).
HIGH_INTOLERANCE = 0.1        # Cassa 2017 / Zeng 2024 strong-constraint threshold (~15% of genes)
MODERATE_INTOLERANCE = 0.01

import threading

_S3FS = None
_S3FS_LOCK = threading.Lock()
_DERIVED_STATUS: Optional[bool] = None


def classify_shet(shet: Optional[float]) -> str:
    """high_intolerance (s_het>=0.1) / moderate_intolerance (0.01-0.1) / tolerant (<0.01) /
    indeterminate (no row). A HIGH s_het = strong dominant-LoF intolerance = full-KO safety concern."""
    if shet is None:
        return "indeterminate"
    if shet >= HIGH_INTOLERANCE:
        return "high_intolerance"
    if shet >= MODERATE_INTOLERANCE:
        return "moderate_intolerance"
    return "tolerant"


def _get_s3fs():
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                ensure_aws_profile()
                import pyarrow.fs as fs
                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def load_shet_row(gene_symbol: str) -> Optional[dict]:
    """Return the per-gene s_het row (dict) or None if the gene is absent. Pushdown on gene_symbol.
    A genuine 404 -> None (honest data_unavailable, latched); transient/creds -> raise."""
    global _DERIVED_STATUS
    import pyarrow.parquet as pq
    import pyarrow.compute as pc
    key = (gene_symbol or "").upper().strip()
    if not key:
        return None
    uri = f"{S3_BUCKET}/{S3_KEY}"
    try:
        table = pq.read_table(uri, filesystem=_get_s3fs(),
                              filters=[(COL_GENE, "=", key)])
    except Exception as e:  # noqa: BLE001 — distinguish definitive-absence from transient
        if is_definitively_absent(e):
            _DERIVED_STATUS = False
            return None
        raise
    hits = table.filter(pc.equal(pc.utf8_upper(table[COL_GENE]), key)).to_pylist()
    return hits[0] if hits else None


def compute_summary(row: Optional[dict], gene_symbol: str) -> dict:
    """Card summary_fields from a row (or a data_unavailable stub)."""
    if not row:
        return {"shet_class": "indeterminate", "shet_score": None,
                "shet_lower_95": None, "shet_upper_95": None,
                "obs_lof_count": None, "exp_lof_count": None,
                "method_version": METHOD_VERSION, "_data_note": f"{gene_symbol} absent from s_het product"}
    shet = row.get("shet")
    return {
        "shet_class": classify_shet(shet),
        "shet_score": shet,
        "shet_lower_95": row.get("shet_lower_95"),
        "shet_upper_95": row.get("shet_upper_95"),
        "obs_lof_count": row.get("obs_lof"),
        "exp_lof_count": row.get("exp_lof"),
        "shet_context": (f"GeneBayes s_het={shet:.3g} ({classify_shet(shet)}); dominant-LoF selection "
                         f"coefficient (Zeng 2024)") if shet is not None else None,
        "method_version": METHOD_VERSION,
    }
