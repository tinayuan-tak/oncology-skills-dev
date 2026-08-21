"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, card1c arm).

Reconstruct the per-line concordance frame from the persisted plot_data_concordance.parquet (Stage 1,
read_crispr_rnai_concordance(plot_data_out=...)) and delegate to the SAME cli.emit_* draw functions a
live run uses — so the crispr-rnai-dependency-concordance figures (overlay-density + partition-bar +
scatter + interactive twin) render OFFLINE, with NO second CRISPR+RNAi load at figure time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

# emit_concordance_scatter keys on chronos vs demeter2 (both may be None for single-assay lines).
_REQUIRED_COLUMNS = ("chronos", "demeter2")


def render_from_plot_data(plot_data: "Union[str, Path, object]", summary: dict, out_dir: "Union[str, Path]",
                          target: str, indication: Optional[str] = None, *,
                          target_contracts_dir: "Optional[Union[str, Path]]" = None) -> list[dict]:
    """Render the crispr-rnai-dependency-concordance figures OFFLINE from persisted plot_data. NO live
    read. The partition-bar uses the passed `summary` (the card's compute_concordance output); the
    other panels replay the persisted per-line frame."""
    import pandas as pd

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")
    # Restore None from parquet's NaN so the `is not None` single-assay logic in the emitters holds
    # (a CRISPR-only line has demeter2=None, not NaN; NaN would wrongly pass `is not None`).
    per_line = df.astype(object).where(pd.notnull(df), None).to_dict("records")

    _cli.emit_concordance_overlay_density(per_line, target, out_dir, tcd)
    _cli.emit_concordance_scatter(per_line, target, out_dir, tcd)
    _cli.emit_partition_bar(summary, target, out_dir, tcd)

    static = [
        {"id": "concordance_overlay_density", "path": "figure_concordance_overlay_density.svg",
         "type": "overlay_kde_with_rug", "primary": True},
        {"id": "concordance_partition_bar", "path": "figure_concordance_partition_bar.svg",
         "type": "stacked_bar", "primary": False},
        {"id": "concordance_scatter", "path": "figure_concordance_scatter.svg",
         "type": "scatter_with_quadrants", "primary": False},
    ]
    dynamic: list[dict] = []
    try:
        specs = _cli.emit_plotly_specs(per_line, target, out_dir, tcd) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; SVGs are the contract
        pass
    return static + dynamic
