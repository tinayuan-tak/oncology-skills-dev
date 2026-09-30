"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, breadth arm).

The tumor-elevation-breadth RNA companion figure (pan-cancer by-tissue tumor-vs-normal boxplot) is
drawn from PRECOMPUTED five-number summaries — the quantile product rows, not per-sample values —
so read.emit_plot_data already persists exactly the columns the plot needs
(plot_data_pan_cancer_by_tissue.parquet: gene_symbol, ensembl_gene_id, source, group, n, min, q1,
median, q3, max, mean). This seam replays that persisted frame into the (now presampled-aware)
read.emit_by_tissue_distribution / emit_plotly_specs so the figure renders OFFLINE with NO second
read of the 69 MB quantile product / S3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import read as _read

_REQUIRED_COLUMNS = ("source", "group", "median")


def render_from_plot_data(
    plot_data: "Union[str, Path, object]",
    summary: dict,
    out_dir: "Union[str, Path]",
    target: str,
    indication: "Optional[str]" = None,
    *,
    target_contracts_dir: "Optional[Union[str, Path]]" = None,
) -> list[dict]:
    """Render the pan-cancer by-tissue distribution OFFLINE from persisted plot_data
    (plot_data_pan_cancer_by_tissue.parquet). Replays the persisted quantile rows into the
    presampled-aware read.emit_by_tissue_distribution / emit_plotly_specs. NO live read."""
    import pandas as pd

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = str(target_contracts_dir) if target_contracts_dir else None

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")
    if df.empty:
        return []  # target absent from the quantile product

    kw = {"target_contracts_dir": tcd} if tcd else {}
    _read.emit_by_tissue_distribution(target, out_dir, presampled=df, **kw)
    static = [
        {
            "id": "pan_cancer_by_tissue_distribution",
            "path": "figure_pan_cancer_by_tissue_distribution.svg",
            "type": "pan_cancer_by_tissue_tumor_vs_normal_distribution",
            "primary": True,
        },
    ]
    dynamic: list[dict] = []
    try:
        specs = _read.emit_plotly_specs(target, out_dir, presampled=df, **kw) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; the SVG is the contract
        pass
    return static + dynamic
