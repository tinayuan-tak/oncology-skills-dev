"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 2).

`render_from_plot_data` reconstructs the in-memory frame the drawing functions expect
(tpm_by_model / model_metadata) from the `plot_data_expression.parquet` that card RESOLUTION now
persists (Stage 1, #415), then delegates to the SAME `cli.emit_*` drawing functions a live run uses.

Result: the figures render OFFLINE — deterministic, unit-testable, and byte-identical to a live run —
with NO second S3/`cbg` read, and they cannot diverge from the verdict (same data object). This is the
seam the monolith's per-card emitters migrate onto (Stage 3): repoint the registry entry here instead
of re-executing the method.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

# The persisted plot_data long-frame columns (see cli.emit_plot_data): the serialized form of the
# tpm_by_model / model_metadata dicts the draw functions consume.
_REQUIRED_COLUMNS = ("model_id", "log2tpm")


def _reconstruct_frame(plot_data: "Union[str, Path, object]") -> tuple[dict, dict]:
    """Rebuild (tpm_by_model, model_metadata) from a plot_data DataFrame or a parquet path.

    This is the inverse of cli.emit_plot_data — it deserializes the persisted long frame back into
    the two dicts load_expression_files produced in memory, so the existing draw functions run
    unchanged. NO S3 access."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")

    tpm_by_model: dict = {}
    model_metadata: dict = {}
    for row in df.itertuples(index=False):
        mid = row.model_id
        tpm_by_model[mid] = float(row.log2tpm)
        model_metadata[mid] = {
            "ModelID": mid,
            "OncotreeLineage": getattr(row, "lineage", None),
            "CCLEName": getattr(row, "ccle_name", None),
        }
    return tpm_by_model, model_metadata


def render_from_plot_data(plot_data: "Union[str, Path, object]", summary: dict, out_dir: "Union[str, Path]",
                          target: str, indication: Optional[str] = None, *,
                          target_contracts_dir: "Optional[Union[str, Path]]" = None) -> list[dict]:
    """Render the cellline-rna-distribution figures OFFLINE from persisted plot_data + summary.

    plot_data: a DataFrame OR a path to plot_data_expression.parquet.
    summary:   the card summary dict (scalars: medians, thresholds, class) — carries reference lines.
    Returns the figure-descriptor list (id/path/type/primary) mirroring the registry emitter. NO live
    read — delegates to the same cli.emit_* draw functions a live run uses, so the SVGs are identical."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    tpm_by_model, model_metadata = _reconstruct_frame(plot_data)

    _cli.emit_density_plot(tpm_by_model, target, summary, out_dir, tcd)
    _cli.emit_lineage_strip(tpm_by_model, model_metadata, target, summary, out_dir, tcd)

    static = [
        {"id": "density_expression", "path": "figure_density_expression.svg",
         "type": "density_histogram_with_kde", "primary": True},
        {"id": "lineage_strip_expression", "path": "figure_lineage_strip_expression.svg",
         "type": "per_lineage_strip_plot", "primary": False},
    ]
    # Interactive plotly twins from the SAME reconstructed frame (static + interactive can't drift).
    # We RETURN their descriptors (dynamic: True) too — mirroring the skills _plotly_from wrapping — so
    # this is an EXACT drop-in for the Stage-3 registry repoint (the emitter delegates fully here, and
    # the interactive dashboard keeps its plotly specs). Best-effort: a plotly failure/absence just
    # contributes no dynamic descriptors; the SVGs remain the guaranteed contract.
    dynamic: list[dict] = []
    try:
        specs = _cli.emit_plotly_specs(tpm_by_model, model_metadata, target, summary, out_dir, tcd,
                                       indication) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; SVGs are the contract
        pass

    # Descriptor types are canonicalized to the FIGURE_CATALOG closed enum — density_histogram_with_kde
    # / ranked_waterfall / per_lineage_strip_plot — matching the card contract (Stage 5).
    return static + dynamic
