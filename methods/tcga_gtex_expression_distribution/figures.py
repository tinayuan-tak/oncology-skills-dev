"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, tumor-RNA arm).

The expression/selectivity emitters differ from the DepMap family: their draw functions RE-READ
tumor/normal samples inside the draw. Stage 6 makes the draws vector-driven (cli.emit_svg /
emit_plotly_specs gained an opt-in `presampled=(tumor, normal, tissue)`), and this seam replays the
per-sample vectors persisted by cli.emit_plot_data (plot_data_expression_distribution.parquet) into
them — so the tumor-rna-distribution figure renders OFFLINE, with NO second recount3/S3 read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

_REQUIRED_COLUMNS = ("group", "log2_tpm")


def _reconstruct_vectors(plot_data: "Union[str, Path, object]") -> tuple[list, list, str]:
    """Rebuild (tumor, normal, tissue) from the persisted long frame (cli.emit_plot_data). NO S3."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")
    tumor = [float(v) for v in df.loc[df["group"] == "tumor", "log2_tpm"]]
    normal_df = df[df["group"] == "normal"]
    normal = [float(v) for v in normal_df["log2_tpm"]]
    tissue = ""
    if "source" in df.columns and not normal_df.empty:
        src = str(normal_df["source"].iloc[0])
        tissue = src.split("GTEx:", 1)[1] if "GTEx:" in src else src
    return tumor, normal, tissue


def render_from_plot_data(plot_data: "Union[str, Path, object]", summary: dict, out_dir: "Union[str, Path]",
                          target: str, indication: Optional[str] = None, *,
                          target_contracts_dir: "Optional[Union[str, Path]]" = None) -> list[dict]:
    """Render the tumor-rna-distribution per-sample figure OFFLINE from persisted plot_data. NO live
    read — replays the persisted tumor/normal vectors into the vector-driven cli.emit_svg /
    emit_plotly_specs (p95 reference line etc. come from the passed `summary`)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    tumor, normal, tissue = _reconstruct_vectors(plot_data)
    _cli.emit_svg(target, indication, summary, out_dir, tcd, presampled=(tumor, normal, tissue))

    static = [
        {"id": "expression_distribution_per_sample", "path": "figure_expression_distribution.svg",
         "type": "per_sample_tumor_normal_distribution", "primary": True},
    ]
    dynamic: list[dict] = []
    try:
        specs = _cli.emit_plotly_specs(target, indication, out_dir, tcd,
                                       presampled=(tumor, normal, tissue)) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; the SVG is the contract
        pass
    return static + dynamic
