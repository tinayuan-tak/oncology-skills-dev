#!/usr/bin/env python3
"""depmap-chronos-distribution CLI — pan-cancer dependency distribution analysis.

Consumes DepMap 26Q1 CRISPRGeneEffect.csv + Model.csv, computes per-target dependency
distribution stats across the panel, emits summary.json + two SVG figures (waterfall +
histogram-KDE) + plot_data.parquet for the pan-cancer-crispr-dependency-distribution card.

Usage:
    depmap-chronos-distribution \
        --target KRAS \
        --release-pin 26q1 \
        --strong-dependency-threshold -1.0 \
        --catalog-repo /path/to/data-catalog \
        --out /tmp/depmap_chronos_distribution_KRAS/

Inputs (resolved from catalog manifest `depmap-consortium-26q1`):
  - CRISPRGeneEffect.csv (~564 MB) — cell_line × gene Chronos matrix
  - Model.csv (~922 KB) — cell-line metadata (ModelID, lineage, primary_disease, ...)

Outputs (in --out directory):
  - summary.json        — decision-grade scalars (n, median, percentiles, fractions, shape)
  - figure_waterfall.svg — ranked per-cell-line Chronos waterfall
  - figure_histogram_kde.svg — density histogram with KDE overlay
  - plot_data.parquet   — long-format per-cell-line data for re-rendering
  - manifest.yaml       — provenance + cell-line list + input md5s

Iter-2 implementation: reads from local cache or S3. AWS-credential-aware. Graceful
degradation when files unreachable (emits _live_read_error in summary.json).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

# === Default paths ===
DEFAULT_CATALOG_REPO = Path(
    os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
)
DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
DEPMAP_S3_PREFIX = "s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1"
DEPMAP_LOCAL_FALLBACK_DIRS = [
    Path("/home/sagemaker-user/depmap-26q1"),
    Path("/data/depmap/26q1"),
    Path.home() / "depmap-26q1",
]


def load_depmap_files(release_pin: str, target_symbol: str) -> tuple[dict, dict, list]:
    """Load CRISPRGeneEffect for the target gene + Model.csv.

    Returns:
        chronos_by_model_id: {model_id (cell line) → chronos_score (float)}
        model_metadata_by_id: {model_id → metadata_dict}
        load_errors: list of structured error dicts (empty if successful)

    Strategy:
      1. Check local fallback paths first (DEPMAP_LOCAL_FALLBACK_DIRS).
      2. If not found, attempt S3 read via boto3 (requires AWS creds).
      3. If S3 fails, return load_errors with structured reason.
    """
    import pandas as pd

    crispr_path = None
    model_path = None
    load_errors = []

    # Local cache discovery
    for fallback_dir in DEPMAP_LOCAL_FALLBACK_DIRS:
        candidate_crispr = fallback_dir / "CRISPRGeneEffect.csv"
        candidate_model = fallback_dir / "Model.csv"
        if candidate_crispr.exists() and candidate_model.exists():
            crispr_path = candidate_crispr
            model_path = candidate_model
            click.echo(f"  Using local DepMap cache at {fallback_dir}", err=True)
            break

    # Model.csv: prefer local-cache Model.csv when a local-cache CRISPR was
    # found (test-fixture consistency); otherwise use the shared cached S3 loader.
    if model_path is not None:
        model_df = pd.read_csv(model_path)
    else:
        from methods.depmap_common import load_model_csv
        try:
            model_df = load_model_csv(release_pin)
        except FileNotFoundError as e:
            load_errors.append({
                "_live_read_error": "s3_read_failed",
                "detail": str(e),
                "remediation": "Ensure AWS credentials are set and bucket onc-compbio is accessible.",
            })
            return {}, {}, load_errors

    # === TIER-2 PATH: try parquet derived product first (100-500× faster than CSV) ===
    # get_chronos_column reads only ModelID + target column from the parquet at
    # s3://onc-compbio/data-catalog/derived/depmap-26q1-parquet-v1/CRISPRGeneEffect.parquet
    # with local-disk cache under ~/.cache/framework-depmap-26q1-parquet/. Falls
    # through to the CSV path only if the parquet is unreachable AND no local CSV.
    if crispr_path is None:
        try:
            from methods.depmap_common.parquet import get_chronos_column
            target_df = get_chronos_column(target_symbol, release_pin)
            if target_df is not None:
                # Identify target column (should be "SYMBOL (entrez_id)" format) + ID column
                target_col = next((c for c in target_df.columns if c != "ModelID"), None)
                if target_col:
                    chronos_by_model_id = {}
                    for _, row in target_df.iterrows():
                        val = row[target_col]
                        if pd.notna(val):
                            chronos_by_model_id[row["ModelID"]] = float(val)
                    model_id_col = "ModelID" if "ModelID" in model_df.columns else model_df.columns[0]
                    model_metadata_by_id = {row[model_id_col]: row.to_dict()
                                             for _, row in model_df.iterrows()}
                    return chronos_by_model_id, model_metadata_by_id, load_errors
            # target absent from parquet → fall through to CSV path (or emit error below)
        except (FileNotFoundError, ImportError):
            # Parquet not available (not precomputed, or pyarrow not installed) → CSV fallback
            pass

    # === LEGACY CSV PATH (fallback) ===
    if crispr_path is None:
        try:
            import boto3
            from botocore.exceptions import ClientError, NoCredentialsError
            s3 = boto3.client("s3")
            bucket = "onc-compbio"
            crispr_key = "data-catalog/sources/depmap-consortium/dmc-26q1/CRISPRGeneEffect.csv"
            click.echo(f"  Fetching s3://{bucket}/{crispr_key}", err=True)
            crispr_obj = s3.get_object(Bucket=bucket, Key=crispr_key)
            crispr_df = pd.read_csv(BytesIO(crispr_obj["Body"].read()))
        except (ImportError,) as e:
            load_errors.append({
                "_live_read_error": "boto3_not_available",
                "detail": str(e),
                "remediation": "Install boto3 or provide local DepMap cache at one of "
                               f"{[str(d) for d in DEPMAP_LOCAL_FALLBACK_DIRS]}",
            })
            return {}, {}, load_errors
        except Exception as e:
            load_errors.append({
                "_live_read_error": "s3_read_failed",
                "detail": str(e),
                "remediation": f"Ensure AWS credentials are set and bucket {DEPMAP_S3_PREFIX} is accessible.",
            })
            return {}, {}, load_errors
    else:
        # Local read
        crispr_df = pd.read_csv(crispr_path)

    # Extract target column from CRISPRGeneEffect
    target_columns = [c for c in crispr_df.columns
                      if c == target_symbol or c.split(" ")[0] == target_symbol]
    if not target_columns:
        load_errors.append({
            "_live_read_error": "target_not_in_crispr_panel",
            "detail": f"Target {target_symbol} not found as a column in CRISPRGeneEffect.csv",
            "remediation": "Confirm HGNC symbol spelling; check whether target was screened in 26Q1.",
        })
        return {}, {}, load_errors

    target_col = target_columns[0]
    cell_line_col = crispr_df.columns[0]

    chronos_by_model_id = {}
    for _, row in crispr_df[[cell_line_col, target_col]].iterrows():
        if pd.notna(row[target_col]):
            chronos_by_model_id[row[cell_line_col]] = float(row[target_col])

    model_id_col = "ModelID" if "ModelID" in model_df.columns else model_df.columns[0]
    model_metadata_by_id = {row[model_id_col]: row.to_dict() for _, row in model_df.iterrows()}

    return chronos_by_model_id, model_metadata_by_id, load_errors


def compute_summary_stats(chronos_by_model: dict, model_metadata: dict,
                             strong_threshold: float = -1.0,
                             moderate_threshold: float = -0.5,
                             pan_essential_fraction: float = 0.85,
                             selective_min: float = 0.05,
                             selective_max: float = 0.60) -> dict:
    """Compute the decision-grade summary scalars defined in the card_spec."""
    import numpy as np
    import pandas as pd

    if not chronos_by_model:
        return {"_no_data": True}

    scores = np.array(list(chronos_by_model.values()))
    n = len(scores)

    # Core distribution stats
    summary = {
        "n_cell_lines_evaluated": int(n),
        "median_chronos_panel": float(np.median(scores)),
        "p25_chronos_panel": float(np.percentile(scores, 25)),
        "p75_chronos_panel": float(np.percentile(scores, 75)),
        "p5_chronos_panel": float(np.percentile(scores, 5)),
        "p95_chronos_panel": float(np.percentile(scores, 95)),
        "chronos_iqr": float(np.percentile(scores, 75) - np.percentile(scores, 25)),
    }

    # Threshold-based fractions
    summary["fraction_strongly_dependent"] = float(np.mean(scores <= strong_threshold))
    summary["fraction_moderately_dependent"] = float(
        np.mean((scores > strong_threshold) & (scores <= moderate_threshold))
    )
    summary["fraction_non_essential"] = float(np.mean(scores > moderate_threshold))

    # Distribution shape classification
    frac_strong = summary["fraction_strongly_dependent"]
    if frac_strong >= pan_essential_fraction:
        shape = "pan_essential"
    elif selective_min <= frac_strong <= selective_max:
        # bimodal? — check skewness / detect tail separation
        # Simple heuristic: distribution is bimodal if there's a clear tail
        # at frac_strongly_dependent && median_panel > -0.5 (i.e., most cells aren't dependent)
        if summary["median_chronos_panel"] > -0.5:
            shape = "bimodal_selective"
        else:
            shape = "shifted_dependent"
    elif summary["median_chronos_panel"] <= -0.5 and frac_strong > selective_max:
        shape = "shifted_dependent"
    else:
        shape = "non_essential"
    summary["distribution_shape"] = shape

    # Pan-essentiality score (continuous version of fraction_strongly_dependent)
    summary["pan_essential_score"] = frac_strong

    # Selectivity index: ratio of dependent-tail magnitude vs background
    # Tail = mean of scores ≤ strong_threshold; background = mean of scores > moderate_threshold
    tail_scores = scores[scores <= strong_threshold]
    background_scores = scores[scores > moderate_threshold]
    if len(tail_scores) > 0 and len(background_scores) > 0:
        tail_magnitude = abs(np.mean(tail_scores))
        background_magnitude = max(abs(np.mean(background_scores)), 0.01)
        summary["selectivity_index"] = float(tail_magnitude / (tail_magnitude + background_magnitude))
    else:
        summary["selectivity_index"] = 0.0

    # Top dependent lineages (with per-lineage stats)
    # Build cell_line → lineage map
    lineage_records = []
    for model_id, chronos in chronos_by_model.items():
        meta = model_metadata.get(model_id, {})
        # DepMap Model.csv uses OncotreeLineage typically; fall back to other columns
        lineage = (meta.get("OncotreeLineage")
                   or meta.get("lineage")
                   or meta.get("PrimaryDisease")
                   or "unknown")
        lineage_records.append({"model_id": model_id, "lineage": lineage, "chronos": chronos})

    lineage_df = pd.DataFrame(lineage_records)
    # Per-lineage stats: median chronos, fraction strongly dependent, n
    top_lineages = []
    for lineage_name, subset in lineage_df.groupby("lineage"):
        if len(subset) < 5:   # require min 5 cell lines per lineage for stable estimate
            continue
        frac_strong_in_lineage = float((subset["chronos"] <= strong_threshold).mean())
        top_lineages.append({
            "lineage": lineage_name,
            "n_in_lineage": int(len(subset)),
            "fraction_strongly_dependent": frac_strong_in_lineage,
            "median_chronos": float(subset["chronos"].median()),
            "fraction_of_dependent_tail": float(
                (subset["chronos"] <= strong_threshold).sum() / max(1, (lineage_df["chronos"] <= strong_threshold).sum())
            ),
        })
    # Sort by fraction_strongly_dependent descending, take top 5
    top_lineages.sort(key=lambda x: x["fraction_strongly_dependent"], reverse=True)
    summary["top_dependent_lineages"] = top_lineages[:5]

    # === dependency_class — DepMap-convention descriptive categorical ===
    # Maps the distribution shape + dependent-fraction to one of the four classes that
    # the Tier-2 interpretation-rules consume. Vocabulary declared in the card_spec's
    # outputs.summary_fields_vocabulary.dependency_class. The mapping mirrors DepMap's
    # published portal logic.
    summary["dependency_class"] = _classify_dependency(
        fraction_strongly_dependent=frac_strong,
        median_chronos_panel=summary["median_chronos_panel"],
        distribution_shape=shape,
        top_dependent_lineages=summary["top_dependent_lineages"],
        n_cell_lines_evaluated=summary["n_cell_lines_evaluated"],
        pan_essential_fraction=pan_essential_fraction,
        selective_min=selective_min,
        selective_max=selective_max,
    )

    return summary


# --- DepMap-power admissibility guard (2026-07-17) --------------------------
# A pooled pan-cancer `non_dependent` call (< 5% of ~1500 lines strongly dependent)
# is only a TRUSTED NEGATIVE if no well-sampled lineage is concentrated-dependent.
# When a lineage IS concentrated-dependent but its cell lines are too few to lift the
# POOLED fraction above the floor (the EGFR-in-lung / FLT3-mut-AML / IDH1-mut case:
# a handful of relevant lines diluted across ~1500), the pooled `non_dependent` is
# UNDERPOWERED, not a negative. We emit a distinct class so the gate treats it as
# `insufficient` (measured-vs-null discipline) rather than firing a false-negative veto.
LINEAGE_CONCENTRATED_DEP_FRACTION = 0.30   # a lineage with >=30% strongly-dependent lines...
LINEAGE_MIN_N_FOR_ADMISSIBILITY = 5        # ...and >=5 lines (already the top_lineages floor)
# Panel-coverage floor for a TRUSTWORTHY pan-essential VETO (H fix, 2026-07-20). DepMap
# Chronos panels are typically ~1000-1500 lines; a `common_essential` call on a tiny panel
# is an underpowered artifact, not a trusted pan-essential. Below this floor, a >=85%
# strongly-dependent fraction routes to `common_essential_underpowered` → insufficient (NOT
# the pan-essential veto). Conservative: 300 only trips genuinely small panels.
PAN_ESSENTIAL_MIN_PANEL_N = 300


def _classify_dependency(fraction_strongly_dependent: float,
                          median_chronos_panel: float,
                          distribution_shape: str,
                          top_dependent_lineages: list | None = None,
                          n_cell_lines_evaluated: int | None = None,
                          pan_essential_fraction: float = 0.85,
                          selective_min: float = 0.05,
                          selective_max: float = 0.60) -> str:
    """Map summary stats to a DepMap-convention dependency_class categorical.

    Returns one of: common_essential | common_essential_underpowered |
                    strongly_selective | broadly_dependent | non_dependent |
                    non_dependent_underpowered | data_unavailable

    The vocabulary matches target-contracts/cards/pan-cancer-crispr-dependency-distribution
    .card.yaml's outputs.summary_fields_vocabulary.dependency_class. Tier-2 rules
    in interpretation-rules/intracellular-intrinsic.rules.yaml consume these labels.

    ADMISSIBILITY GUARDS at BOTH veto-producing ends (measured-vs-null discipline —
    an underpowered panel is a coverage gap, NOT a trusted negative/positive, so it must
    NOT force a gate VETO):
      - `non_dependent_underpowered` (2026-07-17): below-floor pooled call contradicted
        by a concentrated-dependent well-sampled lineage (EGFR/FLT3/IDH1 under-sampled).
      - `common_essential_underpowered` (H fix 2026-07-20): a >=85% pan-essential call on
        a panel below PAN_ESSENTIAL_MIN_PANEL_N — a tiny-panel artifact, not a trusted
        pan-essential. Routes to insufficient instead of the pan-essential veto.
    """
    if fraction_strongly_dependent >= pan_essential_fraction:
        if (n_cell_lines_evaluated is not None
                and n_cell_lines_evaluated < PAN_ESSENTIAL_MIN_PANEL_N):
            return "common_essential_underpowered"
        return "common_essential"
    if fraction_strongly_dependent < selective_min:
        # Below the pooled floor. Admissibility check: is there a well-sampled lineage
        # that IS concentrated-dependent? If so the pooled negative is underpowered
        # (diluted), not trusted — flag it so the gate treats it as insufficient.
        for lin in (top_dependent_lineages or []):
            if (lin.get("n_in_lineage", 0) >= LINEAGE_MIN_N_FOR_ADMISSIBILITY
                    and lin.get("fraction_strongly_dependent", 0.0)
                    >= LINEAGE_CONCENTRATED_DEP_FRACTION):
                return "non_dependent_underpowered"
        return "non_dependent"
    if distribution_shape == "bimodal_selective":
        return "strongly_selective"
    if (selective_min <= fraction_strongly_dependent <= selective_max
            and median_chronos_panel <= -0.5):
        return "broadly_dependent"
    if distribution_shape == "shifted_dependent":
        return "broadly_dependent"
    # Fallback: in-range but doesn't fit a clean shape (low confidence)
    return "broadly_dependent"


def emit_waterfall_plot(chronos_by_model: dict, model_metadata: dict,
                          target_symbol: str, summary: dict,
                          out_path: Path,
                          contracts_root: Path) -> None:
    """Emit the ranked waterfall figure to {out_path}/figure_waterfall.svg.

    Per-cell-line Chronos sorted ascending, lineage-colored, reference lines at
    -1.0 (strong), -0.5 (moderate), 0 (no dependency)."""
    import matplotlib.pyplot as plt
    import numpy as np

    # Load style
    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    from takeda_palette import (  # type: ignore
        get_lineage_color, REFLINE_NEUTRAL, REFLINE_KILLER, REFLINE_NOMINAL,
        FIGSIZE_DOUBLE_COLUMN, CHRONOS_STRONG_DEPENDENCY,
    )

    # Build sorted list
    rows = []
    for mid, c in chronos_by_model.items():
        meta = model_metadata.get(mid, {})
        lineage = (meta.get("OncotreeLineage") or meta.get("lineage")
                   or meta.get("PrimaryDisease") or "unknown")
        rows.append((mid, c, lineage))
    rows.sort(key=lambda r: r[1])

    chronos_arr = np.array([r[1] for r in rows])
    lineage_arr = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=FIGSIZE_DOUBLE_COLUMN)

    # Identify top-5 lineages (most cells in dependent tail) for distinct colors
    from collections import Counter
    dependent_tail_lineages = [r[2] for r in rows if r[1] <= CHRONOS_STRONG_DEPENDENCY]
    top_lineages_in_tail = [name for name, _ in Counter(dependent_tail_lineages).most_common(5)]

    colors = [get_lineage_color(lg) if lg in top_lineages_in_tail else "#CCCCCC"
              for lg in lineage_arr]

    x = np.arange(len(rows))
    ax.bar(x, chronos_arr, width=1.0, color=colors, edgecolor="none")

    # Reference lines
    ax.axhline(y=0.0, **REFLINE_NOMINAL, zorder=1)
    ax.axhline(y=-0.5, **REFLINE_NEUTRAL, zorder=1)
    ax.axhline(y=CHRONOS_STRONG_DEPENDENCY, **REFLINE_KILLER, zorder=1)

    # Threshold labels — placed in axes-coordinate space at the LEFT edge to avoid
    # overlap with both (a) the bars (which extend from x=0 to x=len(rows)) and
    # (b) the lineage legend (which sits in the lower-right corner). White background
    # box keeps the label readable when reference lines pass through them.
    _label_bbox = dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.5)
    ax.text(0.005, 0.04, "no dependency", fontsize=8, color="#666666",
             ha="left", va="bottom", transform=ax.get_yaxis_transform(),
             bbox=_label_bbox, zorder=4)
    ax.text(0.005, -0.5, "moderate", fontsize=8, color="#666666",
             ha="left", va="bottom", transform=ax.get_yaxis_transform(),
             bbox=_label_bbox, zorder=4)
    ax.text(0.005, CHRONOS_STRONG_DEPENDENCY, "strong", fontsize=8, color="#B22222",
             ha="left", va="bottom", transform=ax.get_yaxis_transform(),
             bbox=_label_bbox, zorder=4)

    # Labels + title
    ax.set_xlabel("Cell line (sorted by dependency)")
    ax.set_ylabel("Chronos score (more dependent ↓)")
    n = summary.get("n_cell_lines_evaluated", "?")
    shape = summary.get("distribution_shape", "?").upper().replace("_", " ")
    ax.set_title(f"{target_symbol} pan-cancer Chronos distribution  (n={n}, {shape})")

    # Lineage legend (top dependent lineages)
    if top_lineages_in_tail:
        from matplotlib.patches import Patch
        legend_handles = [Patch(color=get_lineage_color(lg), label=lg.replace("_", " ").title())
                          for lg in top_lineages_in_tail]
        legend_handles.append(Patch(color="#CCCCCC", label="other lineages"))
        ax.legend(handles=legend_handles, loc="lower right", framealpha=0.9, fontsize=8)

    ax.set_xlim(-0.5, len(rows) - 0.5)
    ax.grid(axis="y")

    fig.savefig(out_path / "figure_waterfall.svg", bbox_inches="tight")
    plt.close(fig)


def emit_histogram_kde_plot(chronos_by_model: dict, target_symbol: str,
                               summary: dict, out_path: Path,
                               contracts_root: Path) -> None:
    """Emit the density histogram + KDE figure to {out_path}/figure_histogram_kde.svg."""
    import matplotlib.pyplot as plt
    import numpy as np

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    from takeda_palette import (  # type: ignore
        REFLINE_NEUTRAL, REFLINE_KILLER, REFLINE_NOMINAL,
        FIGSIZE_SINGLE_COLUMN_TALL, CHRONOS_STRONG_DEPENDENCY,
    )

    try:
        import seaborn as sns
        have_seaborn = True
    except ImportError:
        have_seaborn = False

    scores = np.array(list(chronos_by_model.values()))
    fig, ax = plt.subplots(figsize=FIGSIZE_SINGLE_COLUMN_TALL)

    # Histogram with KDE overlay (seaborn if available; matplotlib fallback)
    if have_seaborn:
        sns.histplot(scores, kde=True, ax=ax, color="#0072B2",
                     edgecolor="white", linewidth=0.5, alpha=0.7,
                     stat="density", bins=40)
    else:
        ax.hist(scores, bins=40, density=True, color="#0072B2",
                edgecolor="white", linewidth=0.5, alpha=0.7)

    # Reference lines
    ax.axvline(x=0.0, **REFLINE_NOMINAL, zorder=2)
    ax.axvline(x=-0.5, **REFLINE_NEUTRAL, zorder=2)
    ax.axvline(x=CHRONOS_STRONG_DEPENDENCY, **REFLINE_KILLER, zorder=2)

    # Shaded region: strongly dependent
    ax.axvspan(scores.min() - 0.1, CHRONOS_STRONG_DEPENDENCY,
               alpha=0.10, color="#B22222", zorder=0)

    # Annotations: median + IQR + fraction_strongly_dependent
    median = summary.get("median_chronos_panel", float(np.median(scores)))
    frac_strong = summary.get("fraction_strongly_dependent", 0)
    text = f"median = {median:.2f}\nIQR = {summary.get('chronos_iqr', 0):.2f}\nfrac. strongly dep. = {frac_strong:.1%}"
    ax.text(0.05, 0.95, text, transform=ax.transAxes, fontsize=8,
            verticalalignment="top", bbox=dict(boxstyle="round,pad=0.4",
                                                facecolor="white", edgecolor="#CCCCCC", alpha=0.9))

    n = summary.get("n_cell_lines_evaluated", "?")
    shape = summary.get("distribution_shape", "?").upper().replace("_", " ")
    ax.set_title(f"{target_symbol} Chronos density  (n={n}, {shape})")
    ax.set_xlabel("Chronos score")
    ax.set_ylabel("Density")

    fig.savefig(out_path / "figure_histogram_kde.svg", bbox_inches="tight")
    plt.close(fig)


def emit_plotly_specs(chronos_by_model: dict, model_metadata: dict,
                      target_symbol: str, summary: dict, out_path: Path,
                      contracts_root: Path) -> list:
    """Emit interactive Plotly figure specs SIBLING to the matplotlib SVGs (dynamic-dashboard
    Phase A). Built from the SAME in-memory chronos_by_model the SVGs use — so the interactive
    chart can NOT drift from the static figure or the plot_data.parquet (one data source, three
    renderings). Writes:
      - figure_waterfall.plotly.json      (ranked per-cell-line bars, lineage-colored, reflines)
      - figure_histogram_kde.plotly.json  (density histogram, reflines + strong-dependency shade)
    Each is fig.to_json() (a self-describing Plotly spec the HTML renderer embeds via Plotly.newPlot;
    NO kaleido / static export). Returns a list of {id, path, type} descriptors for the manifest.
    Failures are absorbed (the SVG path is the guaranteed artifact); Plotly is a best-effort add.
    """
    try:
        import numpy as np
        import plotly.graph_objects as go
        sys.path.insert(0, str(contracts_root / "plot_styles"))
        from takeda_palette import get_lineage_color, CHRONOS_STRONG_DEPENDENCY  # type: ignore
    except Exception as e:  # noqa: BLE001 — Plotly optional; never block the SVG artifacts
        print(f"[chronos-distribution] plotly spec emission skipped: {e}", file=sys.stderr)
        return []

    # matplotlib linestyle → Plotly dash; reflines mirror the SVGs exactly (0 / -0.5 / -1.0).
    STRONG = CHRONOS_STRONG_DEPENDENCY
    reflines = [(0.0, "#999999", "solid", "no dependency"),
                (-0.5, "#666666", "dash", "moderate"),
                (STRONG, "#B22222", "dash", "strong")]
    written = []

    # --- Waterfall: sorted bars, top-5 dependent-tail lineages colored, else grey (mirrors SVG) ---
    try:
        rows = sorted(
            ((mid, c, (model_metadata.get(mid, {}).get("OncotreeLineage")
                       or model_metadata.get(mid, {}).get("lineage")
                       or model_metadata.get(mid, {}).get("PrimaryDisease") or "unknown"))
             for mid, c in chronos_by_model.items()),
            key=lambda r: r[1])
        from collections import Counter
        tail = [lg for _, c, lg in rows if c <= STRONG]
        top_lineages = [n for n, _ in Counter(tail).most_common(5)]
        names = [model_metadata.get(mid, {}).get("CellLineName", mid) for mid, _, _ in rows]
        vals = [c for _, c, _ in rows]
        colors = [get_lineage_color(lg) if lg in top_lineages else "#CCCCCC" for _, _, lg in rows]
        lineages = [lg for _, _, lg in rows]
        fig = go.Figure(go.Bar(
            x=list(range(len(rows))), y=vals, marker_color=colors,
            customdata=list(zip(names, lineages)),
            hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>Chronos %{y:.2f}<extra></extra>"))
        for yv, col, dash, lab in reflines:
            fig.add_hline(y=yv, line=dict(color=col, dash=dash, width=1.5),
                          annotation_text=lab, annotation_position="top left")
        n = summary.get("n_cell_lines_evaluated", "?")
        shape = str(summary.get("distribution_shape", "?")).upper().replace("_", " ")
        fig.update_layout(
            title=f"{target_symbol} pan-cancer Chronos distribution (n={n}, {shape})",
            xaxis_title="Cell line (sorted by dependency)",
            yaxis_title="Chronos score (more dependent ↓)",
            template="plotly_white", showlegend=False, bargap=0, margin=dict(l=60, r=20, t=50, b=50))
        (out_path / "figure_waterfall.plotly.json").write_text(fig.to_json())
        written.append({"id": "waterfall", "path": "figure_waterfall.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[chronos-distribution] waterfall plotly skipped: {e}", file=sys.stderr)

    # --- Histogram (density): mirrors the SVG (blue bars + reflines + strong-dep shade) ---
    try:
        scores = np.array(list(chronos_by_model.values()), dtype=float)
        fig = go.Figure(go.Histogram(
            x=scores, histnorm="probability density", nbinsx=40,
            marker_color="#0072B2", marker_line_color="white", marker_line_width=0.5, opacity=0.75,
            hovertemplate="Chronos %{x:.2f}<br>density %{y:.3f}<extra></extra>"))
        fig.add_vrect(x0=float(scores.min()) - 0.1, x1=STRONG, fillcolor="#B22222",
                      opacity=0.10, line_width=0)
        for xv, col, dash, lab in reflines:
            fig.add_vline(x=xv, line=dict(color=col, dash=dash, width=1.5),
                          annotation_text=lab, annotation_position="top")
        n = summary.get("n_cell_lines_evaluated", "?")
        med = summary.get("median_chronos_panel", float(np.median(scores)))
        fig.update_layout(
            title=f"{target_symbol} Chronos density (n={n}, median {med:.2f})",
            xaxis_title="Chronos score", yaxis_title="Density",
            template="plotly_white", showlegend=False, margin=dict(l=60, r=20, t=50, b=50))
        (out_path / "figure_histogram_kde.plotly.json").write_text(fig.to_json())
        written.append({"id": "histogram_kde", "path": "figure_histogram_kde.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[chronos-distribution] histogram plotly skipped: {e}", file=sys.stderr)

    return written


def emit_plot_data(chronos_by_model: dict, model_metadata: dict,
                     strong_threshold: float, out_path: Path) -> None:
    """Emit plot_data.parquet — one row per cell line."""
    import pandas as pd

    rows = []
    sorted_items = sorted(chronos_by_model.items(), key=lambda x: x[1])
    for rank, (mid, c) in enumerate(sorted_items, start=1):
        meta = model_metadata.get(mid, {})
        rows.append({
            "cell_line_id": mid,
            "cell_line_name": meta.get("CellLineName", meta.get("ModelID", mid)),
            "chronos_score": float(c),
            "lineage": (meta.get("OncotreeLineage")
                        or meta.get("lineage")
                        or meta.get("PrimaryDisease") or "unknown"),
            "sub_lineage": meta.get("OncotreeSubtype") or meta.get("Subtype") or "",
            "primary_disease": meta.get("PrimaryDisease") or meta.get("primary_disease") or "",
            "is_strongly_dependent": bool(c <= strong_threshold),
            "rank_in_panel": rank,
        })

    df = pd.DataFrame(rows)
    # Quartile
    df["quartile"] = pd.qcut(df["chronos_score"], q=4,
                              labels=["Q1_most_dependent", "Q2", "Q3", "Q4_least_dependent"]).astype(str)

    df.to_parquet(out_path / "plot_data.parquet", index=False)


def emit_manifest(target_symbol: str, release_pin: str, summary: dict,
                    chronos_by_model: dict, out_path: Path,
                    load_errors: list, plotly_specs: Optional[list] = None) -> None:
    """Emit manifest.yaml — provenance for this card emission."""
    import yaml

    cell_line_ids = sorted(chronos_by_model.keys())
    manifest = {
        "method": "depmap-chronos-distribution",
        "method_version": METHOD_VERSION,
        "target": target_symbol,
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "input_manifest": "depmap-consortium-26q1",
        "input_files_consumed": ["CRISPRGeneEffect.csv", "Model.csv"],
        "n_cell_lines_evaluated": summary.get("n_cell_lines_evaluated", 0),
        "cell_lines_list_sample": cell_line_ids[:10] if cell_line_ids else [],
        "cell_lines_total_count": len(cell_line_ids),
        "load_errors": load_errors,
        "plotly_figures": plotly_specs or [],   # interactive figure specs (Phase A); [] if unavailable
    }
    with (out_path / "manifest.yaml").open("w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)


@click.command()
@click.option("--target", required=True, help="HGNC symbol (e.g., KRAS, MYC, BCL2).")
@click.option("--release-pin", default="26q1", help="DepMap release pin.")
@click.option("--strong-dependency-threshold", type=float, default=-1.0,
              help="Chronos threshold for 'strongly dependent' classification.")
@click.option("--moderate-dependency-threshold", type=float, default=-0.5)
@click.option("--catalog-repo", type=click.Path(file_okay=False, path_type=Path),
              default=DEFAULT_CATALOG_REPO)
@click.option("--contracts-root", type=click.Path(file_okay=False, path_type=Path),
              default=DEFAULT_TARGET_CONTRACTS)
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Output directory; summary.json + figures + plot_data land here.")
@click.option("--dry-run", is_flag=True, help="Print the plan; don't actually load DepMap.")
def main(target: str, release_pin: str, strong_dependency_threshold: float,
         moderate_dependency_threshold: float, catalog_repo: Path,
         contracts_root: Path, out: Path, dry_run: bool) -> int:
    """Pan-cancer Chronos distribution analysis for a target."""
    out.mkdir(parents=True, exist_ok=True)

    click.echo(f"=== depmap-chronos-distribution ===")
    click.echo(f"  target:        {target}")
    click.echo(f"  release_pin:   {release_pin}")
    click.echo(f"  strong_thresh: {strong_dependency_threshold}")
    click.echo(f"  out:           {out}")

    if dry_run:
        click.echo("(--dry-run: skipping actual analysis)")
        return 0

    # 1. Load DepMap data
    chronos_by_model, model_metadata, load_errors = load_depmap_files(release_pin, target)

    if load_errors:
        click.echo(f"  LOAD ERRORS: {len(load_errors)}", err=True)
        for e in load_errors:
            click.echo(f"    {e}", err=True)
        # Emit a structured-error summary so callers can detect failure
        with (out / "summary.json").open("w") as f:
            json.dump({"_live_read_error": True, "errors": load_errors,
                       "target": target, "release_pin": release_pin}, f, indent=2)
        emit_manifest(target, release_pin, {}, {}, out, load_errors)
        return 2

    if not chronos_by_model:
        click.echo(f"  No Chronos data for {target} in {release_pin}", err=True)
        with (out / "summary.json").open("w") as f:
            json.dump({"_no_data": True, "target": target}, f)
        return 2

    # 2. Compute summary
    summary = compute_summary_stats(
        chronos_by_model, model_metadata,
        strong_threshold=strong_dependency_threshold,
        moderate_threshold=moderate_dependency_threshold,
    )

    # 3. Emit summary.json
    with (out / "summary.json").open("w") as f:
        json.dump(summary, f, indent=2, default=str)

    # 4. Emit figures (matplotlib SVG — the guaranteed artifact) + interactive Plotly specs (siblings)
    emit_waterfall_plot(chronos_by_model, model_metadata, target, summary, out, contracts_root)
    emit_histogram_kde_plot(chronos_by_model, target, summary, out, contracts_root)
    plotly_specs = emit_plotly_specs(chronos_by_model, model_metadata, target, summary, out, contracts_root)

    # 5. Emit plot_data.parquet
    emit_plot_data(chronos_by_model, model_metadata, strong_dependency_threshold, out)

    # 6. Emit manifest.yaml
    emit_manifest(target, release_pin, summary, chronos_by_model, out, load_errors, plotly_specs)

    click.echo(f"  → summary.json:   {out / 'summary.json'}")
    click.echo(f"  → waterfall:      {out / 'figure_waterfall.svg'}")
    click.echo(f"  → histogram_kde:  {out / 'figure_histogram_kde.svg'}")
    click.echo(f"  → plotly specs:   {len(plotly_specs)} ({', '.join(s['id'] for s in plotly_specs)})")
    click.echo(f"  → plot_data:      {out / 'plot_data.parquet'}")
    click.echo(f"  → manifest:       {out / 'manifest.yaml'}")
    click.echo(f"  distribution_shape: {summary.get('distribution_shape')}")
    click.echo(f"  fraction_strongly_dependent: {summary.get('fraction_strongly_dependent'):.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
