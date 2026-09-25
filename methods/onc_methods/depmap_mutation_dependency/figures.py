"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, card3 arm).

Reconstruct chronos_by_model / hotspot_by_model / damaging_by_model / model_metadata from the
persisted plot_data.parquet (Stage 1, read_mutation_stratified_dependency(plot_data_out=...)),
recompute the (pure) mutation stratification, and delegate to the SAME cli.emit_* draw functions a
live run uses — so the mutation-stratified-dependency figures (mut-vs-WT strip + per-hotspot strip +
interactive twin) render OFFLINE, with NO second DepMap Chronos+mutation load at figure time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

_REQUIRED_COLUMNS = ("cell_line_id", "chronos_score", "is_hotspot_mutant", "is_damaging_mutant")


def _reconstruct(plot_data: "Union[str, Path, object]") -> tuple[dict, dict, dict, dict]:
    """Rebuild (chronos_by_model, hotspot_by_model, damaging_by_model, model_metadata) — the inverse
    of cli.emit_plot_data. NO S3 access."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")

    chronos, hotspot, damaging, meta = {}, {}, {}, {}
    for row in df.itertuples(index=False):
        mid = row.cell_line_id
        chronos[mid] = float(row.chronos_score)
        hotspot[mid] = bool(row.is_hotspot_mutant)
        damaging[mid] = bool(row.is_damaging_mutant)
        meta[mid] = {
            "ModelID": mid,
            "CellLineName": getattr(row, "cell_line_name", None),
            "OncotreeLineage": getattr(row, "lineage", None),
        }
    return chronos, hotspot, damaging, meta


def render_from_plot_data(
    plot_data: "Union[str, Path, object]",
    summary: dict,
    out_dir: "Union[str, Path]",
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir: "Optional[Union[str, Path]]" = None,
) -> list[dict]:
    """Render the mutation-stratified-dependency figures OFFLINE from persisted plot_data. NO live
    read — reconstructs the frame, recomputes the (pure) stratification, and delegates to the same
    cli.emit_* draw functions a live run uses."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    chronos_by_model, hotspot_by_model, damaging_by_model, model_metadata = _reconstruct(plot_data)
    recomputed = _cli.compute_mutation_stratification(chronos_by_model, hotspot_by_model, damaging_by_model)

    _cli.emit_mut_vs_wt_strip_plot(
        chronos_by_model, hotspot_by_model, damaging_by_model, target, recomputed, out_dir, tcd,
        model_metadata=model_metadata, indication=indication
    )
    _cli.emit_per_hotspot_chronos_plot(chronos_by_model, recomputed.get("per_hotspot_stats", []), target, out_dir, tcd)

    static = [
        {
            "id": "mut_vs_wt_strip",
            "path": "figure_mut_vs_wt_strip.svg",
            "type": "mutation_stratified_strip",
            "primary": True,
        },
        {
            "id": "per_hotspot_chronos",
            "path": "figure_per_hotspot_chronos.svg",
            "type": "per_hotspot_chronos_strip",
            "primary": False,
        },
    ]
    dynamic: list[dict] = []
    try:
        specs = (
            _cli.emit_plotly_specs(
                chronos_by_model, hotspot_by_model, damaging_by_model, target, recomputed, out_dir, tcd
            )
            or []
        )
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; SVGs are the contract
        pass
    return static + dynamic
