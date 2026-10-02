"""Offline figure rendering from persisted plot_data for gdc_somatic_hotspot.

Reconstructs the hotspot lollipop and mutation frequency stacked figures from the
persisted plot_data.parquet (emitted by cli.emit_plot_data), delegating to the SAME
cli.emit_* draw functions a live run uses — so the figures render OFFLINE,
deterministically, byte-identical to a live run, with NO second MC3/S3 read.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from . import cli as _cli

_REQUIRED_COLUMNS = ("target", "indication", "frequency", "row_type")


def _reconstruct_data(plot_data: Union[str, Path, object]) -> tuple[list, float, list, str, str]:
    """Rebuild (hotspot_frequencies, overall_frequency, all_gene_frequencies, target, indication)
    from a plot_data DataFrame or parquet path. NO S3 access."""
    import pandas as pd

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")

    target = df["target"].iloc[0] if not df.empty else ""
    indication = df["indication"].iloc[0] if not df.empty else ""

    hotspot_rows = df[df["row_type"] == "hotspot"]
    hotspot_frequencies = [
        {
            "protein_change": row["protein_change"],
            "frequency": row["frequency"],
            "n_samples": row.get("n_samples"),
        }
        for _, row in hotspot_rows.iterrows()
    ]

    summary_row = df[df["row_type"] == "target_summary"]
    overall_frequency = float(summary_row["frequency"].iloc[0]) if not summary_row.empty else 0.0

    context_rows = df[df["row_type"] == "all_genes_context"]
    all_gene_frequencies = []
    for _, row in context_rows.iterrows():
        gene = row.get("gene_symbol")
        freq = row["frequency"]
        if freq is not None:
            all_gene_frequencies.append((gene, float(freq)))

    return hotspot_frequencies, overall_frequency, all_gene_frequencies, target, indication


def render_hotspot_lollipop_from_plot_data(
    plot_data: Union[str, Path, object],
    summary: dict,
    out_dir: Union[str, Path],
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir: Optional[Union[str, Path]] = None,
) -> list[dict]:
    """Render the hotspot lollipop figure OFFLINE from persisted plot_data. NO live read."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    hotspot_frequencies, _, _, data_target, data_indication = _reconstruct_data(plot_data)
    target = target or data_target
    indication = indication or data_indication

    svg_path = _cli.emit_hotspot_lollipop(
        hotspot_frequencies,
        target,
        indication,
        out_dir,
        tcd,
    )

    if svg_path is None:
        return []

    return [
        {
            "id": "hotspot_lollipop",
            "path": "figure_hotspot_lollipop.svg",
            "type": "mutation_hotspot_lollipop",
            "primary": True,
        },
    ]


def render_mutation_frequency_stacked_from_plot_data(
    plot_data_indication: Union[str, Path, object],
    plot_data_pancancer: Union[str, Path, object],
    summary: dict,
    out_dir: Union[str, Path],
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir: Optional[Union[str, Path]] = None,
) -> list[dict]:
    """Render the stacked mutation frequency figure OFFLINE from persisted plot_data. NO live read."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    _, freq_ind, genes_ind, data_target, data_indication = _reconstruct_data(plot_data_indication)
    _, freq_pan, genes_pan, _, _ = _reconstruct_data(plot_data_pancancer)

    target = target or data_target
    indication = indication or data_indication

    svg_path = _cli.emit_mutation_frequency_stacked(
        target,
        indication,
        freq_ind,
        genes_ind,
        freq_pan,
        genes_pan,
        out_dir,
        tcd,
    )

    if svg_path is None:
        return []

    return [
        {
            "id": "mutation_frequency_stacked",
            "path": "figure_mutation_frequency_stacked.svg",
            "type": "mutation_frequency_comparison",
            "primary": True,
        },
    ]


def render_hotspot_pie_from_plot_data(
    plot_data_indication: Union[str, Path, object],
    plot_data_pancancer: Union[str, Path, object],
    summary: dict,
    out_dir: Union[str, Path],
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir: Optional[Union[str, Path]] = None,
) -> list[dict]:
    """Render the hotspot pie chart OFFLINE from persisted plot_data. NO live read."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    hotspots_ind, overall_freq_ind, _, data_target, data_indication = _reconstruct_data(plot_data_indication)
    hotspots_pan, overall_freq_pan, _, _, _ = _reconstruct_data(plot_data_pancancer)

    target = target or data_target
    indication = indication or data_indication

    svg_path = _cli.emit_hotspot_pie(
        hotspots_ind,
        hotspots_pan,
        overall_freq_ind,
        overall_freq_pan,
        target,
        indication,
        out_dir,
        tcd,
    )

    if svg_path is None:
        return []

    return [
        {
            "id": "hotspot_pie",
            "path": "figure_hotspot_pie.svg",
            "type": "hotspot_distribution_pie",
            "primary": True,
        },
    ]


