"""depmap_chronos.read — library entry point for live-mode reads (Card 2).

Exposes a single function `read_lineage_selectivity(target, indication)` that
returns the summary dict for the dependency-lineage-selectivity card. Reuses the
loader + compute helpers from cli.py rather than duplicating them — matches the
canonical pattern established by Card 1 (methods/depmap_chronos_distribution).

When the underlying DepMap data is unreachable (no local cache + no AWS creds),
returns a dict with `_live_read_error` key; the orchestrator's live-stub-fallback
mode then falls back to the stub fixture.

This function does NOT emit figures or plot_data; it returns scalars only. For
full card emission (with SVGs + parquet), the framework's figure-emission
registry (skills/compose-dashboard/scripts/_figure_emitters.py) re-invokes the
cli's emit_* helpers separately. Same code path the unit tests exercise.
"""

from __future__ import annotations

import os
from typing import Optional

from . import cli as _cli

DEFAULT_AWS_PROFILE = "cbg"

# Indication → OncotreeLineage mapping (DepMap Model.csv categorical).
# Mirrors cli.compute_lineage_summary's INDICATION_LINEAGE; kept here for back-compat
# imports (some tests reference INDICATION_TO_DEPMAP_LINEAGE directly).
INDICATION_TO_DEPMAP_LINEAGE = {
    "COADREAD": "Bowel",
    "PDAC": "Pancreas",
    "NSCLC": "Lung",
    "SCLC": "Lung",
    "GC": "Stomach",
}


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def read_lineage_selectivity(
    target: str,
    indication: str,
    strong_threshold: float = -1.0,
    moderate_threshold: float = -0.5,
) -> dict:
    """Compute lineage selectivity for a target in an indication's DepMap lineage.

    Delegates to cli.load_depmap_files + cli.compute_lineage_summary — same code
    paths the CLI and the figure-emission registry use. Returns the dict shape
    matching Card 2's outputs.summary_fields.

    On data-unreachable errors, returns a dict with `_live_read_error` key.
    """
    _ensure_aws_profile()

    chronos_by_model, model_metadata, load_errors = _cli.load_depmap_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "s3_or_local_read_failed"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap 26Q1; verify local cache or AWS credentials.",
        }
    if not chronos_by_model:
        return {
            "_live_read_error": "no_data_for_target",
            "target": target,
            "_remediation": f"target {target!r} not found in CRISPRGeneEffect.csv; confirm HGNC symbol.",
        }

    return _cli.compute_lineage_summary(
        chronos_by_model, model_metadata, indication=indication,
        strong_threshold=strong_threshold,
        moderate_threshold=moderate_threshold,
    )
