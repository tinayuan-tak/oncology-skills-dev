"""depmap_chronos_distribution.read — library entry point for live-mode reads.

Exposes a single function `read_pan_cancer_distribution(target, indication)` that
returns the summary dict for the pan-cancer-crispr-dependency-distribution card. The
indication parameter is accepted for dispatcher consistency but is NOT consumed:
this card is pan-cancer by definition (not lineage-filtered). Lineage-filtering is
the job of the sister `lineage-specific-dependency` card.

When the underlying DepMap data is unreachable (no local cache + no AWS creds),
returns a dict with `_live_read_error` key; the orchestrator's live-stub-fallback
mode then falls back to the stub fixture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import cli as _cli


def read_pan_cancer_distribution(target: str, indication: Optional[str] = None,
                                   strong_threshold: float = -1.0,
                                   moderate_threshold: float = -0.5) -> Optional[dict]:
    """Compute the pan-cancer dependency distribution for target. Returns the
    summary dict matching the pan-cancer-crispr-dependency-distribution card's
    outputs.summary_fields. The `indication` parameter is intentionally ignored
    (this card is pan-cancer).

    Note: this function does NOT emit figures or plot_data; it returns scalars only.
    For full card emission (with SVGs + parquet), use the CLI subprocess invocation
    via methods/depmap_chronos_distribution/cli.py. The framework's compose-dashboard
    runtime decides whether the live-reader scalar path is sufficient or whether to
    invoke the CLI for full artifacts.
    """
    chronos_by_model, model_metadata, load_errors = _cli.load_depmap_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap 26Q1; verify local cache or AWS credentials.",
            # Tier-2 vocabulary: always emit dependency_class so rules can fire on "data_unavailable".
            "dependency_class": "data_unavailable",
            "distribution_shape": "unclassified",
        }
    if not chronos_by_model:
        return {
            "_live_read_error": "no_data_for_target",
            "target": target,
            "_remediation": f"target {target!r} not found in CRISPRGeneEffect.csv; confirm HGNC symbol.",
            "dependency_class": "data_unavailable",
            "distribution_shape": "unclassified",
        }

    summary = _cli.compute_summary_stats(
        chronos_by_model, model_metadata,
        strong_threshold=strong_threshold,
        moderate_threshold=moderate_threshold,
    )

    # Axis-2 (contextualized interpretation): control-benchmark position. ADDITIVE +
    # verdict-inert — the dep_control_* fields anchor the target's Chronos against curated
    # pan-essential (ceiling) + non-essential (floor) controls so a reader can tell a
    # pan-essential tox liability from a selective dependency window. No rule reads them
    # (the dependency resolver is untouched). Wrapped so a control-read failure NEVER
    # breaks the primary distribution summary (degrades to data_unavailable).
    try:
        from methods.dependency_controls import control_position_dependency
        summary.update(control_position_dependency(target, release_pin="26q1"))
    except Exception as e:  # noqa: BLE001 — the control axis is a display facet, never load-bearing
        summary.setdefault("dep_control_position_class", "data_unavailable")
        summary.setdefault("_dep_control_note", f"control axis unavailable: {type(e).__name__}")

    return summary
