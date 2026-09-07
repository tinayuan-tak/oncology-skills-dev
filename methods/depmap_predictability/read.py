"""depmap_predictability.read — v2 library entry for live-mode reads.

Reads one row out of the frozen derived parquet (default pin 26q1-v3)
`s3://onc-compbio/data-catalog/derived/depmap-predictability-26q1-v3/predictability_per_gene.parquet`
via pyarrow predicate pushdown. No sklearn / XGBoost at framework runtime.

On unreachable parquet or missing target, returns a dict with
`_live_read_error` + `predictability_class=data_unavailable` so the framework's
graceful-degradation contract holds (same shape as E1-E4).
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli

DEFAULT_AWS_PROFILE = "cbg"
DEFAULT_RELEASE_PIN = "26q1-v3"


from methods.target_id_sidecar import ensure_aws_profile


def read_predictability(target: str, indication: Optional[str] = None, release_pin: str = DEFAULT_RELEASE_PIN) -> dict:
    """Compute predictability for a target — pan-cancer, indication-independent.

    `indication` is accepted for the framework's CARD_DISPATCHERS contract but
    NOT consumed by v2 — the model uses lineage as a FEATURE, not a stratification
    axis. Per-lineage read-outs are exposed via `per_lineage_predictability`.
    """
    ensure_aws_profile()
    parquet_uri = _cli.RELEASE_PIN_TO_PARQUET.get(release_pin)
    if parquet_uri is None:
        return {
            "_live_read_error": "unknown_release_pin",
            "_remediation": f"release_pin {release_pin!r} not in {list(_cli.RELEASE_PIN_TO_PARQUET.keys())}",
            "predictability_class": "data_unavailable",
            "pred_dominant_feature_class": "data_unavailable",
        }
    try:
        row = _cli.fetch_predictability_row(parquet_uri, target)
    except Exception as e:
        return {
            "_live_read_error": "s3_read_failed",
            "_remediation": f"Could not read {parquet_uri}: {e}",
            "predictability_class": "data_unavailable",
            "pred_dominant_feature_class": "data_unavailable",
        }
    return _cli.compute_summary(row, target)
