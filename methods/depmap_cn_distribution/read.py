"""depmap_cn_distribution.read — library entry for live-mode reads."""

from __future__ import annotations
from typing import Optional
from . import cli as _cli


def read_cn_distribution(target: str, indication: Optional[str] = None) -> Optional[dict]:
    """Compute pan-cancer CN distribution for target. WES-primary + WGS-fallback.
    Returns summary dict matching the copy-number-distribution card's outputs.summary_fields."""
    cn_by, mmeta, assay_used, load_errors = _cli.load_cn_files("26q1", target)
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap CN data or target absent from both WES + WGS panels.",
            "copy_number_class": "data_unavailable",
            "cn_assay_used": assay_used,
            "cn_distribution_shape": "unclassified",
        }
    return _cli.compute_summary_stats(cn_by, mmeta, assay_used=assay_used)
