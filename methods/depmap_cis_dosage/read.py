"""depmap_cis_dosage.read — library entry point for cis-feature → own-expression coupling.

Composes TWO live {ModelID -> value} loaders (mirrors depmap_amp_expr_dependency/read.py, MINUS Chronos):
  - rel. CN  via depmap_cn_distribution.load_cn_files                ({ModelID -> relative CN}, bridged)
  - log2TPM  via depmap_expression_distribution.load_expression_files ({ModelID -> log2(TPM+1)})
then cli.compute_cis_dosage (CN↔expression Spearman). Target-only; `indication` is accepted for the
dispatcher signature but the correlation is PAN-PANEL (a per-indication cis-dosage correlation is rarely
powered — few lines per lineage — so it is deferred to a later within-lineage refinement; evidence_scope
is reported as pan_no_indication accordingly).

Returns the cis-feature-expression-coherence card's summary_fields, or a dict with _live_read_error +
cis_dosage_class=data_unavailable when the underlying DepMap data is unreachable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"

from methods.target_id_sidecar import ensure_aws_profile


def read_cis_dosage(target: str, indication: Optional[str] = None,
                    release_pin: str = "26q1", plot_data_out: Optional[Path] = None) -> dict:
    """Compute cis-dosage (own-CN → own-expression) coupling for target across the DepMap panel.

    `indication` is accepted for dispatcher-signature back-compat but NOT consumed (target-only,
    pan-panel correlation). `release_pin` selects the DepMap release and is threaded into both loaders.
    Returns the card's summary_fields, or a dict with _live_read_error when data is unreachable.
    """
    ensure_aws_profile()
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))

    from methods.depmap_cn_distribution import cli as cncli
    from methods.depmap_expression_distribution import cli as excli

    def _unavailable(err: str, errors: list | None = None, remediation: str | None = None) -> dict:
        out = {
            "_live_read_error": err,
            "cis_dosage_class": "data_unavailable",
            "evidence_scope": "pan_no_indication",
        }
        if errors:
            out["errors"] = errors
        if remediation:
            out["_remediation"] = remediation
        return out

    # 1. Relative CN (bridged ModelConditionID -> ModelID by load_cn_files)
    cn_by_model, cn_meta, assay_used, cn_errs = cncli.load_cn_files(
        release_pin=release_pin, target_symbol=target
    )
    if cn_errs or not cn_by_model:
        return _unavailable(
            cn_errs[0].get("_live_read_error", "cn_read_failed") if cn_errs else "no_cn_for_target",
            errors=cn_errs,
            remediation="Method cannot reach DepMap 26Q1 copy number; verify local cache or AWS credentials.",
        )

    # 2. log2TPM expression
    tpm_by_model, _tpm_meta, tpm_errs = excli.load_expression_files(
        release_pin=release_pin, target_symbol=target
    )
    if tpm_errs or not tpm_by_model:
        return _unavailable(
            tpm_errs[0].get("_live_read_error", "expression_read_failed") if tpm_errs else "no_expression_for_target",
            errors=tpm_errs,
            remediation="Method cannot reach DepMap 26Q1 expression; verify local cache or AWS credentials.",
        )

    summary = _cli.compute_cis_dosage(cn_by_model, tpm_by_model)
    # Pan-panel correlation → the honest scope is pan_no_indication (within-lineage cis-dosage is a
    # later refinement; the cis_coherence resolver does not gate on evidence_scope at Stage 0).
    summary["evidence_scope"] = "pan_no_indication"
    summary["_cn_assay_used"] = assay_used   # WES (primary) or WGS (fallback), provenance

    # Figure Stage 6: persist the merged CN×TPM frame during resolution so the figure renders offline
    # from it (no second CN+expression load at figure time). Best-effort, verdict-inert.
    if plot_data_out is not None:
        try:
            from . import figures as _figs
            merged = _figs.build_merged_data(cn_by_model, tpm_by_model, cn_meta)
            _figs.emit_plot_data(merged, plot_data_out)
        except Exception:  # noqa: BLE001 — persistence best-effort; never break the verdict read
            pass
    return summary
