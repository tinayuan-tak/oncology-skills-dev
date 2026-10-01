"""depmap_predictability.read — v2 library entry for live-mode reads.

Reads one row out of the frozen derived parquet (default pin 26q3-v4; 26q1-v* selectable)
`s3://onc-compbio/data-catalog/derived/depmap-predictability-26q3-v4/predictability_per_gene.parquet`
via pyarrow predicate pushdown. No sklearn / XGBoost at framework runtime.

On unreachable parquet or missing target, returns a dict with
`_live_read_error` + `predictability_class=data_unavailable` so the framework's
graceful-degradation contract holds (same shape as E1-E4).

Every returned dict carries provenance metadata — `_release_pin` (the pin the row
was actually read with) and `_derived_product_uri` (the resolved parquet, or None
when the pin did not resolve). Out-of-band consumers that stamp an evidence
manifest (e.g. the skills figure emitters) MUST read these rather than hardcoding
a pin, so provenance follows the data instead of drifting when the default moves.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli

DEFAULT_AWS_PROFILE = "cbg"
# Default is 26q3-v4 (#814): the 26Q3 genome-scope recompute (18,432 genes, true SHAP) is
# materialized at s3://…/derived/depmap-predictability-26q3-v4/ and its manifest is minted
# (data-catalog depmap-predictability-26q3-v4). The 26q1-v* pins remain selectable via
# `release_pin=` for reproducibility of historical runs.
DEFAULT_RELEASE_PIN = "26q3-v4"


from onc_methods.target_id_sidecar import ensure_aws_profile


def read_predictability(target: str, indication: Optional[str] = None, release_pin: str = DEFAULT_RELEASE_PIN) -> dict:
    """Compute predictability for a target — pan-cancer, indication-independent.

    `indication` is accepted for the framework's CARD_DISPATCHERS contract but
    NOT consumed by v2 — the model uses lineage as a FEATURE, not a stratification
    axis. Per-lineage read-outs are exposed via `per_lineage_predictability`.
    """
    ensure_aws_profile()

    def _with_provenance(summary: dict, parquet_uri: Optional[str]) -> dict:
        # Provenance follows the data (see module docstring): stamp the pin actually
        # used and the resolved parquet onto EVERY return path, so a consumer reads
        # it from the summary instead of hardcoding a literal that drifts.
        summary["_release_pin"] = release_pin
        summary["_derived_product_uri"] = parquet_uri
        return summary

    parquet_uri = _cli.RELEASE_PIN_TO_PARQUET.get(release_pin)
    if parquet_uri is None:
        return _with_provenance(
            {
                "_live_read_error": "unknown_release_pin",
                "_remediation": f"release_pin {release_pin!r} not in {list(_cli.RELEASE_PIN_TO_PARQUET.keys())}",
                "predictability_class": "data_unavailable",
                "pred_dominant_feature_class": "data_unavailable",
            },
            None,
        )
    try:
        row = _cli.fetch_predictability_row(parquet_uri, target)
    except Exception as e:
        return _with_provenance(
            {
                "_live_read_error": "s3_read_failed",
                "_remediation": f"Could not read {parquet_uri}: {e}",
                "predictability_class": "data_unavailable",
                "pred_dominant_feature_class": "data_unavailable",
            },
            parquet_uri,
        )
    return _with_provenance(_cli.compute_summary(row, target), parquet_uri)
