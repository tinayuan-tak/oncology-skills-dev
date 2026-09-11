"""depmap_cn_dependency.read — library entry point for copy-number-stratified dependency.

Delegates to depmap_chronos_distribution.load_depmap_files (Chronos) +
depmap_cn_distribution.load_cn_files (relative CN, already bridged to ModelID) +
cli.compute_cn_stratification. Mirrors depmap_mutation_dependency/read.py's shape +
error handling. Target-only (indication accepted for the dispatcher signature, not consumed).

Returns the copy-number-stratified-dependency card's summary_fields, or a dict with
_live_read_error when the underlying DepMap data is unreachable.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"


from methods.target_id_sidecar import ensure_aws_profile


def read_cn_stratified_dependency(target: str, indication: Optional[str] = None) -> dict:
    """Compute copy-number-stratified dependency for target across the DepMap panel.

    `indication` is accepted for dispatcher-signature back-compat but NOT consumed
    (target-only, like the mutation-stratified sibling). Returns the card's
    summary_fields, or a dict with _live_read_error when data is unreachable.
    """
    ensure_aws_profile()
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))

    from methods.depmap_chronos_distribution import cli as c1cli
    from methods.depmap_cn_distribution import cli as cncli

    # 1. Chronos (reuse Card-1's loader)
    chronos_by_model, model_metadata, chronos_errs = c1cli.load_depmap_files(release_pin="26q1", target_symbol=target)
    if chronos_errs:
        return {
            "_live_read_error": chronos_errs[0].get("_live_read_error", "s3_or_local_read_failed"),
            "errors": chronos_errs,
            "_remediation": "Method cannot reach DepMap 26Q1 Chronos; verify local cache or AWS credentials.",
            "cn_stratification_class": "data_unavailable",
        }
    if not chronos_by_model:
        return {
            "_live_read_error": "no_chronos_for_target",
            "target": target,
            "cn_stratification_class": "data_unavailable",
        }

    # 2. Relative CN (already bridged ModelConditionID → ModelID by load_cn_files)
    cn_by_model, _cn_meta, assay_used, cn_errs = cncli.load_cn_files(release_pin="26q1", target_symbol=target)
    if cn_errs or not cn_by_model:
        return {
            "_live_read_error": (
                cn_errs[0].get("_live_read_error", "cn_read_failed") if cn_errs else "no_cn_for_target"
            ),
            "errors": cn_errs,
            "_remediation": "Method cannot reach DepMap 26Q1 copy number; verify local cache or AWS credentials.",
            "cn_stratification_class": "data_unavailable",
        }

    # INDICATION-CONDITIONED ladder — within-lineage when powered, else pan-DepMap
    # (strong→moderate). Compute kernel unchanged. See depmap_common.lineage_ladder.
    from methods.depmap_common.lineage_ladder import apply_lineage_ladder

    def _compute(mut_models, wt_models):
        # amplified (cn>focal) = the "mutant" arm → mut_models; neutral = WT arm → wt_models.
        # MUST use FOCAL_AMP_HIGH (2.0) — the SAME focal HIGH-level cut compute_cn_stratification
        # applies (cli.py `focal_amp=FOCAL_AMP_HIGH`) to build its amplified vector. Using the
        # shallow FOCAL_AMP (1.5) here misroutes shallow-gain lines (1.5–2.0) into the amplified
        # arm, so they are dropped from the pan-WT comparator scope while the kernel still counts
        # them as neutral → an inconsistent, biased delta_chronos.
        from methods.depmap_cn_dependency.cli import FOCAL_AMP_HIGH

        def _keep(m):
            arm = mut_models if cn_by_model.get(m, 0) > FOCAL_AMP_HIGH else wt_models
            return arm is None or m in arm

        c = {m: v for m, v in chronos_by_model.items() if _keep(m)}
        cn = {m: v for m, v in cn_by_model.items() if m in c}
        return _cli.compute_cn_stratification(c, cn)

    summary = apply_lineage_ladder(_compute, "cn_stratification_class", model_metadata, indication)
    summary["_cn_assay_used"] = assay_used  # WGS (primary) or WES (fallback), provenance
    return summary
