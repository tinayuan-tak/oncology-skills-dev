"""Offline figure rendering from persisted plot_data (figure-consolidation Stage 2, protein arm).

Fifth distribution-family member. Reconstruct abundance_by_model / lineage_by_model from the persisted
plot_data_protein_abundance.parquet (Stage 1) and delegate to the SAME cli.emit_* draw functions a
live run uses — so the cellline-protein-abundance figures render OFFLINE, deterministically,
byte-identical to a live run, with NO second S3/cbg read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

_REQUIRED_COLUMNS = ("model_id", "log2_abundance")


def _reconstruct_frame(plot_data: "Union[str, Path, object]") -> tuple[dict, dict]:
    """Rebuild (abundance_by_model, lineage_by_model) from a plot_data DataFrame or parquet path —
    the inverse of cli.emit_plot_data_protein. NO S3 access."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")

    abundance_by_model: dict = {}
    lineage_by_model: dict = {}
    for row in df.itertuples(index=False):
        mid = row.model_id
        abundance_by_model[mid] = float(row.log2_abundance)
        lineage_by_model[mid] = getattr(row, "lineage", None)
    return abundance_by_model, lineage_by_model


def render_from_plot_data(
    plot_data: "Union[str, Path, object]",
    summary: dict,
    out_dir: "Union[str, Path]",
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir: "Optional[Union[str, Path]]" = None,
) -> list[dict]:
    """Render the cellline-protein-abundance figures OFFLINE from persisted plot_data + summary. NO
    live read — delegates to the same cli.emit_* draw functions a live run uses."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    abundance_by_model, lineage_by_model = _reconstruct_frame(plot_data)

    _cli.emit_density_protein(abundance_by_model, target, summary, out_dir, tcd)
    _cli.emit_lineage_strip_protein(abundance_by_model, lineage_by_model, target, summary, out_dir, tcd)

    # Descriptor shape mirrors the current registry emitter (_emit_protein_abundance_celline). Type
    # canonicalization to the FIGURE_CATALOG closed enum is a Stage-5 concern.
    static = [
        {
            "id": "density_protein_abundance",
            "path": "figure_density_protein_abundance.svg",
            "type": "density_histogram_with_kde",
            "primary": True,
        },
        {
            "id": "lineage_strip_protein",
            "path": "figure_lineage_strip_protein.svg",
            "type": "per_lineage_strip_plot",
            "primary": False,
        },
    ]
    # Interactive plotly twins from the SAME reconstructed frame — RETURNED (dynamic: True) so this is
    # an EXACT drop-in for the Stage-3 registry repoint (mirrors the skills _plotly_from wrapping).
    # Best-effort: absence/failure contributes no dynamic descriptors; the SVGs are the contract.
    dynamic: list[dict] = []
    try:
        specs = _cli.emit_plotly_specs(abundance_by_model, lineage_by_model, target, summary, out_dir, tcd) or []
        dynamic = [{**s, "dynamic": True} for s in specs]
    except Exception:  # noqa: BLE001 — additive interactive twin; SVGs are the contract
        pass
    return static + dynamic
