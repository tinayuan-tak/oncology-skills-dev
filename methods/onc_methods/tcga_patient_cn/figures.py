"""Offline figure rendering from persisted plot_data (tcga_patient_cn).

Reconstruct CN frequency data from the persisted plot_data_cn.parquet and
delegate to the SAME cli.emit_* draw functions a live run uses — so the
copy-number figures render OFFLINE, with NO second TCGA data load at figure time.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

_REQUIRED_COLUMNS = ("gene_symbol", "frequency", "cn_type", "row_type")


def _reconstruct(plot_data: "Union[str, Path, object]") -> dict:
    """Rebuild figure data from plot_data_cn.parquet.

    Returns dict with:
        target: str
        indication: str
        amp_freq: float (target amplification frequency)
        del_freq: float (target deletion frequency)
        amp_genes: list[(gene, freq)] for amplification context (indication)
        del_genes: list[(gene, freq)] for deletion context (indication)
        amp_genes_pancancer: list[(gene, freq)] for amplification context (pan-cancer)
        del_genes_pancancer: list[(gene, freq)] for deletion context (pan-cancer)
    """
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")

    result = {
        "target": df["target"].iloc[0] if "target" in df.columns else None,
        "indication": df["indication"].iloc[0] if "indication" in df.columns else None,
    }

    # Extract target summary
    target_rows = df[df["row_type"] == "target_summary"]
    amp_target = target_rows[target_rows["cn_type"] == "amplification"]
    del_target = target_rows[target_rows["cn_type"] == "deletion"]

    result["amp_freq"] = float(amp_target["frequency"].iloc[0]) if len(amp_target) > 0 else None
    result["del_freq"] = float(del_target["frequency"].iloc[0]) if len(del_target) > 0 else None

    # Extract indication-specific context
    context_rows = df[df["row_type"] == "all_genes_context"]

    amp_context = context_rows[context_rows["cn_type"] == "amplification"]
    result["amp_genes"] = [(row["gene_symbol"], row["frequency"])
                           for _, row in amp_context.iterrows()]

    del_context = context_rows[context_rows["cn_type"] == "deletion"]
    result["del_genes"] = [(row["gene_symbol"], row["frequency"])
                           for _, row in del_context.iterrows()]

    # Extract pan-cancer context (if available)
    pancancer_rows = df[df["row_type"] == "all_genes_context_pancancer"]
    if len(pancancer_rows) > 0:
        amp_pan = pancancer_rows[pancancer_rows["cn_type"] == "amplification"]
        result["amp_genes_pancancer"] = [(row["gene_symbol"], row["frequency"])
                                          for _, row in amp_pan.iterrows()]

        del_pan = pancancer_rows[pancancer_rows["cn_type"] == "deletion"]
        result["del_genes_pancancer"] = [(row["gene_symbol"], row["frequency"])
                                          for _, row in del_pan.iterrows()]
    else:
        # Fallback to indication data if no pan-cancer rows
        result["amp_genes_pancancer"] = result["amp_genes"]
        result["del_genes_pancancer"] = result["del_genes"]

    return result


def render_from_plot_data(
    plot_data: "Union[str, Path, object]",
    summary: dict,
    out_dir: "Union[str, Path]",
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir: "Optional[Union[str, Path]]" = None,
) -> list[dict]:
    """Render the tcga_patient_cn figures OFFLINE from persisted plot_data.

    NO live read — reconstructs the frame and delegates to the same cli.emit_*
    draw functions a live run uses.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    data = _reconstruct(plot_data)
    target = data.get("target") or target
    indication = data.get("indication") or indication

    figures = []

    # Emit amplification pie chart
    if data.get("amp_freq") is not None and data.get("amp_genes"):
        # Note: emit_cn_frequency_pie expects both any-level and focal-level frequencies
        # For offline rendering, we use the stored frequency as "any" level
        # Focal level would need to be stored separately in plot_data for full support
        amp_any = data["amp_freq"]
        amp_focal = summary.get("patient_focal_amplification_freq", 0.0)

        svg = _cli.emit_cn_frequency_pie(
            target,
            indication,
            target_any_indication=amp_any,
            target_focal_indication=amp_focal,
            indication_gene_frequencies=data["amp_genes"],
            target_any_pancancer=summary.get("pancancer_amp_freq", amp_any),
            target_focal_pancancer=summary.get("pancancer_focal_amp_freq", amp_focal),
            pancancer_gene_frequencies=data.get("amp_genes_pancancer", data["amp_genes"]),
            out_path=out_dir,
            contracts_root=tcd,
            cn_type="amplification",
        )
        if svg:
            figures.append({
                "id": "cn_amplification_pie",
                "path": "figure_cn_amplification_pie.svg",
                "type": "cn_frequency_pie",
                "primary": True,
            })

    # Emit deletion pie chart
    if data.get("del_freq") is not None and data.get("del_genes"):
        del_any = data["del_freq"]
        del_focal = summary.get("patient_focal_deletion_freq", 0.0)

        svg = _cli.emit_cn_frequency_pie(
            target,
            indication,
            target_any_indication=del_any,
            target_focal_indication=del_focal,
            indication_gene_frequencies=data["del_genes"],
            target_any_pancancer=summary.get("pancancer_del_freq", del_any),
            target_focal_pancancer=summary.get("pancancer_focal_del_freq", del_focal),
            pancancer_gene_frequencies=data.get("del_genes_pancancer", data["del_genes"]),
            out_path=out_dir,
            contracts_root=tcd,
            cn_type="deletion",
        )
        if svg:
            figures.append({
                "id": "cn_deletion_pie",
                "path": "figure_cn_deletion_pie.svg",
                "type": "cn_frequency_pie",
                "primary": False,
            })

    # Emit amplification stacked bar
    if data.get("amp_freq") is not None and data.get("amp_genes"):
        svg = _cli.emit_cn_frequency_stacked(
            target,
            indication,
            target_freq_indication=data["amp_freq"],
            indication_gene_frequencies=data["amp_genes"],
            target_freq_pancancer=summary.get("pancancer_amp_freq", data["amp_freq"]),
            pancancer_gene_frequencies=data.get("amp_genes_pancancer", data["amp_genes"]),
            out_path=out_dir,
            contracts_root=tcd,
            cn_type="amplification",
            focal_events=True,
        )
        if svg:
            figures.append({
                "id": "cn_amplification_stacked",
                "path": "figure_cn_amplification_stacked.svg",
                "type": "cn_frequency_stacked",
                "primary": False,
            })

    # Emit deletion stacked bar
    if data.get("del_freq") is not None and data.get("del_genes"):
        svg = _cli.emit_cn_frequency_stacked(
            target,
            indication,
            target_freq_indication=data["del_freq"],
            indication_gene_frequencies=data["del_genes"],
            target_freq_pancancer=summary.get("pancancer_del_freq", data["del_freq"]),
            pancancer_gene_frequencies=data.get("del_genes_pancancer", data["del_genes"]),
            out_path=out_dir,
            contracts_root=tcd,
            cn_type="deletion",
            focal_events=True,
        )
        if svg:
            figures.append({
                "id": "cn_deletion_stacked",
                "path": "figure_cn_deletion_stacked.svg",
                "type": "cn_frequency_stacked",
                "primary": False,
            })

    return figures
