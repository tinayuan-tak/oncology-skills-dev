"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, card4 arm).

Reconstruct the merged per-cell-line frame from the persisted plot_data.parquet (Stage 1,
read_expression_dependency(plot_data_out=...)) and delegate to the SAME cli.emit_* draw functions a
live run uses — so the expression-dependency-correlation figures (scatter_with_regression +
lineage_stratified_scatter) render OFFLINE, deterministically, with NO second DepMap/S3 read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

# emit_scatter/lineage_stratified consume the merged frame directly (chronos vs tpm_logp1 axes).
_REQUIRED_COLUMNS = ("chronos", "tpm_logp1")


def render_from_plot_data(plot_data: "Union[str, Path, object]", summary: dict, out_dir: "Union[str, Path]",
                          target: str, indication: Optional[str] = None, *,
                          target_contracts_dir: "Optional[Union[str, Path]]" = None) -> list[dict]:
    """Render the expression-dependency-correlation figures OFFLINE from persisted plot_data. NO live
    read — replays the persisted merged frame into the same cli.emit_* draw functions a live run uses.
    Reference lines/stats come from the passed `summary` (the card's compute_correlation_summary)."""
    import pandas as pd

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")
    merged = df.to_dict("records")

    _cli.emit_scatter_regression_plot(merged, target, indication, summary, out_dir, tcd)
    _cli.emit_lineage_stratified_scatter(merged, target, indication, summary, out_dir, tcd)

    # Descriptor shape mirrors the registry emitter (_emit_card4_expression_dependency_correlation);
    # card4 has no plotly twin.
    return [
        {"id": "scatter_with_regression", "path": "figure_scatter_with_regression.svg",
         "type": "expression_chronos_scatter", "primary": True},
        {"id": "lineage_stratified_scatter", "path": "figure_lineage_stratified_scatter.svg",
         "type": "lineage_stratified_scatter", "primary": False},
    ]
