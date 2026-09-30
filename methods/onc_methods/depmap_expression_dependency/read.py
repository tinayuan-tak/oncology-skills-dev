"""depmap_expression_dependency.read — library entry for Card 4 (live mode).

Delegates to cli.load_depmap_files_for_card4 + cli.compute_correlation_summary —
same DRY pattern as Card 1 + Card 2 method packages. Returns the summary dict
matching cards/expression-dependency-correlation.card.yaml's outputs.summary_fields,
or a structured _live_read_error when data is unreachable.

This function does NOT emit figures or plot_data; it returns scalars only. For
full card emission (with SVGs + parquet), the framework's figure-emission
registry (skills/compose-dashboard/scripts/_figure_emitters.py) re-invokes the
cli's emit_*_plot helpers separately.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import cli as _cli

DEFAULT_AWS_PROFILE = "cbg"


from onc_methods.target_id_sidecar import ensure_aws_profile


def read_expression_dependency(
    target: str, indication: Optional[str] = None, plot_data_out: Optional[Path] = None
) -> dict:
    """Compute expression-vs-Chronos correlation for target gene in indication.

    Args:
      target: HGNC symbol (e.g. 'KRAS')
      indication: OncoTree-style code ('COADREAD', 'PDAC', ...). Required for
                  target-lineage highlighting; if None, falls back to pan-cancer.

    Returns:
      Dict matching Card 4's outputs.summary_fields OR a dict with _live_read_error
      key when data is unreachable.
    """
    ensure_aws_profile()

    if indication is None:
        indication = ""

    chronos_by_model, tpm_by_model, model_metadata, load_errors = _cli.load_depmap_files_for_card4(
        release_pin="26q3", target_symbol=target
    )

    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "s3_or_local_read_failed"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap 26Q3; verify local cache or AWS credentials.",
            # Tier-2 vocabulary: always emit correlation_class so rules can fire on data_unavailable.
            "correlation_class": "data_unavailable",
        }

    if not chronos_by_model or not tpm_by_model:
        return {
            "_live_read_error": "no_data_for_target",
            "target": target,
            "_remediation": f"target {target!r} not in either CRISPRGeneEffect or TPM matrix; confirm HGNC symbol.",
            "correlation_class": "data_unavailable",
        }

    # Figure Stage 6: persist the per-cell-line merged frame during resolution so the figure renders
    # offline from it (no second DepMap load at figure time). Best-effort, verdict-inert.
    if plot_data_out is not None:
        try:
            plot_data_out.mkdir(parents=True, exist_ok=True)
            target_lineage = _cli.INDICATION_LINEAGE.get(indication, "")
            merged = _cli.build_merged_data(chronos_by_model, tpm_by_model, model_metadata, target_lineage)
            _cli.emit_plot_data(merged, plot_data_out)
        except Exception:  # noqa: BLE001 — persistence best-effort; never break the verdict read
            pass

    return _cli.compute_correlation_summary(
        chronos_by_model,
        tpm_by_model,
        model_metadata,
        indication=indication,
    )
