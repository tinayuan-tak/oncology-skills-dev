"""depmap_prism_activity.read — library entry for compose-dashboard live-mode reads.

Reads one row from the frozen `depmap-prism-activity-v4` derived parquet via
pyarrow predicate pushdown. No PRISM CSV parsing at framework runtime.

On unreachable parquet, returns a dict with `_live_read_error` +
`prism_activity_class=data_unavailable` so the framework's graceful-degradation
contract holds. On target-absent-from-aggregate (no PRISM-annotated compounds
across either release), returns `prism_activity_class=no_compounds_found` —
this is a real class call, NOT a data-availability gap.

v2 (2026-07-01): adds per_lineage_activity + prism_lineage_selectivity fields
to the returned summary.
"""

from __future__ import annotations

import os
from typing import Optional

from . import cli as _cli

DEFAULT_AWS_PROFILE = "cbg"
DEFAULT_RELEASE_PIN = "prism-activity-v4"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def read_prism_activity(target: str, indication: Optional[str] = None,
                          release_pin: str = DEFAULT_RELEASE_PIN) -> dict:
    """Read PRISM activity for a target — pan-cancer, indication-independent.

    `indication` is accepted for the framework's CARD_DISPATCHERS contract but
    NOT consumed by v1 — lineage-specific PRISM activity is a v2 scope item
    (would require re-aggregating LFC per-lineage using DepMap cell-line
    lineage metadata).
    """
    _ensure_aws_profile()
    parquet_uri = _cli.RELEASE_PIN_TO_PARQUET.get(release_pin)
    if parquet_uri is None:
        return {
            "_live_read_error": "unknown_release_pin",
            "_remediation": f"release_pin {release_pin!r} not in "
                              f"{list(_cli.RELEASE_PIN_TO_PARQUET.keys())}",
            "prism_activity_class": _cli.CLASS_DATA_UNAVAILABLE,
            "n_compounds_targeting": 0,
            "highest_clinical_phase": None,
            "median_log2auc_across_compounds": None,
            "top_compounds": [],
            "per_lineage_activity": [],
            "prism_lineage_selectivity": _cli.LINEAGE_SEL_DATA_UNAVAILABLE,
        }
    try:
        row = _cli.fetch_prism_row(parquet_uri, target)
    except Exception as e:
        return {
            "_live_read_error": "s3_read_failed",
            "_remediation": f"Could not read {parquet_uri}: {type(e).__name__}: {e}",
            "prism_activity_class": _cli.CLASS_DATA_UNAVAILABLE,
            "n_compounds_targeting": 0,
            "highest_clinical_phase": None,
            "median_log2auc_across_compounds": None,
            "top_compounds": [],
            "per_lineage_activity": [],
            "prism_lineage_selectivity": _cli.LINEAGE_SEL_DATA_UNAVAILABLE,
        }
    return _cli.compute_summary(row, target)
