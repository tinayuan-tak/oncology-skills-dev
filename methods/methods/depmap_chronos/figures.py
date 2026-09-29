"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, card2 arm).

Parallel to the distribution-family figures.py: reconstruct chronos_by_model / model_metadata from
the persisted plot_data.parquet (Stage 1, read_lineage_selectivity(plot_data_out=...)) and delegate
to the SAME cli.emit_* draw functions a live run uses — so the dependency-lineage-selectivity figures
(forest_plot + lineage_strip + interactive twin) render OFFLINE, deterministically, byte-identical to
a live run, with NO second DepMap/S3 read.

target_lineage is re-derived from `indication` (cli.INDICATION_LINEAGE) at render time — the read is
indication-decoupled (Card 2 v3), but the FIGURE highlights the indication's lineage.
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
    """Render the dependency-lineage-selectivity figures OFFLINE from persisted plot_data. NO live
    read — reconstructs the frame, recomputes the lineage summary, and delegates to the same cli.emit_*
    draw functions a live run uses."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    chronos_by_model, model_metadata = _reconstruct_frame(plot_data)
    target_lineage = _cli.INDICATION_LINEAGE.get(indication, "") if indication else ""

    lineage_summary = _cli.compute_lineage_summary(
        chronos_by_model,
        model_metadata,
        indication=indication,
    )
    merged_data = _cli.emit_plot_data(
        chronos_by_model,
        model_metadata,
        target_lineage,
        -1.0,
        out_dir,
    )
    _cli.emit_forest_plot(
        lineage_summary.get("_per_lineage_records", []),
        target_lineage,
        target,
        indication,
        lineage_summary,
        out_dir,
        tcd,
    )
    _cli.emit_lineage_strip(
        merged_data,
        target_lineage,
        target,
        indication,
        out_dir,
        tcd,
    )

    static = [
        {"id": "forest_plot", "path": "figure_forest_plot.svg", "type": "lineage_forest_plot", "primary": True},
        {"id": "lineage_strip", "path": "figure_lineage_strip.svg", "type": "lineage_strip_plot", "primary": False},
    ]
    # Interactive plotly twin from the SAME reconstructed records — RETURNED (dynamic: True) so this is
    # an EXACT drop-in for the registry emitter (which appends _plotly_from today). Best-effort.
    dynamic: list[dict] = []
    try:
        specs = (
            _cli.emit_plotly_specs(
                lineage_summary.get("_per_lineage_records", []),
                target_lineage,
                target,
                indication,
                lineage_summary,
                out_dir,
                tcd,
            )
            or []
        )
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; SVGs are the contract
        pass
    return static + dynamic
