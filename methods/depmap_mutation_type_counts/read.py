"""depmap_mutation_type_counts.read — library entry for live-mode reads."""

from __future__ import annotations
from typing import Optional
from . import cli as _cli


def read_mutation_type_counts(target: str, indication: Optional[str] = None) -> Optional[dict]:
    """Compute mutation-class counts for target across DepMap cell lines.
    Returns summary dict matching the mutation-type-counts card's outputs.summary_fields."""
    target_rows, model_meta, n_total, load_errors = _cli.load_mutation_data("26q1", target)
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap MAF data.",
            "mutation_landscape_class": "data_unavailable",
            "mut_dominant_mutation_class": "none",
        }
    return _cli.compute_summary_stats(target_rows, model_meta, n_total)
