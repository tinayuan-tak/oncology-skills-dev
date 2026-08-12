"""tcga_mc3_signatures.read — library entry for the per-indication mutational-signature context facet.

Reads the MATERIALIZED per-indication rollup (tcga-mc3-mutational-signatures-per-indication-v1) and
returns the mutational-signature-context card's summary_fields for the requested indication. Read
grain is pre-aggregated → an O(1) per-indication lookup (no per-sample refit at run time).

Target-INDEPENDENT (tier: indication): the mutagenic-process profile is a cohort property; a target
maps in only as "which indication am I in". Verdict-INERT: no resolver rung.
"""
from __future__ import annotations

import io
import os
import subprocess
from typing import Optional

from . import cli as _cli
from .signatures import INFORMATIVE_PROCESSES, NON_BASELINE_PROCESSES

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "tcga-mc3-mutational-signatures-per-indication-v1"


def _resolve_derived_uri() -> str:
    from methods.catalog_query.read import s3_uri_for
    return s3_uri_for(DERIVED_MANIFEST_ID)


def _ensure_aws_profile() -> None:
    os.environ.setdefault("AWS_PROFILE", DEFAULT_AWS_PROFILE)


def _load_product():
    import pandas as pd
    _ensure_aws_profile()
    raw = subprocess.run(["aws", "s3", "cp", _resolve_derived_uri(), "-"],
                         capture_output=True, timeout=120).stdout
    if not raw:
        raise RuntimeError(f"could not load materialized product {DERIVED_MANIFEST_ID}")
    return pd.read_parquet(io.BytesIO(raw))


def read_mutational_signature_context(target: Optional[str] = None,
                                      indication: Optional[str] = None) -> dict:
    """Return the mutational-signature-context card's summary_fields for the indication.

    `target` accepted for the dispatcher signature but NOT consumed (cohort-level, target-independent).
    Returns data_unavailable when the indication is not in the product.
    """
    if not indication:
        return {"dominant_process": "data_unavailable",
                "_note": "indication required (signature context is a per-indication cohort facet)."}
    df = _load_product()
    hit = df[df["indication"].astype(str).str.upper() == indication.upper()]
    if hit.empty:
        return {"dominant_process": "data_unavailable", "indication": indication,
                "_note": f"{indication} not in the TCGA-MC3 signature product (v1 covers "
                         f"{sorted(df['indication'].unique())})."}
    row = hit.iloc[0].to_dict()
    out = {
        "indication": indication,
        "n_samples": int(row["n_samples"]),
        "dominant_process": row["dominant_process"],
        "enriched_processes": row["enriched_processes"],
    }
    for pr in INFORMATIVE_PROCESSES:
        out[f"{pr}_class"] = row.get(f"{pr}_class")
        out[f"frac_{pr}_high"] = row.get(f"frac_{pr}_high")
    out["_method_version"] = METHOD_VERSION
    out["_source"] = ("TCGA MC3 v0.2.8 → SigProfilerAssignment COSMIC v3.3; "
                      "verdict-inert cohort context")
    return out
