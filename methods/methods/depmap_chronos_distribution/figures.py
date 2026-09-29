"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 2, chronos arm).

Parallel to depmap_expression_distribution/figures.py: reconstruct the chronos_by_model /
model_metadata dicts from the persisted plot_data.parquet (Stage 1) and delegate to the SAME
cli.emit_* draw functions a live run uses — so the pan-cancer-crispr-dependency-distribution figures
render OFFLINE, deterministically, byte-identical to a live run, with NO second S3/cbg read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

# The persisted plot_data long-frame columns (see cli.emit_plot_data): the serialized chronos frame.
_REQUIRED_COLUMNS = ("cell_line_id", "chronos_score")


def _reconstruct_frame(plot_data: "Union[str, Path, object]") -> tuple[dict, dict]:
    """Rebuild (chronos_by_model, model_metadata) from a plot_data DataFrame or parquet path — the
    inverse of cli.emit_plot_data. NO S3 access."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")

    chronos_by_model: dict = {}
    model_metadata: dict = {}
    for row in df.itertuples(index=False):
        mid = row.cell_line_id
        chronos_by_model[mid] = float(row.chronos_score)
        model_metadata[mid] = {
            "ModelID": mid,
            "CellLineName": getattr(row, "cell_line_name", None),
            "OncotreeLineage": getattr(row, "lineage", None),
            "OncotreeSubtype": getattr(row, "sub_lineage", None),
        }
    return chronos_by_model, model_metadata


def render_from_plot_data(
    plot_data: "Union[str, Path, object]",
    summary: dict,
    out_dir: "Union[str, Path]",
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir: "Optional[Union[str, Path]]" = None,
) -> list[dict]:
    """Render the pan-cancer-crispr-dependency-distribution figures OFFLINE from persisted plot_data +
    summary. NO live read — delegates to the same cli.emit_* draw functions a live run uses."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    chronos_by_model, model_metadata = _reconstruct_frame(plot_data)

    _cli.emit_waterfall_plot(chronos_by_model, model_metadata, target, summary, out_dir, tcd)
    _cli.emit_histogram_kde_plot(chronos_by_model, target, summary, out_dir, tcd)

    # Descriptor shape mirrors the current registry emitter (_emit_card1_pan_cancer_dependency_
    # distribution) with types canonicalized to the FIGURE_CATALOG closed enum (Stage 5).
    static = [
        {"id": "waterfall", "path": "figure_waterfall.svg", "type": "ranked_waterfall", "primary": True},
        {
            "id": "histogram_kde",
            "path": "figure_histogram_kde.svg",
            "type": "density_histogram_with_kde",
            "primary": False,
        },
    ]
    # Interactive plotly twins from the SAME reconstructed frame (static + interactive can't drift).
    # We RETURN their descriptors (dynamic: True) too — mirroring the skills _plotly_from wrapping — so
    # this is an EXACT drop-in for the Stage-3 registry repoint (the emitter delegates fully here and
    # the interactive dashboard keeps its plotly specs). Best-effort: absence/failure just contributes
    # no dynamic descriptors; the SVGs remain the guaranteed contract.
    dynamic: list[dict] = []
    try:
        specs = _cli.emit_plotly_specs(chronos_by_model, model_metadata, target, summary, out_dir, tcd) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; SVGs are the contract
        pass
    return static + dynamic
