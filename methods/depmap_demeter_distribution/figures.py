"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 2, RNAi arm).

Parallel to the chronos/expression arms: reconstruct demeter_by_model / model_metadata from the
persisted plot_data.parquet (Stage 1) and delegate to the SAME cli.emit_* draw functions a live run
uses — so the pan-cancer-rnai-dependency-distribution figures render OFFLINE, deterministically,
byte-identical to a live run, with NO second S3/cbg read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

_REQUIRED_COLUMNS = ("model_id", "demeter2_score")


def _reconstruct_frame(plot_data: "Union[str, Path, object]") -> tuple[dict, dict]:
    """Rebuild (demeter_by_model, model_metadata) from a plot_data DataFrame or parquet path — the
    inverse of cli.emit_plot_data. NO S3 access."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")

    demeter_by_model: dict = {}
    model_metadata: dict = {}
    for row in df.itertuples(index=False):
        mid = row.model_id
        demeter_by_model[mid] = float(row.demeter2_score)
        model_metadata[mid] = {
            "ModelID": mid,
            "CCLEName": getattr(row, "ccle_name", None),
            "OncotreeLineage": getattr(row, "lineage", None),
        }
    return demeter_by_model, model_metadata


def render_from_plot_data(plot_data: "Union[str, Path, object]", summary: dict, out_dir: "Union[str, Path]",
                          target: str, indication: Optional[str] = None, *,
                          target_contracts_dir: "Optional[Union[str, Path]]" = None) -> list[dict]:
    """Render the pan-cancer-rnai-dependency-distribution figures OFFLINE from persisted plot_data +
    summary. NO live read — delegates to the same cli.emit_* draw functions a live run uses."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    demeter_by_model, model_metadata = _reconstruct_frame(plot_data)

    _cli.emit_waterfall_plot(demeter_by_model, model_metadata, target, summary, out_dir, tcd)
    _cli.emit_histogram_kde_plot(demeter_by_model, target, summary, out_dir, tcd)
    try:
        _cli.emit_plotly_specs(demeter_by_model, model_metadata, target, summary, out_dir, tcd)
    except Exception:  # noqa: BLE001 — additive interactive twin; SVGs are the contract
        pass

    # Descriptor shape mirrors the current registry emitter (_emit_card1b_pan_cancer_rnai_dependency_
    # distribution). Type canonicalization to the FIGURE_CATALOG closed enum is a Stage-5 concern.
    return [
        {"id": "waterfall_rnai", "path": "figure_waterfall_rnai.svg",
         "type": "ranked_waterfall_rnai", "primary": True},
        {"id": "histogram_kde_rnai", "path": "figure_histogram_kde_rnai.svg",
         "type": "density_histogram_with_kde_rnai", "primary": False},
    ]
