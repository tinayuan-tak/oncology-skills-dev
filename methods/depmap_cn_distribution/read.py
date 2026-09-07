"""depmap_cn_distribution.read — library entry for live-mode reads."""

from __future__ import annotations
from pathlib import Path
from typing import Optional
from . import cli as _cli


def read_cn_distribution(
    target: str, indication: Optional[str] = None, plot_data_out: Optional[Path] = None
) -> Optional[dict]:
    """Compute pan-cancer CN distribution for target. WES-primary + WGS-fallback.
    Returns summary dict matching the copy-number-distribution card's outputs.summary_fields."""
    cn_by, mmeta, assay_used, load_errors = _cli.load_cn_files("26q1", target)
    if load_errors:
        return {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "_remediation": "Method cannot reach DepMap CN data or target absent from both WES + WGS panels.",
            "copy_number_class": "data_unavailable",
            "cn_assay_used": assay_used,
            "cn_distribution_shape": "unclassified",
        }
    summary = _cli.compute_summary_stats(cn_by, mmeta, assay_used=assay_used)
    # Figure-consolidation Stage 1: OPT-IN persist plot_data during card RESOLUTION from the cn_by
    # frame already in memory, so figures.render_from_plot_data draws with NO live read. Best-effort;
    # never breaks the verdict read. Default None => byte-identical no-op.
    if plot_data_out is not None:
        try:
            _pd_dir = Path(plot_data_out)
            _pd_dir.mkdir(parents=True, exist_ok=True)
            _cli.emit_plot_data(cn_by, mmeta, _pd_dir)
        except Exception:  # noqa: BLE001 — plot_data persistence is additive; never break resolution
            pass
    return summary
