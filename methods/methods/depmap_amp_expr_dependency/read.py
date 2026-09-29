"""depmap_amp_expr_dependency.read — library entry point for amp→expr→dependency three-way.

Composes THREE live {ModelID -> value} loaders (mirrors depmap_cn_dependency/read.py, +expression):
  - Chronos  via depmap_chronos_distribution.load_depmap_files      ({ModelID -> chronos})
  - rel. CN  via depmap_cn_distribution.load_cn_files               ({ModelID -> relative CN}, bridged)
  - log2TPM  via depmap_expression_distribution.load_expression_files ({ModelID -> log2(TPM+1)})
then cli.compute_amp_expr_stratification (conjoint amplified∩high-TPM vs rest). Target-only (indication
accepted for the dispatcher signature, not consumed).

Returns the amp-expr-stratified-dependency card's summary_fields, or a dict with _live_read_error when
the underlying DepMap data is unreachable.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"


from methods.target_id_sidecar import ensure_aws_profile


def read_amp_expr_dependency(target: str, indication: Optional[str] = None, release_pin: str = "26q3") -> dict:
    """Compute amplification+overexpression conjoint-stratified dependency for target across the panel.

    `indication` is accepted for dispatcher-signature back-compat but NOT consumed (target-only, like
    the mutation/CN/fusion stratified siblings). `release_pin` selects the DepMap release and is
    threaded into all three loaders (was previously hardcoded to "26q1", so the arg was ignored).
    Returns the card's summary_fields, or a dict with _live_read_error when data is unreachable.
    """
    ensure_aws_profile()
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))

    from methods.depmap_chronos_distribution import cli as c1cli
    from methods.depmap_cn_distribution import cli as cncli
    from methods.depmap_expression_distribution import cli as excli

    # 1. Chronos
    chronos_by_model, model_metadata, chronos_errs = c1cli.load_depmap_files(
        release_pin=release_pin, target_symbol=target
    )
    if chronos_errs:
        return {
            "_live_read_error": chronos_errs[0].get("_live_read_error", "s3_or_local_read_failed"),
            "errors": chronos_errs,
            "_remediation": "Method cannot reach DepMap 26Q3 Chronos; verify local cache or AWS credentials.",
            "amp_expr_stratification_class": "data_unavailable",
        }
    if not chronos_by_model:
        return {
            "_live_read_error": "no_chronos_for_target",
            "target": target,
            "amp_expr_stratification_class": "data_unavailable",
        }

    # 2. Relative CN (bridged ModelConditionID -> ModelID by load_cn_files)
    cn_by_model, _cn_meta, assay_used, cn_errs = cncli.load_cn_files(release_pin=release_pin, target_symbol=target)
    if cn_errs or not cn_by_model:
        return {
            "_live_read_error": (
                cn_errs[0].get("_live_read_error", "cn_read_failed") if cn_errs else "no_cn_for_target"
            ),
            "errors": cn_errs,
            "_remediation": "Method cannot reach DepMap 26Q3 copy number; verify local cache or AWS credentials.",
            "amp_expr_stratification_class": "data_unavailable",
        }

    # 3. log2TPM expression
    tpm_by_model, _tpm_meta, tpm_errs = excli.load_expression_files(release_pin=release_pin, target_symbol=target)
    if tpm_errs or not tpm_by_model:
        return {
            "_live_read_error": (
                tpm_errs[0].get("_live_read_error", "expression_read_failed")
                if tpm_errs
                else "no_expression_for_target"
            ),
            "errors": tpm_errs,
            "_remediation": "Method cannot reach DepMap 26Q3 expression; verify local cache or AWS credentials.",
            "amp_expr_stratification_class": "data_unavailable",
        }

    # INDICATION-CONDITIONED ladder — within-lineage when powered, else pan-DepMap
    # (strong→moderate). Compute kernel unchanged. See depmap_common.lineage_ladder.
    from methods.depmap_common.lineage_ladder import apply_lineage_ladder

    def _compute(mut_models, wt_models):
        # amp_expr's POSITIVE arm (amplified AND top-tertile-TPM) is a CONJOINT computed inside the
        # kernel from the evaluated set's tertile — it can't be split by arm at the read layer. And
        # the high-prevalence-driver problem (the reason the ladder has a lineage-restricted-comparator
        # step) doesn't arise for a conjoint (rarely >30% of a lineage). So amp_expr restricts the whole
        # evaluated set to the in-lineage intersection of the two arms (None = all); the
        # lineage-restricted-comparator step degenerates to the full lineage set here — harmless, since
        # without a separable positive arm it equals the plain within-lineage restriction.
        restrict = None
        if mut_models is not None and wt_models is not None:
            restrict = mut_models & wt_models
        elif mut_models is not None:
            restrict = mut_models
        elif wt_models is not None:
            restrict = wt_models
        if restrict is None:
            return _cli.compute_amp_expr_stratification(chronos_by_model, cn_by_model, tpm_by_model)
        c = {m: v for m, v in chronos_by_model.items() if m in restrict}
        cn = {m: v for m, v in cn_by_model.items() if m in restrict}
        t = {m: v for m, v in tpm_by_model.items() if m in restrict}
        return _cli.compute_amp_expr_stratification(c, cn, t)

    summary = apply_lineage_ladder(_compute, "amp_expr_stratification_class", model_metadata, indication)
    summary["_cn_assay_used"] = assay_used  # WGS (primary) or WES (fallback), provenance
    return summary
