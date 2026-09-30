"""depmap_prism_crispr_concordance.read — library entry for compose-dashboard.

Reads one gene row from the v4 shared parquet at
`s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v4/prism_activity_per_gene.parquet`.
Same parquet as E6 (PRISM compound activity), different card — this one exposes
the concordance fields (per_compound_concordance + crispr_prism_concordance_class
+ dual_responders).
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli

DEFAULT_AWS_PROFILE = "cbg"
DEFAULT_RELEASE_PIN = "prism-activity-v4"


from onc_methods.target_id_sidecar import ensure_aws_profile


def read_prism_crispr_concordance(
    target: str, indication: Optional[str] = None, release_pin: str = DEFAULT_RELEASE_PIN
) -> dict:
    """Read CRISPR × RNAi × PRISM concordance for a target — pan-cancer,
    indication-independent (correlation across the full DepMap cell-line panel;
    lineage stratification is out of scope for this card)."""
    ensure_aws_profile()
    parquet_uri = _cli.RELEASE_PIN_TO_PARQUET.get(release_pin)
    if parquet_uri is None:
        return {
            "_live_read_error": "unknown_release_pin",
            "_remediation": f"release_pin {release_pin!r} not in {list(_cli.RELEASE_PIN_TO_PARQUET.keys())}",
            "crispr_prism_concordance_class": _cli.CONCORDANCE_DATA_UNAVAILABLE,
            "n_compounds_evaluated": 0,
            "per_compound_concordance": [],
            "best_spearman_r_crispr": None,
            "best_spearman_r_rnai": None,
            "n_dual_responders": 0,
            "dual_responders": [],
        }
    try:
        row = _cli.fetch_concordance_row(parquet_uri, target)
    except Exception as e:
        return {
            "_live_read_error": "s3_read_failed",
            "_remediation": f"Could not read {parquet_uri}: {type(e).__name__}: {e}",
            "crispr_prism_concordance_class": _cli.CONCORDANCE_DATA_UNAVAILABLE,
            "n_compounds_evaluated": 0,
            "per_compound_concordance": [],
            "best_spearman_r_crispr": None,
            "best_spearman_r_rnai": None,
            "n_dual_responders": 0,
            "dual_responders": [],
        }
    return _cli.compute_summary(row, target)
