"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, recommended-models).

Vector-driven: cli.emit_svg gained an opt-in `presampled=models` (the full per-model rows) and
emit_plotly_specs an opt-in `summary=`. This seam replays the persisted models into them — so the
patient<->model correspondence scatter renders OFFLINE, with NO second DepMap load at figure time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from . import cli as _cli

_REQUIRED_COLUMNS = ("target_log2tpm", "chronos")


def render_from_plot_data(plot_data, summary: dict, out_dir, target: str,
                          indication: "Optional[str]" = None, *, target_contracts_dir=None) -> list:
    import pandas as pd

    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    tcd = target_contracts_dir or _cli.DEFAULT_TARGET_CONTRACTS
    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")
    # restore None from parquet NaN so emit_svg's `chronos is None` skip holds (models without a screen)
    models = df.astype(object).where(pd.notnull(df), None).to_dict("records")

    svg = _cli.emit_svg(target, indication, summary, out_dir, tcd, presampled=models)
    if svg is None:
        return []
    static = [{"id": "recommended_models_scatter", "path": "figure_recommended_models.svg",
               "type": "patient_model_correspondence_scatter", "primary": True}]
    dynamic = []
    try:
        specs = _cli.emit_plotly_specs(target, indication, out_dir, tcd, summary=summary) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001
        pass
    return static + dynamic
