"""depmap_expression_distribution.read — library entry point for live-mode reads."""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_expression_distribution(target: str, indication: Optional[str] = None,
                                  expressed_threshold: float = 1.0) -> Optional[dict]:
    """Compute pan-cancer expression distribution for target. Returns summary dict
    matching the cellline-rna-distribution card's outputs.summary_fields."""
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
    summary = _cli.compute_summary_stats(tpm_by_model, model_metadata,
                                         expressed_threshold=expressed_threshold)
    # All-gene percentile of the panel median (Phase 1C): where does this target's panel
    # median log2(TPM+1) sit among ALL ~19k protein-coding genes in the DepMap panel? A
    # single-gene predicate-pushdown lookup of the precomputed allgene-depmap-rank-26q1-v1
    # (NO re-scan of the wide matrix). Additive/display — never flips expression_class.
    try:
        from methods.allgene_percentile_precompute.lookup import depmap_allgene_percentile
        summary.update(depmap_allgene_percentile(target))
    except Exception:  # noqa: BLE001 — enrichment is best-effort; core summary stands
        summary.setdefault("allgene_percentile", None)
        summary.setdefault("allgene_percentile_class", "data_unavailable")
        summary.setdefault("allgene_percentile_context", None)
    return summary
