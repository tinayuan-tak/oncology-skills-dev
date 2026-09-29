"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 6, DGE arm).

The DGE 3-group figure (tumor / TCGA-adjacent / GTEx per-sample box+strip + the sensitivity forest)
draws from per_sample_data fetched LIVE from recount3 at figure time. emit.emit_plot_data persists
that per_sample_data as a long parquet (plot_data_dge_per_sample.parquet); this seam reconstructs the
per_sample_data dict and replays it into the already-vector-driven
emit.emit_tumor_vs_normal_selectivity_4panel / emit.emit_plotly_specs — NO recount3 re-stream.

Two thin entry points render the SAME SVG under the two consuming cards' distinct descriptor ids:
  - render_selectivity_from_plot_data  → tumor-vs-normal-selectivity card (id tumor_vs_normal_selectivity_4panel)
  - render_adjacent_from_plot_data     → tumor-rna-vs-adjacent card       (id tumor_vs_normal_3group)
The forest contrasts + the right-hand callout come from the passed `summary` (the resolved card
verdict), exactly as the live dispatcher passed them — so the offline figure cannot diverge.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

from methods.roots import contracts_root

from . import emit as _emit

# Portable sibling default; `or` so an empty env value falls back too (Path("") is the CWD).
_DEFAULT_TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT") or str(contracts_root())

_REQUIRED_COLUMNS = ("group",)
_SAMPLE_FIELDS = _emit._PLOT_DATA_SAMPLE_FIELDS
_GROUP_TO_KEY = {"tumor": "tumor_samples", "adjacent": "adjacent_samples", "gtex": "gtex_samples"}

# Mirror of _skills_common/_figure_emitters/_common._DGE_SENSITIVITY_CELLS — the sensitivity cells
# the SVG forest draws, read straight off the summary (no recompute). Kept in step with that helper.
# Cell B (ComBat re-run of A) was REMOVED here in analysis-methods#727; the skills-side mirror in
# _skills_common still lists cell B and must be updated to match in a follow-up cross-repo PR (this
# PR is analysis-methods-only). A cell absent from the summary is skipped by _cell_contrasts anyway,
# so a lingering B entry there is harmless (never drawn) until that mirror lands. Cell D is retired
# but kept declared for forward-compat (skipped when absent).
_DGE_SENSITIVITY_CELLS = [
    ("tumor vs TCGA adj (raw)", "log2fc_cell_a", "q_value_cell_a"),
    ("tumor vs GTEx (raw joint)", "log2fc_cell_c", "q_value_cell_c"),
    ("tumor vs GTEx (ComBat)", "log2fc_cell_d", "q_value_cell_d"),
]


def _cell_contrasts(summary: dict) -> list[dict]:
    rows = []
    for label, lfc_k, q_k in _DGE_SENSITIVITY_CELLS:
        lfc = (summary or {}).get(lfc_k)
        if lfc is None or lfc != lfc:  # skip absent / NaN cells (matches the SVG forest)
            continue
        rows.append({"label": label, "log2_fc": float(lfc), "q_value": summary.get(q_k)})
    return rows


def _reconstruct_per_sample(plot_data: "Union[str, Path, object]") -> Optional[dict]:
    """Rebuild the per_sample_data dict (read_per_sample_expression_all_three_groups shape) from the
    persisted long parquet. NO recount3 re-stream. Returns None when there are no rows."""
    import math

    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")
    if df.empty:
        return None

    def _clean(v):
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    out: dict = {k: [] for k in _GROUP_TO_KEY.values()}
    for _, r in df.iterrows():
        key = _GROUP_TO_KEY.get(str(r["group"]))
        if key is None:
            continue
        out[key].append({f: _clean(r[f]) for f in _SAMPLE_FIELDS if f in df.columns})
    for k, cnt_key in (("tumor_samples", "n_tumor"), ("adjacent_samples", "n_adjacent"), ("gtex_samples", "n_gtex")):
        out[cnt_key] = len(out[k])
    gtex_tissue = _clean(df["gtex_tissue"].iloc[0]) if "gtex_tissue" in df.columns else None
    out["gtex_tissue"] = gtex_tissue
    out["gene_ensembl_id"] = _clean(df["gene_ensembl_id"].iloc[0]) if "gene_ensembl_id" in df.columns else None
    return out


def _render_4panel(plot_data, summary, out_dir, target, indication, figure_id, target_contracts_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else Path(_DEFAULT_TARGET_CONTRACTS)

    per_sample = _reconstruct_per_sample(plot_data)
    if per_sample is None:
        return []

    _emit.emit_tumor_vs_normal_selectivity_4panel(
        sensitivity_summary=summary or {},
        per_sample_data=per_sample,
        target=target,
        indication=indication,
        out_dir=out_dir,
        target_contracts_dir=tcd,
    )
    static = [
        {
            "id": figure_id,
            "path": "figure_tumor_vs_normal_selectivity_4panel.svg",
            "type": "box_forest_sensitivity_panel",
            "primary": True,
        },
    ]
    dynamic: list[dict] = []
    try:
        specs = (
            _emit.emit_plotly_specs(
                per_sample, _cell_contrasts(summary), target, indication, out_dir, tcd, "tumor_vs_normal"
            )
            or []
        )
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; the SVG is the contract
        pass
    return static + dynamic


def render_selectivity_from_plot_data(
    plot_data: "Union[str, Path, object]",
    summary: dict,
    out_dir: "Union[str, Path]",
    target: str,
    indication: "Optional[str]" = None,
    *,
    target_contracts_dir: "Optional[Union[str, Path]]" = None,
) -> list[dict]:
    """Render the tumor-vs-normal-selectivity 4-panel OFFLINE from persisted plot_data. NO live read."""
    return _render_4panel(
        plot_data, summary, out_dir, target, indication, "tumor_vs_normal_selectivity_4panel", target_contracts_dir
    )


def render_adjacent_from_plot_data(
    plot_data: "Union[str, Path, object]",
    summary: dict,
    out_dir: "Union[str, Path]",
    target: str,
    indication: "Optional[str]" = None,
    *,
    target_contracts_dir: "Optional[Union[str, Path]]" = None,
) -> list[dict]:
    """Render the tumor-rna-vs-adjacent 3-group panel OFFLINE from persisted plot_data (same SVG as
    the selectivity card, distinct descriptor id). NO live read."""
    return _render_4panel(
        plot_data, summary, out_dir, target, indication, "tumor_vs_normal_3group", target_contracts_dir
    )
