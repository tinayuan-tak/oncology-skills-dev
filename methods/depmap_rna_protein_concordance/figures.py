"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, rna-protein arms).

Vector-driven: cli.emit_svg / emit_tumor_svg (+ plotly twins) gained an opt-in `presampled=points`.
This seam replays the per-model / per-tumor paired points persisted by the resolve readers into them —
so the cellline + tumor RNA↔protein scatters render OFFLINE, with NO second DepMap/CPTAC read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

_REQUIRED_COLUMNS = ("rna", "protein")


def _points_from(plot_data: "Union[str, Path, object]") -> list:
    import pandas as pd
    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")
    return [{"rna": float(r.rna), "protein": float(r.protein)} for r in df.itertuples(index=False)]


def render_from_plot_data(plot_data, summary: dict, out_dir, target: str,
                          indication: "Optional[str]" = None, *, target_contracts_dir=None) -> list:
    """Cell-line RNA↔protein scatter, OFFLINE from persisted per-model points."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    tcd = target_contracts_dir or _cli.DEFAULT_TARGET_CONTRACTS
    pts = _points_from(plot_data)
    svg = _cli.emit_svg(target, indication, summary, out_dir, tcd, presampled=pts)
    if svg is None:
        return []
    static = [{"id": "rna_protein_concordance_scatter", "path": "figure_rna_protein_concordance.svg",
               "type": "rna_protein_concordance_scatter", "primary": True}]
    dynamic = []
    try:
        specs = _cli.emit_plotly_specs(target, indication, out_dir, tcd, presampled=pts, summary=summary) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001
        pass
    return static + dynamic


def render_tumor_from_plot_data(plot_data, summary: dict, out_dir, target: str,
                                indication: "Optional[str]" = None, *, target_contracts_dir=None) -> list:
    """Tumor (CPTAC) RNA↔protein scatter, OFFLINE from persisted per-tumor points."""
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    tcd = target_contracts_dir or _cli.DEFAULT_TARGET_CONTRACTS
    pts = _points_from(plot_data)
    svg = _cli.emit_tumor_svg(target, indication, out_dir, tcd, presampled=pts, summary=summary)
    if svg is None:
        return []
    static = [{"id": "rna_protein_concordance_tumor_scatter",
               "path": "figure_rna_protein_concordance_tumor.svg",
               "type": "rna_protein_concordance_tumor_scatter", "primary": True}]
    dynamic = []
    try:
        specs = _cli.emit_tumor_plotly_specs(target, indication, out_dir, tcd,
                                             presampled=pts, summary=summary) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001
        pass
    return static + dynamic
