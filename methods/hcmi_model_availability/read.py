"""hcmi_model_availability.read — card-side reader for the per-indication HCMI model-availability product.

Reads the MATERIALIZED per-indication table (one row per framework indication) and returns the
translational model-availability summary the target-model-availability card consumes. This is an
INDICATION-level signal (target-INDEPENDENT — "how many patient-derived HCMI organoid/cell models exist
for indication Y to preclinically validate any target"), so only `indication` filters. Graceful
data_unavailable when the indication is not in the HCMI crosswalk (no mapped models) or the product is
absent. Mirrors pancan_mutation_ccf.read's S3-resolve pattern (aws s3 cp -> pandas).
"""
from __future__ import annotations

import io
import os
import subprocess
from functools import lru_cache
from typing import Optional

_DERIVED_S3 = ("s3://onc-compbio/data-catalog/derived/"
               "hcmi-model-availability-per-indication-v1/hcmi_model_availability_per_indication.parquet")

_UNAVAILABLE = {
    "model_availability_class": "data_unavailable",
    "n_patient_derived_models": 0,
    "primary_site_breakdown": None,
    "source": "HCMI-CMDC-DR45",
}


def _ensure_aws_profile() -> None:
    os.environ.setdefault("AWS_PROFILE", "cbg")


@lru_cache(maxsize=2)
def _load_product(product_path: "Optional[str]" = None):
    """Load the per-indication model-availability product (local product_path override for tests, else S3)."""
    import pandas as pd
    if product_path:
        from pathlib import Path
        return pd.read_parquet(product_path) if Path(product_path).exists() else None
    _ensure_aws_profile()
    try:
        raw = subprocess.run(["aws", "s3", "cp", _DERIVED_S3, "-"],
                             capture_output=True, timeout=120).stdout
        return pd.read_parquet(io.BytesIO(raw)) if raw else None
    except Exception:  # noqa: BLE001 — product unreachable → data_unavailable, never raise into the card
        return None


def read_model_availability(indication: "Optional[str]" = None, product_path: "Optional[str]" = None,
                            *, target: "Optional[str]" = None) -> dict:
    """Per-indication HCMI patient-derived model-availability summary. VERDICT-INERT translational signal.

    `target` is accepted (and IGNORED) to satisfy the compose-dashboard generic-dispatch contract
    (_live_readers._generic_dispatch calls every reader as fn(target=, indication=)): model
    availability is INDICATION-level / target-INDEPENDENT, so the target symbol is irrelevant here."""
    df = _load_product(product_path)
    if df is None or df.empty:
        return dict(_UNAVAILABLE, _missing_reason="no HCMI model-availability product materialized/reachable")
    hit = df[df["indication"] == indication]
    if hit.empty:
        return dict(_UNAVAILABLE,
                    _missing_reason=f"{indication} not in the HCMI (primary_site, disease_type) crosswalk "
                                    f"(no mapped patient-derived models)")
    row = hit.iloc[0]
    return {
        "model_availability_class": row["model_availability_class"],
        "n_patient_derived_models": int(row["n_patient_derived_models"]),
        "primary_site_breakdown": row["primary_site_breakdown"],
        "source": row["source"],
    }
