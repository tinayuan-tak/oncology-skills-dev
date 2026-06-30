"""depmap_mutation_dependency.read — library entry for Card 3 live-mode reads.

Delegates to cli.load_depmap_files (via depmap_chronos_distribution reuse) +
cli.load_mutation_data + cli.compute_mutation_stratification. Matches the
canonical Card 1+2 pattern (read.py is a thin delegate over cli helpers; no
duplicate compute logic).

When the underlying data is unreachable, returns a dict with `_live_read_error`
AND `mutation_stratification_class: "data_unavailable"` (Tier-2 vocabulary
contract — descriptive label always present so the Tier-2 rule for
data_unavailable can fire).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

from . import cli as _cli

DEFAULT_AWS_PROFILE = "cbg"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def read_mutation_stratified_dependency(
    target: str,
    indication: Optional[str] = None,
) -> dict:
    """Compute mutation-stratified dependency for target across the DepMap panel.

    `indication` is accepted for back-compat with the dispatcher signature but is
    NOT consumed by the compute path. Card 3 is target-only per Decision 2A —
    the per-indication mutation prevalence + indication-specific stratification
    are downstream synthesis concerns.

    Returns dict matching Card 3's outputs.summary_fields, or a dict with
    _live_read_error key when data is unreachable.
    """
    _ensure_aws_profile()

    # Reuse Card 1's loader for Chronos
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))
    from methods.depmap_chronos_distribution import cli as c1cli

    chronos_by_model, model_metadata, chronos_errs = c1cli.load_depmap_files(
        release_pin="26q1", target_symbol=target
    )
    if chronos_errs:
        return {
            "_live_read_error": chronos_errs[0].get("_live_read_error", "s3_or_local_read_failed"),
            "errors": chronos_errs,
            "_remediation": "Method cannot reach DepMap 26Q1 Chronos; verify local cache or AWS credentials.",
            "mutation_stratification_class": "data_unavailable",
        }
    if not chronos_by_model:
        return {
            "_live_read_error": "no_chronos_for_target",
            "target": target,
            "mutation_stratification_class": "data_unavailable",
        }

    hotspot_by_model, damaging_by_model, mut_errs = _cli.load_mutation_data(
        release_pin="26q1", target_symbol=target
    )
    if mut_errs:
        return {
            "_live_read_error": mut_errs[0].get("_live_read_error", "mutation_read_failed"),
            "errors": mut_errs,
            "mutation_stratification_class": "data_unavailable",
        }

    return _cli.compute_mutation_stratification(
        chronos_by_model, hotspot_by_model, damaging_by_model
    )