def render_mutation_frequency_pie_from_plot_data(
    plot_data_indication: Union[str, Path, object],
    plot_data_pancancer: Union[str, Path, object],
    summary: dict,
    out_dir: Union[str, Path],
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir: Optional[Union[str, Path]] = None,
) -> list[dict]:
    """Render the mutation frequency pie chart OFFLINE from persisted plot_data. NO live read."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tcd = Path(target_contracts_dir) if target_contracts_dir else _cli.DEFAULT_TARGET_CONTRACTS

    _, freq_ind, genes_ind, data_target, data_indication = _reconstruct_data(plot_data_indication)
    _, freq_pan, genes_pan, _, _ = _reconstruct_data(plot_data_pancancer)

    target = target or data_target
    indication = indication or data_indication

    svg_path = _cli.emit_mutation_frequency_pie(
        target,
        indication,
        freq_ind,
        genes_ind,
        freq_pan,
        genes_pan,
        out_dir,
        tcd,
    )

    if svg_path is None:
        return []

    return [
        {
            "id": "mutation_frequency_pie",
            "path": "figure_mutation_frequency_pie.svg",
            "type": "mutation_frequency_pie",
            "primary": False,
        },
    ]


def render_from_plot_data(
    plot_data: Union[str, Path, object],
    summary: dict,
    out_dir: Union[str, Path],
    target: str,
    indication: Optional[str] = None,
    *,
    target_contracts_dir: Optional[Union[str, Path]] = None,
    plot_data_pancancer: Optional[Union[str, Path, object]] = None,
) -> list[dict]:
    """Render gdc_somatic_hotspot figures OFFLINE from persisted plot_data.

    Args:
        plot_data: Path to indication-level plot_data.parquet
        summary: Card summary dict
        out_dir: Output directory for figures
        target: Gene symbol
        indication: Indication code
        target_contracts_dir: Path to target-contracts repo
        plot_data_pancancer: Optional path to pan-cancer plot_data.parquet
            (required for pie and stacked figures)

    Returns:
        list of figure spec dicts for rendered figures
    """
    specs = []

    # Render hotspot pie (primary) and other figures if pan-cancer data is available
    if plot_data_pancancer is not None:
        # Hotspot pie is the primary figure (replaces lollipop)
        specs.extend(
            render_hotspot_pie_from_plot_data(
                plot_data, plot_data_pancancer, summary, out_dir, target, indication,
                target_contracts_dir=target_contracts_dir
            )
        )
        specs.extend(
            render_mutation_frequency_pie_from_plot_data(
                plot_data, plot_data_pancancer, summary, out_dir, target, indication,
                target_contracts_dir=target_contracts_dir
            )
        )
        specs.extend(
            render_mutation_frequency_stacked_from_plot_data(
                plot_data, plot_data_pancancer, summary, out_dir, target, indication,
                target_contracts_dir=target_contracts_dir
            )
        )

    return specs
