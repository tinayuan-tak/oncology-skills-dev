"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, CPTAC arm).

The CPTAC per-cohort tumor-vs-normal protein boxplot draws each box from the RAW per-aliquot
log-ratio arrays (not five-number summaries). read.emit_plot_data now persists those arrays as the
`tumor_values`/`normal_values` list-columns of plot_data_protein_per_cohort.parquet, so this seam
reconstructs the per-cohort stats list (including the `_tumor_values`/`_normal_values` the draw
expects) and replays it into the presampled-aware read.emit_per_cohort_panel / emit_plotly_specs —
the figure renders OFFLINE with NO re-read of the per-sample product.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import read as _read

# stat columns persisted alongside the raw-array list-columns (one row per cohort)
_STAT_COLUMNS = ("cohort", "n_tumor", "n_normal", "tumor_min", "tumor_q1", "tumor_median",
                 "tumor_q3", "tumor_max", "normal_min", "normal_q1", "normal_median",
                 "normal_q3", "normal_max", "delta_median", "welch_p", "mwu_p")
_REQUIRED_COLUMNS = ("cohort", "delta_median", "tumor_values", "normal_values")


def _reconstruct_stats(plot_data: "Union[str, Path, object]") -> list[dict]:
    """Rebuild the per-cohort stats list (per_cohort_distribution_stats shape, incl. the raw
    `_tumor_values`/`_normal_values` arrays) from the persisted parquet. NO per-sample re-read."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")
    stats = []
    for _, r in df.iterrows():
        s = {c: (r[c] if c in df.columns else None) for c in _STAT_COLUMNS}
        # list-columns come back as numpy arrays / lists — coerce to plain python float lists
        # (numpy-array truthiness is ambiguous; the draw uses `if s["_tumor_values"]:`).
        s["_tumor_values"] = [float(v) for v in (r["tumor_values"] if r["tumor_values"] is not None else [])]
        s["_normal_values"] = [float(v) for v in (r["normal_values"] if r["normal_values"] is not None else [])]
        stats.append(s)
    # emit_plot_data persists in the sorted (delta_median desc) order the emitters expect; keep it.
    return stats


def render_from_plot_data(plot_data: "Union[str, Path, object]", summary: dict,
                          out_dir: "Union[str, Path]", target: str,
                          indication: "Optional[str]" = None, *,
                          target_contracts_dir: "Optional[Union[str, Path]]" = None) -> list[dict]:
    """Render the CPTAC per-cohort tumor-vs-normal boxplot OFFLINE from persisted plot_data
    (plot_data_protein_per_cohort.parquet). Reconstructs the per-cohort stats (with raw arrays) and
    replays them into the presampled-aware read.emit_per_cohort_panel / emit_plotly_specs. NO live
    read."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = str(target_contracts_dir) if target_contracts_dir else None
    kw = {"target_contracts_dir": tcd} if tcd else {}

    stats = _reconstruct_stats(plot_data)
    if not stats:
        return []                                    # target absent from every CPTAC cohort

    _read.emit_per_cohort_panel(target, out_dir, presampled=stats, **kw)
    static = [
        {"id": "protein_per_cohort_tumor_vs_normal",
         "path": "figure_protein_per_cohort_tumor_vs_normal.svg",
         "type": "per_cohort_distribution_tumor_vs_normal", "primary": True},
    ]
    dynamic: list[dict] = []
    try:
        specs = _read.emit_plotly_specs(target, out_dir, presampled=stats, **kw) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; the SVG is the contract
        pass
    return static + dynamic
