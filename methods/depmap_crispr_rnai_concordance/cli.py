#!/usr/bin/env python3
"""depmap-crispr-rnai-concordance CLI — derived concordance card.

DERIVED CARD: consumes outputs of the two upstream loaders:
  - methods.depmap_chronos_distribution.cli.load_depmap_files (CRISPR Chronos)
  - methods.depmap_demeter_distribution.cli.load_rnai_files (RNAi DEMETER2)

Computes a partition-preserving cell-line union: every line measured in EITHER
assay falls into one of 8 concordance buckets. No imputation. Surfaces
n_in_both / n_crispr_only / n_rnai_only as explicit denominator slices.

Concordance buckets (per cell line):
  - agree_dependent              : both assays call dependent (CRISPR ≤ -0.5, RNAi ≤ -0.25)
  - agree_non_dependent          : both assays call non-dependent
  - disagree_crispr_dependent    : CRISPR dependent, RNAi non-dependent
  - disagree_rnai_dependent      : RNAi dependent, CRISPR non-dependent
  - crispr_only_dependent        : measured in CRISPR only; dependent
  - crispr_only_non_dependent    : measured in CRISPR only; non-dependent
  - rnai_only_dependent          : measured in RNAi only; dependent
  - rnai_only_non_dependent      : measured in RNAi only; non-dependent

Overall concordance_class (categorical, drives Tier-2 rules):
  - strongly_concordant_dependent
  - strongly_concordant_non_dependent
  - discordant
  - partially_assayed
  - data_unavailable
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click

METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)


def load_concordance_inputs(target_symbol: str, release_pin: str = "26q1") -> tuple[dict, dict, dict, list]:
    """Load CRISPR + RNAi score columns for the target.

    Returns:
        chronos_by_model:    {model_id -> Chronos float}
        demeter_by_model:    {model_id -> DEMETER2 float}
        model_metadata:      {model_id -> meta dict (OncotreeLineage, CCLEName, ...)}
        load_errors:         list (empty on success)

    If either upstream load fails, return the error structure. The concordance
    card requires BOTH upstreams; CRISPR-only or RNAi-only is data_unavailable.
    """
    sys.path.insert(0, str(METHOD_DIR.parent.parent))

    from methods.depmap_chronos_distribution import cli as crispr_cli
    from methods.depmap_demeter_distribution import cli as rnai_cli

    chronos_by_model, model_metadata, crispr_errors = crispr_cli.load_depmap_files(
        release_pin=release_pin, target_symbol=target_symbol
    )
    if crispr_errors:
        return {}, {}, {}, [{"_live_read_error": "crispr_load_failed", "underlying": crispr_errors}]

    demeter_by_model, _meta_rnai, rnai_errors, _si = rnai_cli.load_rnai_files(
        release_pin=release_pin, target_symbol=target_symbol
    )  # 4th return (sample_info_df) added for rnai_screens_contributing; unused here
    if rnai_errors:
        return {}, {}, {}, [{"_live_read_error": "rnai_load_failed", "underlying": rnai_errors}]

    return chronos_by_model, demeter_by_model, model_metadata, []


def _classify_cell_line(
    model_id: str, chronos: Optional[float], demeter: Optional[float], crispr_threshold: float, rnai_threshold: float
) -> str:
    """Assign a single cell line to one of 8 concordance buckets."""
    has_crispr = chronos is not None
    has_rnai = demeter is not None
    if not has_crispr and not has_rnai:
        return "unmeasured"  # should never happen if upstream loaders are sane

    crispr_dep = has_crispr and chronos <= crispr_threshold
    rnai_dep = has_rnai and demeter <= rnai_threshold

    if has_crispr and has_rnai:
        if crispr_dep and rnai_dep:
            return "agree_dependent"
        if not crispr_dep and not rnai_dep:
            return "agree_non_dependent"
        if crispr_dep and not rnai_dep:
            return "disagree_crispr_dependent"
        return "disagree_rnai_dependent"  # rnai_dep and not crispr_dep
    if has_crispr:
        return "crispr_only_dependent" if crispr_dep else "crispr_only_non_dependent"
    # has_rnai only
    return "rnai_only_dependent" if rnai_dep else "rnai_only_non_dependent"


def compute_concordance(
    chronos_by_model: dict,
    demeter_by_model: dict,
    model_metadata: dict,
    crispr_threshold: float = -0.5,
    rnai_threshold: float = -0.25,
    min_overlap_for_call: int = 30,
    strongly_concordant_fraction: float = 0.85,
    discordant_fraction: float = 0.30,
) -> dict:
    """Compute the concordance partition + overall class.

    Per-line buckets are recorded in `per_line_concordance`. Bucket counts +
    derived fractions + the overall categorical class populate the rest of the
    summary dict.
    """
    # Union of cell-line ids
    all_ids = set(chronos_by_model.keys()) | set(demeter_by_model.keys())

    per_line = []
    bucket_counts = {
        "agree_dependent": 0,
        "agree_non_dependent": 0,
        "disagree_crispr_dependent": 0,
        "disagree_rnai_dependent": 0,
        "crispr_only_dependent": 0,
        "crispr_only_non_dependent": 0,
        "rnai_only_dependent": 0,
        "rnai_only_non_dependent": 0,
    }

    for model_id in sorted(all_ids):
        chronos = chronos_by_model.get(model_id)
        demeter = demeter_by_model.get(model_id)
        meta = model_metadata.get(model_id, {})
        bucket = _classify_cell_line(model_id, chronos, demeter, crispr_threshold, rnai_threshold)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        per_line.append(
            {
                "model_id": model_id,
                "ccle_name": meta.get("CCLEName"),
                "lineage": meta.get("OncotreeLineage"),
                "chronos": float(chronos) if chronos is not None else None,
                "demeter2": float(demeter) if demeter is not None else None,
                "concordance_label": bucket,
            }
        )

    # Derived denominator slices
    n_in_both = (
        bucket_counts["agree_dependent"]
        + bucket_counts["agree_non_dependent"]
        + bucket_counts["disagree_crispr_dependent"]
        + bucket_counts["disagree_rnai_dependent"]
    )
    n_crispr_only = bucket_counts["crispr_only_dependent"] + bucket_counts["crispr_only_non_dependent"]
    n_rnai_only = bucket_counts["rnai_only_dependent"] + bucket_counts["rnai_only_non_dependent"]
    n_total = n_in_both + n_crispr_only + n_rnai_only

    # Concordance fractions (on the in-both subset)
    if n_in_both > 0:
        n_agree = bucket_counts["agree_dependent"] + bucket_counts["agree_non_dependent"]
        fraction_agree = n_agree / n_in_both
        fraction_dependent_in_both = bucket_counts["agree_dependent"] / n_in_both
    else:
        fraction_agree = None
        fraction_dependent_in_both = None

    # Overall concordance_class
    if n_in_both < min_overlap_for_call:
        concordance_class = "partially_assayed"
    elif fraction_agree >= strongly_concordant_fraction:
        # Both assays agree for majority — but is the majority calling dependent or non-dependent?
        frac_dep_among_agree = bucket_counts["agree_dependent"] / max(
            1, bucket_counts["agree_dependent"] + bucket_counts["agree_non_dependent"]
        )
        if frac_dep_among_agree >= 0.5:
            concordance_class = "strongly_concordant_dependent"
        else:
            concordance_class = "strongly_concordant_non_dependent"
    elif (1.0 - fraction_agree) >= discordant_fraction:
        concordance_class = "discordant"
    else:
        # MIDDLE band: agreement is below the strongly-concordant floor (0.85) yet above the
        # discordant floor (i.e. disagreement < 0.30) — genuinely ambiguous. Previously this
        # was mislabeled `strongly_concordant_*`, so a target with (e.g.) 25% cross-assay
        # disagreement was reported "strongly concordant" (2026-08-08 review finding). It now
        # gets its own honest `moderately_concordant_*` label. Side (dependent vs non-dependent)
        # still follows whichever the agreeing lines lean toward. The consuming rules read
        # `in: [strongly_*, moderately_*]`, so this relabel is VERDICT-INERT (a moderate-dependent
        # target still fires the dominant concordant-dependent rung) — it sharpens the DESCRIPTIVE
        # label without changing the call.
        n_agree_dep = bucket_counts["agree_dependent"]
        n_agree_nondep = bucket_counts["agree_non_dependent"]
        if n_agree_dep >= n_agree_nondep:
            concordance_class = "moderately_concordant_dependent"
        else:
            concordance_class = "moderately_concordant_non_dependent"

    summary = {
        "n_in_both": n_in_both,
        "n_crispr_only": n_crispr_only,
        "n_rnai_only": n_rnai_only,
        "n_total": n_total,
        "n_agree_dependent": bucket_counts["agree_dependent"],
        "n_agree_non_dependent": bucket_counts["agree_non_dependent"],
        "n_disagree_crispr_dependent": bucket_counts["disagree_crispr_dependent"],
        "n_disagree_rnai_dependent": bucket_counts["disagree_rnai_dependent"],
        "n_crispr_only_dependent": bucket_counts["crispr_only_dependent"],
        "n_crispr_only_non_dependent": bucket_counts["crispr_only_non_dependent"],
        "n_rnai_only_dependent": bucket_counts["rnai_only_dependent"],
        "n_rnai_only_non_dependent": bucket_counts["rnai_only_non_dependent"],
        "fraction_agree": float(fraction_agree) if fraction_agree is not None else None,
        "fraction_dependent_in_both": float(fraction_dependent_in_both)
        if fraction_dependent_in_both is not None
        else None,
        "concordance_class": concordance_class,
        "per_line_concordance": per_line,
    }
    return summary


def emit_concordance_overlay_density(
    per_line: list, target_symbol: str, out_dir: Path, target_contracts_dir: Path
) -> Path:
    """Overlay 1D KDE densities + per-assay rug — PRIMARY figure for concordance.

    CRISPR and RNAi scores are z-score-standardized to a shared x-axis (per-assay
    mean/std normalization), then plotted as overlaid KDEs with per-assay rug
    ticks. Replaces the 2D Chronos-vs-DEMETER2 scatter that previously held the
    primary slot — the 1D overlay communicates concordance/discordance more
    directly than asking the reader to mentally fold a 2D scatter onto its diagonal.

    Each rug row uses ALL cell lines for that assay (not just the in-both subset)
    — partition-preserving union.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scipy.stats import gaussian_kde

    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette as pal  # type: ignore

    crispr_scores = np.array([p["chronos"] for p in per_line if p["chronos"] is not None])
    rnai_scores = np.array([p["demeter2"] for p in per_line if p["demeter2"] is not None])
    if len(crispr_scores) == 0 or len(rnai_scores) == 0:
        # Degenerate case; emit a stub
        fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
        ax.text(
            0.5,
            0.5,
            "Insufficient data for concordance density overlay",
            transform=ax.transAxes,
            ha="center",
            va="center",
            fontsize=10,
            color="#666666",
        )
        out_path = out_dir / "figure_concordance_overlay_density.svg"
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    # Z-score standardization (per-assay): each assay's distribution on a unit-std scale
    crispr_mean, crispr_std = crispr_scores.mean(), crispr_scores.std() or 1.0
    rnai_mean, rnai_std = rnai_scores.mean(), rnai_scores.std() or 1.0
    crispr_z = (crispr_scores - crispr_mean) / crispr_std
    rnai_z = (rnai_scores - rnai_mean) / rnai_std

    # Dependent thresholds in z-score space (informative even if they don't align)
    crispr_dep_z = (-0.5 - crispr_mean) / crispr_std
    rnai_dep_z = (-0.25 - rnai_mean) / rnai_std

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)

    x_min = float(min(crispr_z.min(), rnai_z.min()) - 0.5)
    x_max = float(max(crispr_z.max(), rnai_z.max()) + 0.5)
    xs = np.linspace(x_min, x_max, 500)

    if len(crispr_z) >= 10:
        kde_c = gaussian_kde(crispr_z)
        ax.plot(xs, kde_c(xs), color="#0a2540", linewidth=2, label=f"CRISPR Chronos (n={len(crispr_z)})")
        ax.fill_between(xs, kde_c(xs), alpha=0.15, color="#0a2540")
    if len(rnai_z) >= 10:
        kde_r = gaussian_kde(rnai_z)
        ax.plot(xs, kde_r(xs), color="#f0a020", linewidth=2, label=f"RNAi DEMETER2 (n={len(rnai_z)})")
        ax.fill_between(xs, kde_r(xs), alpha=0.15, color="#f0a020")

    # Threshold reference lines (in z-score space)
    ax.axvline(
        crispr_dep_z,
        color="#0a2540",
        linestyle="--",
        linewidth=1,
        alpha=0.6,
        label=f"CRISPR dep threshold (z={crispr_dep_z:.2f})",
    )
    ax.axvline(
        rnai_dep_z,
        color="#f0a020",
        linestyle="--",
        linewidth=1,
        alpha=0.6,
        label=f"RNAi dep threshold (z={rnai_dep_z:.2f})",
    )

    # Rug ticks: place above the density curves
    y_top = ax.get_ylim()[1]
    rug_h = y_top * 0.04
    rug_y_crispr = y_top + rug_h * 0.5
    rug_y_rnai = y_top + rug_h * 1.7
    for z in crispr_z:
        ax.plot(
            [z, z], [rug_y_crispr - rug_h * 0.3, rug_y_crispr + rug_h * 0.3], color="#0a2540", linewidth=0.4, alpha=0.5
        )
    for z in rnai_z:
        ax.plot([z, z], [rug_y_rnai - rug_h * 0.3, rug_y_rnai + rug_h * 0.3], color="#f0a020", linewidth=0.4, alpha=0.5)
    ax.set_ylim(0, rug_y_rnai + rug_h)

    ax.set_xlabel("Dependency score (z-score, per-assay standardized; lower → more dependent)")
    ax.set_ylabel("Density")
    ax.set_title(f"{target_symbol} — CRISPR vs RNAi dependency density overlay")
    ax.legend(loc="upper right", fontsize=7)

    # Annotation: partition counts (CRISPR-only / RNAi-only / both)
    crispr_only = sum(1 for p in per_line if p["chronos"] is not None and p["demeter2"] is None)
    rnai_only = sum(1 for p in per_line if p["chronos"] is None and p["demeter2"] is not None)
    in_both = sum(1 for p in per_line if p["chronos"] is not None and p["demeter2"] is not None)
    note = f"n_in_both: {in_both}\ncrispr_only: {crispr_only}\nrnai_only: {rnai_only}"
    ax.text(
        0.02, 0.98, note, transform=ax.transAxes, fontsize=7, ha="left", va="top", color="#555555", family="monospace"
    )

    fig.tight_layout()
    out_path = out_dir / "figure_concordance_overlay_density.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_concordance_scatter(per_line: list, target_symbol: str, out_dir: Path, target_contracts_dir: Path) -> Path:
    """Scatter of Chronos vs DEMETER2 with quadrant lines — SECONDARY figure
    (demoted from primary). Only in-both points appear; partition counts annotated."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette as pal  # type: ignore

    in_both = [p for p in per_line if p["chronos"] is not None and p["demeter2"] is not None]
    crispr_only = sum(1 for p in per_line if p["chronos"] is not None and p["demeter2"] is None)
    rnai_only = sum(1 for p in per_line if p["chronos"] is None and p["demeter2"] is not None)

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_SQUARE)
    if in_both:
        xs = [p["chronos"] for p in in_both]
        ys = [p["demeter2"] for p in in_both]
        ax.scatter(xs, ys, alpha=0.5, s=15, color="#0a2540")
    ax.axvline(-0.5, color="#cf2828", linestyle="--", linewidth=1, label="CRISPR dep (-0.5)")
    ax.axhline(-0.25, color="#cf2828", linestyle="--", linewidth=1, label="RNAi dep (-0.25)")
    ax.set_xlabel("CRISPR Chronos")
    ax.set_ylabel("RNAi DEMETER2")
    ax.set_title(f"{target_symbol} — CRISPR vs RNAi (n_in_both={len(in_both)})")
    ax.legend(loc="upper left", fontsize=8)
    note = f"crispr_only: {crispr_only}\nrnai_only: {rnai_only}"
    ax.text(0.98, 0.02, note, transform=ax.transAxes, fontsize=8, ha="right", va="bottom", color="#555555")
    fig.tight_layout()
    out_path = out_dir / "figure_concordance_scatter.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_partition_bar(summary: dict, target_symbol: str, out_dir: Path, target_contracts_dir: Path) -> Path:
    """Stacked bar showing partition counts across the 8 buckets."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette as pal  # type: ignore

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    labels = [
        "agree\nnon-dep",
        "agree\ndep",
        "disagree:\nCRISPR-dep",
        "disagree:\nRNAi-dep",
        "CRISPR-only\nnon-dep",
        "CRISPR-only\ndep",
        "RNAi-only\nnon-dep",
        "RNAi-only\ndep",
    ]
    counts = [
        summary["n_agree_non_dependent"],
        summary["n_agree_dependent"],
        summary["n_disagree_crispr_dependent"],
        summary["n_disagree_rnai_dependent"],
        summary["n_crispr_only_non_dependent"],
        summary["n_crispr_only_dependent"],
        summary["n_rnai_only_non_dependent"],
        summary["n_rnai_only_dependent"],
    ]
    colors = [
        "#7fa7c0",
        "#0a2540",  # agree (light/dark blue)
        "#f0a020",
        "#cf2828",  # disagree (orange/red)
        "#a8b8c0",
        "#506070",  # CRISPR-only (light/dark gray)
        "#b0a8c8",
        "#5a4a78",
    ]  # RNAi-only (light/dark purple)
    ax.bar(labels, counts, color=colors, edgecolor="white")
    for i, c in enumerate(counts):
        ax.text(i, c + max(counts) * 0.01, str(c), ha="center", fontsize=8)
    ax.set_ylabel("Cell lines")
    ax.set_title(f"{target_symbol} — concordance partition (n_total={summary['n_total']})")
    plt.xticks(rotation=0, ha="center", fontsize=8)
    fig.tight_layout()
    out_path = out_dir / "figure_concordance_partition_bar.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_plotly_specs(per_line: list, target_symbol: str, out_path: Path, contracts_root: Path) -> list:
    """Emit interactive Plotly spec SIBLING to the concordance SVGs (Gate-C plotly debt, 2026-07-21).

    Interactive twin of emit_concordance_scatter: CRISPR Chronos (x) vs RNAi DEMETER2 (y) for the
    cell lines assayed in BOTH, with the same quadrant thresholds (-0.5 CRISPR / -0.25 RNAi) and
    per-line hover. Built from the SAME per_line concordance list the SVG + plot_data.parquet use
    (no drift). Points colored by concordance bucket so the both-dependent quadrant reads at a glance.
    Writes figure_concordance_scatter.plotly.json. Best-effort (Plotly optional → SVGs guaranteed)."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001 — Plotly optional; never block the SVG artifacts
        print(f"[crispr-rnai-concordance] plotly spec emission skipped: {e}", file=sys.stderr)
        return []

    written = []
    try:
        in_both = [p for p in per_line if p.get("chronos") is not None and p.get("demeter2") is not None]
        crispr_only = sum(1 for p in per_line if p.get("chronos") is not None and p.get("demeter2") is None)
        rnai_only = sum(1 for p in per_line if p.get("chronos") is None and p.get("demeter2") is not None)
        # color by concordance_label (the per-line bucket _classify_cell_line assigns); else navy.
        # Only in-both lines appear here, so the relevant labels are the agree/disagree ones.
        bucket_color = {
            "agree_dependent": "#cf2828",
            "agree_non_dependent": "#CCCCCC",
            "disagree_crispr_dependent": "#0072B2",
            "disagree_rnai_dependent": "#f0a020",
        }
        xs = [p["chronos"] for p in in_both]
        ys = [p["demeter2"] for p in in_both]
        colors = [bucket_color.get(p.get("concordance_label"), "#0a2540") for p in in_both]
        names = [p.get("model_id", "?") for p in in_both]
        buckets = [p.get("concordance_label", "?") for p in in_both]
        fig = go.Figure(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers",
                marker=dict(color=colors, size=7, opacity=0.6, line=dict(width=0.5, color="white")),
                customdata=list(zip(names, buckets)),
                hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>CRISPR %{x:.2f} / RNAi %{y:.2f}<extra></extra>",
            )
        )
        # quadrant thresholds mirror the SVG exactly (-0.5 CRISPR / -0.25 RNAi).
        fig.add_vline(
            x=-0.5,
            line=dict(color="#cf2828", dash="dash", width=1.5),
            annotation_text="CRISPR dep (-0.5)",
            annotation_position="top",
        )
        fig.add_hline(
            y=-0.25,
            line=dict(color="#cf2828", dash="dash", width=1.5),
            annotation_text="RNAi dep (-0.25)",
            annotation_position="right",
        )
        fig.update_layout(
            title=f"{target_symbol} — CRISPR vs RNAi concordance "
            f"(n_in_both={len(in_both)}; crispr_only={crispr_only}, rnai_only={rnai_only})",
            xaxis_title="CRISPR Chronos",
            yaxis_title="RNAi DEMETER2",
            template="plotly_white",
            showlegend=False,
            margin=dict(l=60, r=20, t=50, b=50),
        )
        (out_path / "figure_concordance_scatter.plotly.json").write_text(fig.to_json())
        written.append(
            {"id": "concordance_scatter", "path": "figure_concordance_scatter.plotly.json", "type": "plotly"}
        )
    except Exception as e:  # noqa: BLE001
        print(f"[crispr-rnai-concordance] scatter plotly skipped: {e}", file=sys.stderr)

    return written


def emit_plot_data(per_line: list, out_path: Path) -> Path:
    """Emit per-line concordance Parquet."""
    import pandas as pd

    df = pd.DataFrame(per_line)
    out_file = out_path / "plot_data_concordance.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_manifest(target_symbol: str, release_pin: str, summary: dict, out_dir: Path, load_errors: list) -> Path:
    """Emit provenance manifest YAML."""
    import yaml

    manifest = {
        "method_id": "depmap-crispr-rnai-concordance",
        "method_version": METHOD_VERSION,
        "card_id": "crispr-rnai-dependency-concordance",
        "target": target_symbol,
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "derived_from": [
            "pan-cancer-crispr-dependency-distribution",
            "pan-cancer-rnai-dependency-distribution",
        ],
        "n_total": summary.get("n_total", 0),
        "n_in_both": summary.get("n_in_both", 0),
        "concordance_class": summary.get("concordance_class", "data_unavailable"),
        "load_errors": load_errors,
    }
    out_file = out_dir / "manifest.yaml"
    with open(out_file, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return out_file


@click.command()
@click.option("--target", required=True, help="HGNC symbol")
@click.option("--release-pin", default="26q1")
@click.option("--crispr-dependent-threshold", default=-0.5, type=float)
@click.option("--rnai-dependent-threshold", default=-0.25, type=float)
@click.option("--out", required=True, type=click.Path(file_okay=False, writable=True, path_type=Path))
def main(target, release_pin, crispr_dependent_threshold, rnai_dependent_threshold, out):
    out.mkdir(parents=True, exist_ok=True)
    chronos_by, demeter_by, model_meta, load_errors = load_concordance_inputs(target, release_pin)
    if load_errors:
        err = {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "concordance_class": "data_unavailable",
        }
        (out / "summary.json").write_text(json.dumps(err, indent=2))
        sys.exit(1)
    summary = compute_concordance(
        chronos_by,
        demeter_by,
        model_meta,
        crispr_threshold=crispr_dependent_threshold,
        rnai_threshold=rnai_dependent_threshold,
    )
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_concordance_overlay_density(summary["per_line_concordance"], target, out, DEFAULT_TARGET_CONTRACTS)
    emit_concordance_scatter(summary["per_line_concordance"], target, out, DEFAULT_TARGET_CONTRACTS)
    emit_partition_bar(summary, target, out, DEFAULT_TARGET_CONTRACTS)
    emit_plot_data(summary["per_line_concordance"], out)
    emit_manifest(target, release_pin, summary, out, [])
    click.echo(f"  -> {out}", err=True)


if __name__ == "__main__":
    main()
