#!/usr/bin/env python3
"""depmap-expression-dependency CLI — Card 4 (expression-dependency correlation).

Consumes DepMap 26Q1 CRISPRGeneEffect.csv (Chronos) +
OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv (TPM log2) + Model.csv
(lineage metadata). For a target gene, computes the cross-cell-line correlation
between its own expression and its own Chronos dependency, emits scatter +
lineage-stratified figures + summary scalars.

Usage:
    depmap-expression-dependency \
        --target KRAS \
        --indication COADREAD \
        --release-pin 26q1 \
        --out /tmp/depmap_expression_dependency_KRAS_COADREAD/

Outputs (in --out directory):
  - summary.json                — decision-grade scalars (Card 4 summary_fields)
  - figure_scatter_with_regression.svg
  - figure_lineage_stratified_scatter.svg
  - plot_data.parquet           — long-format per cell line
  - manifest.yaml               — provenance + exclusion tracking + input keys

API convention: load_*, compute_*, emit_*_plot, emit_plot_data, emit_manifest
are PUBLIC (no underscore) since they're consumed by BOTH the CLI and the
skill's figure-emitter registry. Follows the Card 1+2 pattern.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEFAULT_TARGET_CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
DEPMAP_S3_PREFIX = "s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1"
DEPMAP_LOCAL_FALLBACK_DIRS = [
    Path("/home/sagemaker-user/depmap-26q1"),
    Path("/data/depmap/26q1"),
    Path.home() / "depmap-26q1",
]

# TPM matrix has these metadata columns before any gene column. Skip them when
# scanning for the target gene. The 'IsDefaultEntryForModel' filter ensures one
# row per ModelID (canonical sequencing entry).
TPM_METADATA_COLUMNS = (
    "SequencingID", "ModelConditionID", "ModelID",
    "IsDefaultEntryForMC", "IsDefaultEntryForModel",
)


def load_depmap_files_for_card4(release_pin: str, target_symbol: str) -> tuple[dict, dict, dict, list]:
    """Load Chronos + TPM + Model for the target gene. Returns:
        chronos_by_model: {ModelID → chronos (float)}
        tpm_by_model: {ModelID → TPM_logp1 (float)}
        model_metadata: {ModelID → metadata_dict}
        load_errors: list of structured error dicts (empty if successful)

    Strategy:
      1. Local cache first (DEPMAP_LOCAL_FALLBACK_DIRS).
      2. S3 via boto3 if no local cache.
      3. TPM read is memory-efficient: pd.read_csv with usecols=[ModelID,
         IsDefaultEntryForModel, target_col] avoids loading the full ~400 MB.
    """
    import pandas as pd

    crispr_path = None
    tpm_path = None
    model_path = None
    load_errors = []

    # Local cache discovery
    for fallback_dir in DEPMAP_LOCAL_FALLBACK_DIRS:
        cc = fallback_dir / "CRISPRGeneEffect.csv"
        tt = fallback_dir / "OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv"
        mm = fallback_dir / "Model.csv"
        if cc.exists() and tt.exists() and mm.exists():
            crispr_path = cc
            tpm_path = tt
            model_path = mm
            click.echo(f"  Using local DepMap cache at {fallback_dir}", err=True)
            break

    if crispr_path is None:
        # S3 path
        try:
            import boto3
            s3 = boto3.client("s3")
            bucket = "onc-compbio"
            tpm_key = "data-catalog/sources/depmap-consortium/dmc-26q1/OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv"
            crispr_key = "data-catalog/sources/depmap-consortium/dmc-26q1/CRISPRGeneEffect.csv"
            model_key = "data-catalog/sources/depmap-consortium/dmc-26q1/Model.csv"

            click.echo(f"  Fetching s3://{bucket}/{model_key}", err=True)
            model_obj = s3.get_object(Bucket=bucket, Key=model_key)
            model_df = pd.read_csv(BytesIO(model_obj["Body"].read()))

            click.echo(f"  Fetching s3://{bucket}/{crispr_key} (target column only)", err=True)
            crispr_obj = s3.get_object(Bucket=bucket, Key=crispr_key)
            crispr_df = pd.read_csv(BytesIO(crispr_obj["Body"].read()))

            # TPM: locate target column from header, then re-fetch with usecols filter.
            # Memory-efficient: full file is ~400 MB; we read 3 columns only.
            click.echo(f"  Fetching s3://{bucket}/{tpm_key} (target column only)", err=True)
            tpm_obj = s3.get_object(Bucket=bucket, Key=tpm_key)
            # Read entire file (S3 streaming makes usecols-only impractical via boto3 BytesIO).
            # In production we'd want a multi-pass read or pyarrow streaming.
            tpm_df = pd.read_csv(BytesIO(tpm_obj["Body"].read()))
        except ImportError as e:
            load_errors.append({
                "_live_read_error": "boto3_not_available",
                "detail": str(e),
                "remediation": f"Install boto3 or provide local cache at {[str(d) for d in DEPMAP_LOCAL_FALLBACK_DIRS]}",
            })
            return {}, {}, {}, load_errors
        except Exception as e:
            load_errors.append({
                "_live_read_error": "s3_read_failed",
                "detail": str(e),
                "remediation": f"Ensure AWS credentials are set and bucket {DEPMAP_S3_PREFIX} is accessible.",
            })
            return {}, {}, {}, load_errors
    else:
        model_df = pd.read_csv(model_path)
        crispr_df = pd.read_csv(crispr_path)
        # For local-cache path we can use pd.read_csv with usecols since file is on disk.
        # First peek at header for target column.
        tpm_header = pd.read_csv(tpm_path, nrows=0)
        target_tpm_cols = [c for c in tpm_header.columns
                            if c == target_symbol or c.split(" ")[0] == target_symbol]
        if not target_tpm_cols:
            load_errors.append({
                "_live_read_error": "target_not_in_tpm_matrix",
                "detail": f"Target {target_symbol} not in TPM matrix",
            })
            return {}, {}, {}, load_errors
        usecols = list(TPM_METADATA_COLUMNS) + [target_tpm_cols[0]]
        # Some metadata columns may not exist in older releases; filter to those present
        usecols = [c for c in usecols if c in tpm_header.columns]
        tpm_df = pd.read_csv(tpm_path, usecols=usecols)

    # === Extract target Chronos column ===
    chronos_target_cols = [c for c in crispr_df.columns
                            if c == target_symbol or c.split(" ")[0] == target_symbol]
    if not chronos_target_cols:
        load_errors.append({
            "_live_read_error": "target_not_in_crispr_panel",
            "detail": f"Target {target_symbol} not in CRISPRGeneEffect.csv",
        })
        return {}, {}, {}, load_errors
    chronos_target_col = chronos_target_cols[0]
    chronos_id_col = crispr_df.columns[0]
    chronos_by_model = {}
    for _, row in crispr_df[[chronos_id_col, chronos_target_col]].iterrows():
        if pd.notna(row[chronos_target_col]):
            chronos_by_model[row[chronos_id_col]] = float(row[chronos_target_col])

    # === Extract target TPM column with IsDefaultEntryForModel filter ===
    tpm_target_cols = [c for c in tpm_df.columns
                        if c == target_symbol or c.split(" ")[0] == target_symbol]
    if not tpm_target_cols:
        load_errors.append({
            "_live_read_error": "target_not_in_tpm_matrix",
            "detail": f"Target {target_symbol} not in TPM matrix",
        })
        return chronos_by_model, {}, {}, load_errors
    tpm_target_col = tpm_target_cols[0]
    # Filter to default-entry-per-model. DepMap 26Q1 encodes IsDefaultEntryForModel
    # as STRING "Yes"/"No" (not boolean True/False). Accept both formats so older
    # releases or synthetic test fixtures with bool values keep working.
    if "IsDefaultEntryForModel" in tpm_df.columns:
        flag = tpm_df["IsDefaultEntryForModel"]
        tpm_filtered = tpm_df[flag.isin([True, "Yes", "yes", "true", "TRUE"])]
        if tpm_filtered.empty:
            # Defensive fallback: if filter eliminated everything, the dtype/values
            # may be unexpected. Use unfiltered rather than emit empty TPM.
            tpm_filtered = tpm_df
    else:
        tpm_filtered = tpm_df
    tpm_id_col = "ModelID" if "ModelID" in tpm_filtered.columns else tpm_filtered.columns[0]
    tpm_by_model = {}
    for _, row in tpm_filtered[[tpm_id_col, tpm_target_col]].iterrows():
        if pd.notna(row[tpm_target_col]):
            tpm_by_model[row[tpm_id_col]] = float(row[tpm_target_col])

    # === Model metadata ===
    model_id_col = "ModelID" if "ModelID" in model_df.columns else model_df.columns[0]
    model_metadata = {row[model_id_col]: row.to_dict() for _, row in model_df.iterrows()}

    return chronos_by_model, tpm_by_model, model_metadata, load_errors


def compute_correlation_summary(
    chronos_by_model: dict, tpm_by_model: dict, model_metadata: dict,
    indication: str,
    strong_threshold: float = -0.4,
    moderate_threshold: float = -0.2,
    weak_threshold: float = -0.1,
    positive_anomaly_threshold: float = 0.2,
    significance_alpha: float = 0.01,
    biomarker_chronos_threshold: float = -0.5,
    min_tpm_iqr: float = 1.0,
    pan_essential_median: float = -0.5,
) -> dict:
    """Compute Card 4 summary fields. Pure compute over loaded dicts.

    Args mirror the card_spec thresholds; defaults match cards/expression-
    dependency-correlation.card.yaml.
    """
    import numpy as np
    import pandas as pd
    from scipy import stats

    INDICATION_LINEAGE = {
        "COADREAD": "Bowel", "PDAC": "Pancreas", "NSCLC": "Lung",
        "SCLC": "Lung", "GC": "Stomach",
    }
    target_lineage = INDICATION_LINEAGE.get(indication, "")

    # Join Chronos + TPM on ModelID, attach lineage
    rows = []
    for mid in set(chronos_by_model.keys()) & set(tpm_by_model.keys()):
        meta = model_metadata.get(mid, {})
        lineage = meta.get("OncotreeLineage") or meta.get("lineage") or "unknown"
        rows.append({
            "ModelID": mid,
            "chronos": chronos_by_model[mid],
            "tpm_logp1": tpm_by_model[mid],
            "OncotreeLineage": str(lineage),
        })
    if not rows:
        return {"_no_overlap_between_chronos_and_tpm": True,
                 "n_cell_lines_evaluated": 0}

    df = pd.DataFrame(rows)
    n = len(df)

    # === Core correlation ===
    if df["tpm_logp1"].std() < 1e-9 or df["chronos"].std() < 1e-9:
        return {
            "_no_variance": True,
            "n_cell_lines_evaluated": n,
            "_data_note": "no variance in expression or Chronos — correlation undefined",
        }
    pearson_r, pearson_p = stats.pearsonr(df["tpm_logp1"], df["chronos"])
    spearman_r, spearman_p = stats.spearmanr(df["tpm_logp1"], df["chronos"])

    # === Distribution context ===
    tpm_q25, tpm_q75 = df["tpm_logp1"].quantile([0.25, 0.75])
    chronos_q25, chronos_q75 = df["chronos"].quantile([0.25, 0.75])

    # === Quartile stratification ===
    high_expr_mask = df["tpm_logp1"] >= tpm_q75
    low_expr_mask = df["tpm_logp1"] <= tpm_q25
    chronos_high = float(df.loc[high_expr_mask, "chronos"].median()) if high_expr_mask.any() else None
    chronos_low = float(df.loc[low_expr_mask, "chronos"].median()) if low_expr_mask.any() else None
    delta_top_vs_bottom = (chronos_high - chronos_low) if (chronos_high is not None and chronos_low is not None) else None

    # === Lineage breakout in high-expression subset ===
    high_expr_subset = df[high_expr_mask]
    lineage_breakout = []
    for ln_name, sub in high_expr_subset.groupby("OncotreeLineage"):
        if len(sub) < 3:
            continue
        lineage_breakout.append({
            "lineage": str(ln_name),
            "n_high_expr": int(len(sub)),
            "mean_chronos_high_expr": float(sub["chronos"].mean()),
        })
    lineage_breakout.sort(key=lambda x: x["mean_chronos_high_expr"])

    # === Classification ===
    if pearson_r > positive_anomaly_threshold:
        correlation_class = "positive_anomaly"
    elif pearson_r <= strong_threshold and pearson_p <= significance_alpha:
        correlation_class = "strong_negative"
    elif pearson_r <= moderate_threshold and pearson_p <= significance_alpha:
        correlation_class = "moderate_negative"
    elif pearson_r <= weak_threshold:
        correlation_class = "weak_negative"
    else:
        correlation_class = "no_correlation"

    return {
        "pearson_r": float(pearson_r),
        "pearson_p": float(pearson_p),
        "spearman_r": float(spearman_r),
        "spearman_p": float(spearman_p),
        "n_cell_lines_evaluated": n,
        "mean_chronos": float(df["chronos"].mean()),
        "mean_tpm_logp1": float(df["tpm_logp1"].mean()),
        "tpm_iqr": float(tpm_q75 - tpm_q25),
        "chronos_iqr": float(chronos_q75 - chronos_q25),
        "chronos_at_high_expression": chronos_high,
        "chronos_at_low_expression": chronos_low,
        "delta_chronos_top_vs_bottom_quartile": delta_top_vs_bottom,
        "top_lineages_by_dependence_high_expression": lineage_breakout[:5],
        "correlation_class": correlation_class,
        # Internal-only (underscore-prefixed; renderer hides):
        "_target_lineage": target_lineage,
        "_merged_data_n_rows": n,
    }


def _setup_plot_style(contracts_root: Path):
    """Load mplstyle + return palette helpers. Cached side effect (matplotlib.style)."""
    import matplotlib.pyplot as plt
    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    from takeda_palette import (  # type: ignore
        get_lineage_color, REFLINE_NEUTRAL, REFLINE_KILLER, REFLINE_NOMINAL,
        FIGSIZE_DOUBLE_COLUMN, FIGSIZE_DOUBLE_COLUMN_TALL,
        CHRONOS_STRONG_DEPENDENCY, LINEAGE_DEFAULT_COLOR,
    )
    return {
        "get_lineage_color": get_lineage_color,
        "REFLINE_NEUTRAL": REFLINE_NEUTRAL,
        "REFLINE_KILLER": REFLINE_KILLER,
        "REFLINE_NOMINAL": REFLINE_NOMINAL,
        "FIGSIZE_DOUBLE_COLUMN": FIGSIZE_DOUBLE_COLUMN,
        "FIGSIZE_DOUBLE_COLUMN_TALL": FIGSIZE_DOUBLE_COLUMN_TALL,
        "CHRONOS_STRONG_DEPENDENCY": CHRONOS_STRONG_DEPENDENCY,
        "LINEAGE_DEFAULT_COLOR": LINEAGE_DEFAULT_COLOR,
    }


def emit_scatter_regression_plot(merged_data: list, target_symbol: str,
                                  indication: str, summary: dict,
                                  out_path: Path, contracts_root: Path) -> None:
    """Primary figure: lineage-colored scatter of expression vs Chronos with OLS line + r/p block.
    Target-indication lineage is emphasized (larger marker + thicker edge)."""
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from collections import Counter
    from matplotlib.patches import Patch

    style = _setup_plot_style(contracts_root)
    df = pd.DataFrame(merged_data)

    INDICATION_LINEAGE = {"COADREAD": "Bowel", "PDAC": "Pancreas", "NSCLC": "Lung",
                          "SCLC": "Lung", "GC": "Stomach"}
    target_lineage = INDICATION_LINEAGE.get(indication, "")

    fig, ax = plt.subplots(figsize=style["FIGSIZE_DOUBLE_COLUMN"])

    if df.empty:
        ax.text(0.5, 0.5, "No data — see manifest", ha="center", va="center",
                transform=ax.transAxes, color="#666666")
        fig.savefig(out_path / "figure_scatter_with_regression.svg", bbox_inches="tight")
        plt.close(fig)
        return

    # Identify top-5 lineages for legend (by n cells)
    lineage_counts = Counter(df["lineage"])
    top_lineages = [lg for lg, _ in lineage_counts.most_common(5)]

    # Background scatter — all cells, non-target lineage
    is_target = df["lineage"] == target_lineage
    other = df[~is_target]
    target_pts = df[is_target]

    for lg in top_lineages:
        sub = other[other["lineage"] == lg]
        if sub.empty:
            continue
        ax.scatter(sub["tpm_logp1"], sub["chronos"],
                    s=14, alpha=0.55, color=style["get_lineage_color"](lg),
                    edgecolor="white", linewidth=0.3, zorder=2,
                    label=None)
    # "Other lineages" (not in top-5)
    other_others = other[~other["lineage"].isin(top_lineages)]
    if not other_others.empty:
        ax.scatter(other_others["tpm_logp1"], other_others["chronos"],
                    s=12, alpha=0.35, color="#CCCCCC",
                    edgecolor="white", linewidth=0.2, zorder=1)

    # Target-lineage emphasis — larger + thicker edge + on top
    if not target_pts.empty:
        ax.scatter(target_pts["tpm_logp1"], target_pts["chronos"],
                    s=28, alpha=0.85,
                    color=style["get_lineage_color"](target_lineage),
                    edgecolor="#222222", linewidth=0.8, zorder=3)

    # OLS regression line (across all cells)
    if len(df) >= 3 and df["tpm_logp1"].std() > 0:
        slope, intercept = np.polyfit(df["tpm_logp1"], df["chronos"], deg=1)
        x_line = np.linspace(df["tpm_logp1"].min(), df["tpm_logp1"].max(), 50)
        y_line = slope * x_line + intercept
        ax.plot(x_line, y_line, color="#444444", linewidth=1.5, zorder=2, alpha=0.85)

    # Reference lines + left-edge labels (axes-fraction x, data y) with white bbox
    _label_bbox = dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.5)
    ax.axhline(y=0, **style["REFLINE_NOMINAL"], zorder=1)
    ax.axhline(y=-0.5, **style["REFLINE_NEUTRAL"], zorder=1)
    ax.axhline(y=style["CHRONOS_STRONG_DEPENDENCY"], **style["REFLINE_KILLER"], zorder=1)
    ax.text(0.005, 0.05, "no dependency", fontsize=8, color="#666666",
            ha="left", va="bottom", transform=ax.get_yaxis_transform(),
            bbox=_label_bbox, zorder=4)
    ax.text(0.005, style["CHRONOS_STRONG_DEPENDENCY"], "strong",
            fontsize=8, color="#B22222",
            ha="left", va="bottom", transform=ax.get_yaxis_transform(),
            bbox=_label_bbox, zorder=4)

    # Annotation block (top-right) with r/p stats
    r = summary.get("pearson_r")
    p = summary.get("pearson_p")
    sr = summary.get("spearman_r")
    n_val = summary.get("n_cell_lines_evaluated", len(df))
    if r is not None:
        ann_text = (f"n = {n_val}\n"
                    f"Pearson r = {r:.2f}\n"
                    f"p = {p:.2e}\n"
                    f"Spearman r = {sr:.2f}" if sr is not None else
                    f"n = {n_val}\nPearson r = {r:.2f}\np = {p:.2e}")
        ax.text(0.97, 0.97, ann_text,
                transform=ax.transAxes, ha="right", va="top",
                fontsize=9, family="monospace",
                bbox=dict(facecolor="white", edgecolor="#888888",
                            alpha=0.92, pad=4, boxstyle="round,pad=0.4"),
                zorder=5)

    # Lineage legend (bottom-right)
    if top_lineages:
        legend_handles = [Patch(color=style["get_lineage_color"](lg), label=lg)
                          for lg in top_lineages]
        if target_lineage and target_lineage not in top_lineages and target_lineage:
            legend_handles.insert(0, Patch(color=style["get_lineage_color"](target_lineage),
                                            label=f"{target_lineage} (target)"))
        legend_handles.append(Patch(color="#CCCCCC", label="other"))
        ax.legend(handles=legend_handles, loc="lower right", framealpha=0.9, fontsize=8)

    ax.set_xlabel("Expression (log₂ TPM+1)")
    ax.set_ylabel("Chronos score (more dependent ↓)")
    ax.set_title(f"{target_symbol}: expression-dependency correlation in {indication}")
    ax.grid(axis="y")

    fig.savefig(out_path / "figure_scatter_with_regression.svg", bbox_inches="tight")
    plt.close(fig)


def emit_lineage_stratified_scatter(merged_data: list, target_symbol: str,
                                      indication: str, summary: dict,
                                      out_path: Path, contracts_root: Path) -> None:
    """Alternate figure: 2×3 small-multiples scatter, one panel per top-6 lineage.
    Reveals whether pan-cancer correlation is uniform or driven by 1-2 lineages."""
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from collections import Counter
    from scipy import stats

    style = _setup_plot_style(contracts_root)
    df = pd.DataFrame(merged_data)

    INDICATION_LINEAGE = {"COADREAD": "Bowel", "PDAC": "Pancreas", "NSCLC": "Lung",
                          "SCLC": "Lung", "GC": "Stomach"}
    target_lineage = INDICATION_LINEAGE.get(indication, "")

    if df.empty:
        fig, ax = plt.subplots(figsize=style["FIGSIZE_DOUBLE_COLUMN_TALL"])
        ax.text(0.5, 0.5, "No data", ha="center", va="center",
                transform=ax.transAxes, color="#666666")
        fig.savefig(out_path / "figure_lineage_stratified_scatter.svg", bbox_inches="tight")
        plt.close(fig)
        return

    # Pick lineages: top-6 by n with min 10 cells, plus target_lineage always
    lineage_counts = Counter(df["lineage"])
    candidates = [lg for lg, n in lineage_counts.most_common() if n >= 10][:6]
    if target_lineage and target_lineage not in candidates and lineage_counts.get(target_lineage, 0) > 0:
        candidates = [target_lineage] + candidates[:5]
    candidates = candidates[:6]

    fig, axes = plt.subplots(2, 3, figsize=style["FIGSIZE_DOUBLE_COLUMN_TALL"],
                              sharex=True, sharey=True)
    axes = axes.flatten()

    for i, ax in enumerate(axes):
        if i >= len(candidates):
            ax.axis("off")
            continue
        lg = candidates[i]
        color = style["get_lineage_color"](lg)
        # Faded background scatter (other lineages, panel-wide context)
        bg = df[df["lineage"] != lg]
        ax.scatter(bg["tpm_logp1"], bg["chronos"],
                    s=8, alpha=0.12, color="#CCCCCC", zorder=1)
        # Foreground: this lineage
        fg = df[df["lineage"] == lg]
        ax.scatter(fg["tpm_logp1"], fg["chronos"],
                    s=14, alpha=0.85, color=color,
                    edgecolor="white", linewidth=0.3, zorder=3)
        # Within-lineage OLS line (skip if n < 8)
        n_lg = len(fg)
        if n_lg >= 8 and fg["tpm_logp1"].std() > 0:
            slope, intercept = np.polyfit(fg["tpm_logp1"], fg["chronos"], deg=1)
            x_line = np.linspace(fg["tpm_logp1"].min(), fg["tpm_logp1"].max(), 30)
            ax.plot(x_line, slope * x_line + intercept,
                    color=color, linewidth=1.5, zorder=4, alpha=0.9)
        # Annotation: n + r
        r_lg = None
        if n_lg >= 3 and fg["tpm_logp1"].std() > 0:
            r_lg, _ = stats.pearsonr(fg["tpm_logp1"], fg["chronos"])
        ann = f"n={n_lg}, r={r_lg:.2f}" if r_lg is not None else f"n={n_lg}"
        ax.text(0.97, 0.97, ann, transform=ax.transAxes,
                ha="right", va="top", fontsize=8, family="monospace",
                color="#222222")
        # Reference lines
        ax.axhline(y=0, **style["REFLINE_NOMINAL"], zorder=1)
        ax.axhline(y=style["CHRONOS_STRONG_DEPENDENCY"],
                    **style["REFLINE_KILLER"], zorder=1)
        # Panel title — bold for target lineage
        is_target = (lg == target_lineage)
        ax.set_title(lg, fontsize=10, fontweight="bold" if is_target else "normal",
                      color="#B22222" if is_target else "#222222")
        ax.grid(axis="y", alpha=0.4)

    for ax in axes[len(candidates):]:
        ax.axis("off")

    # Common labels
    fig.suptitle(f"{target_symbol}: expression-dependency by lineage in {indication}",
                  fontsize=12, fontweight="bold", y=0.99)
    fig.supxlabel("Expression (log₂ TPM+1)", fontsize=10)
    fig.supylabel("Chronos score (more dependent ↓)", fontsize=10)
    plt.tight_layout()

    fig.savefig(out_path / "figure_lineage_stratified_scatter.svg", bbox_inches="tight")
    plt.close(fig)


def emit_plot_data(merged_data: list, out_path: Path) -> None:
    """Emit plot_data.parquet — long-format per cell line for re-rendering."""
    import pandas as pd

    df = pd.DataFrame(merged_data)
    if df.empty:
        df.to_parquet(out_path / "plot_data.parquet", index=False)
        return

    # Add quartile flags
    if df["tpm_logp1"].notna().any():
        q25 = df["tpm_logp1"].quantile(0.25)
        q75 = df["tpm_logp1"].quantile(0.75)
        df["is_high_expression"] = df["tpm_logp1"] >= q75
        df["is_low_expression"] = df["tpm_logp1"] <= q25
    else:
        df["is_high_expression"] = False
        df["is_low_expression"] = False

    df.to_parquet(out_path / "plot_data.parquet", index=False)


def emit_manifest(target: str, indication: str, release_pin: str,
                   summary: dict, n_excluded: dict, out_path: Path,
                   load_errors: list) -> None:
    import yaml
    manifest = {
        "method": "depmap-expression-dependency",
        "method_version": METHOD_VERSION,
        "target": target,
        "indication": indication,
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_manifest": "depmap-consortium-26q1",
        "input_files_consumed": [
            "CRISPRGeneEffect.csv",
            "OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv",
            "Model.csv",
        ],
        "n_cell_lines_evaluated": summary.get("n_cell_lines_evaluated"),
        "n_cell_lines_excluded_no_chronos": n_excluded.get("no_chronos", 0),
        "n_cell_lines_excluded_no_tpm": n_excluded.get("no_tpm", 0),
        "pearson_r": summary.get("pearson_r"),
        "pearson_p": summary.get("pearson_p"),
        "correlation_class": summary.get("correlation_class"),
        "load_errors": load_errors,
    }
    with (out_path / "manifest.yaml").open("w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)


def build_merged_data(chronos_by_model: dict, tpm_by_model: dict,
                       model_metadata: dict, target_lineage: str) -> list:
    """Build the long-format merged data list. Pure function — used by figure emitters
    AND emit_plot_data. Centralized so all three callers use the same shape."""
    merged = []
    for mid in set(chronos_by_model.keys()) & set(tpm_by_model.keys()):
        meta = model_metadata.get(mid, {})
        lineage = meta.get("OncotreeLineage") or meta.get("lineage") or "unknown"
        merged.append({
            "cell_line_id": mid,
            "cell_line_name": meta.get("CellLineName", mid),
            "chronos_score": chronos_by_model[mid],
            "chronos": chronos_by_model[mid],  # alias for figure emitters
            "tpm_logp1": tpm_by_model[mid],
            "lineage": str(lineage),
            "is_target_lineage": bool(lineage == target_lineage),
        })
    return merged


@click.command()
@click.option("--target", required=True)
@click.option("--indication", required=True,
              type=click.Choice(["COADREAD", "PDAC", "NSCLC", "SCLC", "GC"]))
@click.option("--release-pin", default="26q1")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path))
@click.option("--contracts-root", type=click.Path(file_okay=False, path_type=Path),
              default=DEFAULT_TARGET_CONTRACTS)
@click.option("--dry-run", is_flag=True)
def main(target, indication, release_pin, out, contracts_root, dry_run) -> int:
    """Compute expression-dependency correlation for (target, indication) and
    emit summary + figures + plot_data + manifest."""
    out.mkdir(parents=True, exist_ok=True)
    click.echo(f"=== depmap-expression-dependency (Card 4) ===")
    click.echo(f"  target:      {target}")
    click.echo(f"  indication:  {indication}")
    click.echo(f"  release_pin: {release_pin}")
    click.echo(f"  out:         {out}")
    if dry_run:
        click.echo("(--dry-run: skipping)")
        return 0

    chronos_by_model, tpm_by_model, model_metadata, load_errors = load_depmap_files_for_card4(
        release_pin, target
    )
    if load_errors:
        click.echo(f"  LOAD ERRORS: {len(load_errors)}", err=True)
        with (out / "summary.json").open("w") as f:
            json.dump({"_live_read_error": True, "errors": load_errors,
                       "target": target, "indication": indication}, f, indent=2)
        emit_manifest(target, indication, release_pin, {}, {}, out, load_errors)
        return 2

    summary = compute_correlation_summary(
        chronos_by_model, tpm_by_model, model_metadata, indication=indication
    )
    target_lineage = summary.get("_target_lineage", "")

    n_chronos_only = len(set(chronos_by_model.keys()) - set(tpm_by_model.keys()))
    n_tpm_only = len(set(tpm_by_model.keys()) - set(chronos_by_model.keys()))
    n_excluded = {"no_tpm": n_chronos_only, "no_chronos": n_tpm_only}

    with (out / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2, default=str)

    merged_data = build_merged_data(chronos_by_model, tpm_by_model,
                                      model_metadata, target_lineage)
    emit_plot_data(merged_data, out)
    emit_scatter_regression_plot(merged_data, target, indication, summary, out, contracts_root)
    emit_lineage_stratified_scatter(merged_data, target, indication, summary, out, contracts_root)
    emit_manifest(target, indication, release_pin, summary, n_excluded, out, load_errors)

    click.echo(f"  → summary.json:               {out / 'summary.json'}")
    click.echo(f"  → figure_scatter_with_regression:    {out / 'figure_scatter_with_regression.svg'}")
    click.echo(f"  → figure_lineage_stratified_scatter: {out / 'figure_lineage_stratified_scatter.svg'}")
    click.echo(f"  → plot_data.parquet:          {out / 'plot_data.parquet'}")
    click.echo(f"  → manifest.yaml:              {out / 'manifest.yaml'}")
    click.echo(f"  correlation_class: {summary.get('correlation_class')}")
    click.echo(f"  pearson_r = {summary.get('pearson_r')}, p = {summary.get('pearson_p')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
