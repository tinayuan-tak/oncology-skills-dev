"""depmap_expression_distribution.read — library entry point for live-mode reads."""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_expression_distribution(target: str, indication: Optional[str] = None,
                                  expressed_threshold: float = 1.0) -> Optional[dict]:
    """Compute pan-cancer expression distribution for target. Returns summary dict
    matching the expression-distribution card's outputs.summary_fields."""
    tpm_by_model, model_metadata, load_errors = _cli.load_expression_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap 26Q1 expression data.",
            "expression_class": "data_unavailable",
        }
    if not tpm_by_model:
        return {
            "_live_read_error": "no_data_for_target",
            "expression_class": "data_unavailable",
        }
    return _cli.compute_summary_stats(tpm_by_model, model_metadata,
                                       expressed_threshold=expressed_threshold)
