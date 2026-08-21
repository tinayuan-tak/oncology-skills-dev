"""depmap_crispr_rnai_concordance.read — library entry point for live-mode reads."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import cli as _cli


def read_crispr_rnai_concordance(target: str, indication: Optional[str] = None,
                                 plot_data_out: Optional[Path] = None) -> Optional[dict]:
    """Compute CRISPR-RNAi concordance for target. Returns summary dict matching
    the crispr-rnai-dependency-concordance card's outputs.summary_fields."""
    chronos_by, demeter_by, model_meta, load_errors = _cli.load_concordance_inputs(target, "26q1")
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "_remediation": "Concordance card requires BOTH CRISPR + RNAi upstream loads to succeed; one or both failed.",
            "concordance_class": "data_unavailable",
        }
    if not chronos_by and not demeter_by:
        return {
            "_live_read_error": "no_data_for_target",
            "concordance_class": "data_unavailable",
        }
    result = _cli.compute_concordance(chronos_by, demeter_by, model_meta)

    # Figure Stage 6: persist the per-line concordance frame during resolution so the figure renders
    # offline from it (no second CRISPR+RNAi load at figure time). Best-effort, verdict-inert.
    if plot_data_out is not None and result and result.get("per_line_concordance"):
        try:
            plot_data_out.mkdir(parents=True, exist_ok=True)
            _cli.emit_plot_data(result["per_line_concordance"], plot_data_out)
        except Exception:  # noqa: BLE001 — persistence best-effort; never break the verdict read
            pass

    return result
