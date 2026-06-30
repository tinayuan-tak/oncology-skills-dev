"""depmap_demeter_distribution.read — library entry point for live-mode reads.

Exposes read_pan_cancer_rnai_distribution(target, indication) returning the summary
dict for the pan-cancer-rnai-dependency-distribution card. The indication is
accepted for dispatcher signature consistency but not consumed (this card is
pan-cancer by definition).

When RNAi data is unreachable, returns a dict with _live_read_error key; the
orchestrator's live-stub-fallback mode then falls back to the stub fixture.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_pan_cancer_rnai_distribution(target: str, indication: Optional[str] = None,
                                       strong_threshold: float = -0.5,
                                       moderate_threshold: float = -0.25) -> Optional[dict]:
    """Compute the pan-cancer RNAi dependency distribution for target. Returns the
    summary dict matching the pan-cancer-rnai-dependency-distribution card's
    outputs.summary_fields. The `indication` parameter is intentionally ignored.

    Returns scalars only; no figures or plot_data. Figure emission is the
    figure-emitter's job (called by compose-dashboard's _figure_emitters.py).
    """
    demeter_by_model, model_metadata, load_errors = _cli.load_rnai_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap 26Q1 RNAi data; verify local cache or AWS credentials.",
            "rnai_dependency_class": "data_unavailable",
            "rnai_distribution_shape": "unclassified",
        }
    if not demeter_by_model:
        return {
            "_live_read_error": "no_data_for_target",
            "rnai_dependency_class": "data_unavailable",
            "rnai_distribution_shape": "unclassified",
        }

    summary = _cli.compute_summary_stats(
        demeter_by_model, model_metadata,
        strong_threshold=strong_threshold,
        moderate_threshold=moderate_threshold,
    )
    return summary
