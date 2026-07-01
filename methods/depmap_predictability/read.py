"""depmap_predictability.read — library entry for live-mode reads (E5).

Returns the predictability summary for a target by reading one row out of the
frozen derived parquet via pyarrow predicate pushdown. No sklearn at runtime.

When the parquet is unreachable (no AWS creds, no network, S3 ACL denied),
returns a dict with `_live_read_error` + `predictability_class=data_unavailable`
so the framework's graceful-degradation contract holds (same shape as E1-E4).
"""

from __future__ import annotations

import os
from typing import Optional

from . import cli as _cli

DEFAULT_AWS_PROFILE = "cbg"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def read_predictability(target: str, indication: Optional[str] = None,
                          release_pin: str = "26q1-v1") -> dict:
    """Compute predictability for a target — pan-cancer, indication-independent.

    The `indication` parameter is accepted to match the framework's
    CARD_DISPATCHERS contract (target, indication) but NOT consumed: E5 is
    target-only because the precompute model uses lineage one-hots as features,
    not as a stratification axis.
    """
    _ensure_aws_profile()
    parquet_uri = _cli.RELEASE_PIN_TO_PARQUET.get(release_pin)
    if parquet_uri is None:
        return {
            "_live_read_error": "unknown_release_pin",
            "_remediation": f"release_pin {release_pin!r} not in "
                              f"{list(_cli.RELEASE_PIN_TO_PARQUET.keys())}",
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
