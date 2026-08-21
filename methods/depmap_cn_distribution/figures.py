"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 2, copy-number arm).

Parallel to the expression/chronos/rnai arms: reconstruct cn_by_model / model_metadata from the
persisted plot_data_cn.parquet (Stage 1) and delegate to the SAME cli.emit_* draw functions a live
run uses — so the copy-number-distribution figures render OFFLINE, deterministically, byte-identical
to a live run, with NO second S3/cbg read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

_REQUIRED_COLUMNS = ("model_id", "relative_cn")


def _reconstruct_frame(plot_data: "Union[str, Path, object]") -> tuple[dict, dict]:
    """Rebuild (cn_by_model, model_metadata) from a plot_data DataFrame or parquet path — the inverse
    of cli.emit_plot_data. NO S3 access."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")

    cn_by_model: dict = {}
    model_metadata: dict = {}
    for row in df.itertuples(index=False):
        mid = row.model_id
        cn_by_model[mid] = float(row.relative_cn)
        model_metadata[mid] = {
            "ModelID": mid,
            "CCLEName": getattr(row, "ccle_name", None),
            "OncotreeLineage": getattr(row, "lineage", None),
        }
    return cn_by_model, model_metadata


def render_from_plot_data(plot_data: "Union[str, Path, object]", summary: dict, out_dir: "Union[str, Path]",
                          target: str, indication: Optional[str] = None, *,
                          target_contracts_dir: "Optional[Union[str, Path]]" = None) -> list[dict]:
    """Render the copy-number-distribution figures OFFLINE from persisted plot_data + summary. NO live
    read — delegates to the same cli.emit_* draw functions a live run uses."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    cn_by_model, model_metadata = _reconstruct_frame(plot_data)

    _cli.emit_density_plot(cn_by_model, target, summary, out_dir, tcd)
    _cli.emit_waterfall_plot(cn_by_model, model_metadata, target, summary, out_dir, tcd)
    _cli.emit_lineage_strip(cn_by_model, model_metadata, target, summary, out_dir, tcd)

    # Descriptor shape mirrors the current registry emitter (_emit_cn_distribution) with types
    # canonicalized to the FIGURE_CATALOG closed enum (Stage 5).
    static = [
        {"id": "density_cn", "path": "figure_density_cn.svg",
         "type": "density_histogram_with_kde", "primary": True},
        {"id": "lineage_strip_cn", "path": "figure_lineage_strip_cn.svg",
         "type": "per_lineage_strip_plot", "primary": False},
        {"id": "waterfall_cn", "path": "figure_waterfall_cn.svg",
         "type": "ranked_waterfall", "primary": False},
    ]
    # Interactive plotly twins from the SAME reconstructed frame — RETURNED (dynamic: True) so this is
    # an EXACT drop-in for the Stage-3 registry repoint (mirrors the skills _plotly_from wrapping).
    # The copy-number plotly twin landed with this migration (was the FIGURE_CATALOG parity gap).
    # Best-effort: absence/failure contributes no dynamic descriptors; the SVGs are the contract.
    dynamic: list[dict] = []
    try:
        specs = _cli.emit_plotly_specs(cn_by_model, model_metadata, target, summary,
                                       out_dir, tcd) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; SVGs are the contract
        pass
    return static + dynamic
