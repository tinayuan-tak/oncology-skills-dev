#!/usr/bin/env python3
"""depmap-demeter-distribution CLI — pan-cancer RNAi DEMETER2 distribution analysis.

Consumes DepMap 26Q1 RNAi D2_combined_gene_dep_scores.csv + sample_info.csv +
Model.csv (for ModelID bridge), computes per-target dependency distribution stats
across the RNAi panel (~712 cell lines), emits summary.json + two SVG figures
(waterfall + histogram-KDE) + plot_data.parquet for the
pan-cancer-rnai-dependency-distribution card.

Key differences from depmap_chronos_distribution sibling:
  - Matrix shape is TRANSPOSED: D2_combined is gene-rows x cell-line-columns
    (vs CRISPRGeneEffect: cell-line-rows x gene-columns).
  - Gene row index format is "SYMBOL (entrez_id)" — parse with regex.
  - Cell line columns use legacy CCLE_ID (e.g. "127399_SOFT_TISSUE") — bridge to
    ModelID via sample_info.csv + Model.csv (CCLEName column).
  - DEMETER2 thresholds: strong = -0.5, moderate = -0.25 (different from Chronos).

Inputs (resolved from catalog manifest `depmap-consortium-26q1-rnai`):
  - D2_combined_gene_dep_scores.csv (~161 MB) — gene x cell-line DEMETER2 matrix
  - sample_info.csv (~76 KB) — CCLE_ID + disease + screen-membership flags

Plus the CRISPR-side Model.csv for the ModelID bridge:
  - dmc-26q1/Model.csv (~922 KB) — ModelID, CCLEName, OncotreeLineage

Graceful degradation: if any file unreachable, emit _live_read_error dict.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Optional

import click

from methods.catalog_query.read import bucket_prefix_for, s3_uri_for


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEFAULT_CATALOG_REPO = Path(
    os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
)
DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
RNAI_SOURCE_MANIFEST_ID = "depmap-consortium-26q1-rnai"
CRISPR_SOURCE_MANIFEST_ID = "depmap-consortium-26q1"
# Resolved from the data-catalog manifests (single source of truth). *_S3_PREFIX (s3://-form) feed
# echo/provenance; _RNAI_KEY_PREFIX (bucket-relative) builds the get_object read keys below.
RNAI_S3_PREFIX = s3_uri_for(RNAI_SOURCE_MANIFEST_ID).rstrip("/")
CRISPR_S3_PREFIX = s3_uri_for(CRISPR_SOURCE_MANIFEST_ID).rstrip("/")
_RNAI_KEY_PREFIX = bucket_prefix_for(RNAI_SOURCE_MANIFEST_ID)[1].rstrip("/")
RNAI_LOCAL_FALLBACK_DIRS = [
    Path("/home/sagemaker-user/depmap-26q1-rnai"),
    Path("/data/depmap/26q1-rnai"),
    Path.home() / "depmap-26q1-rnai",
]

# Gene-row label regex: "SYMBOL (entrez_id)" -> SYMBOL
_GENE_LABEL_RE = re.compile(r'^"?([A-Za-z0-9._-]+)\s*\(\d+\)"?$')


def _parse_gene_symbol(label: str) -> Optional[str]:
    """Extract HGNC symbol from a 'SYMBOL (entrez_id)' index label.

    Returns None if the label doesn't match the expected format.
    """
    if not isinstance(label, str):
        return None
    m = _GENE_LABEL_RE.match(label.strip())
    return m.group(1) if m else None


def load_rnai_files(release_pin: str, target_symbol: str) -> tuple[dict, dict, list, "Optional[pd.DataFrame]"]:
    """Load D2_combined_gene_dep_scores for target + sample_info + Model.csv.

    Returns:
        demeter_by_model_id: {model_id (ACH-XXXXXX) -> demeter_score (float)}
        model_metadata_by_id: {model_id -> metadata_dict (OncotreeLineage, etc.)}
        load_errors: list of structured error dicts (empty if successful)

    Strategy:
      1. Check local fallback paths first.
      2. If not found, attempt S3 read via boto3.
      3. Bridge CCLE_ID columns to ModelID via Model.csv's CCLEName column.
    """
    import pandas as pd

    load_errors = []
    rnai_path = None
    sample_info_path = None
    model_path = None

    # === 1. Local cache discovery ===
    for fallback_dir in RNAI_LOCAL_FALLBACK_DIRS:
        candidate_rnai = fallback_dir / "D2_combined_gene_dep_scores.csv"
        candidate_si = fallback_dir / "sample_info.csv"
        if candidate_rnai.exists() and candidate_si.exists():
            rnai_path = candidate_rnai
            sample_info_path = candidate_si
            click.echo(f"  Using local RNAi cache at {fallback_dir}", err=True)
            break
    # Model.csv lives in the CRISPR cache; check default-named dirs sibling to the rnai dir
    for fallback_dir in RNAI_LOCAL_FALLBACK_DIRS:
        sibling = fallback_dir.parent / fallback_dir.name.replace("-rnai", "")
        if (sibling / "Model.csv").exists():
            model_path = sibling / "Model.csv"
            break

    # === 2. S3 read for whichever isn't found locally ===
    rnai_df = None
    sample_info_df = None
    model_df = None
    try:
        import boto3

        s3 = boto3.client("s3")
        bucket = "onc-compbio"

        # === TIER-2 PATH: parquet derived product (filter pushdown by gene_symbol) ===
        target_row_dict = None
        if rnai_path is None:
            try:
                from methods.depmap_common.parquet import get_demeter_row

                target_row_dict = get_demeter_row(target_symbol, release_pin)
                # target_row_dict is {ccle_id: score} or None if target absent
            except (FileNotFoundError, ImportError):
                target_row_dict = None  # fall through to CSV

        if target_row_dict is not None:
            # Skip the rest of the CSV-parsing path; use the dict directly
            rnai_df = None
        elif rnai_path is None:
            rnai_key = f"{_RNAI_KEY_PREFIX}/D2_combined_gene_dep_scores.csv"
            click.echo(f"  Fetching s3://{bucket}/{rnai_key}", err=True)
            obj = s3.get_object(Bucket=bucket, Key=rnai_key)
            # Legacy CSV path: read 161 MB and filter by gene row-label
            rnai_df = pd.read_csv(BytesIO(obj["Body"].read()), index_col=0, na_values=["NA", ""])
        else:
            rnai_df = pd.read_csv(rnai_path, index_col=0, na_values=["NA", ""])

        if sample_info_path is None:
            si_key = f"{_RNAI_KEY_PREFIX}/sample_info.csv"
            click.echo(f"  Fetching s3://{bucket}/{si_key}", err=True)
            obj = s3.get_object(Bucket=bucket, Key=si_key)
            sample_info_df = pd.read_csv(BytesIO(obj["Body"].read()))
        else:
            sample_info_df = pd.read_csv(sample_info_path)

        if model_path is None:
            # Shared cached Model.csv loader — process-wide LRU
            from methods.depmap_common import load_model_csv

            model_df = load_model_csv(release_pin)
        else:
            model_df = pd.read_csv(model_path)
    except ImportError as e:
        load_errors.append(
            {
                "_live_read_error": "boto3_not_available",
                "detail": str(e),
                "remediation": f"Install boto3 or provide local RNAi cache at one of {[str(d) for d in RNAI_LOCAL_FALLBACK_DIRS]}",
            }
        )
        return {}, {}, load_errors, sample_info_df
    except Exception as e:
        load_errors.append(
            {
                "_live_read_error": "s3_read_failed",
                "detail": str(e),
                "remediation": f"Ensure AWS credentials are set and {RNAI_S3_PREFIX} is accessible.",
            }
        )
        return {}, {}, load_errors, sample_info_df

    # === 3. Extract target gene row ===
    # Parquet path already produced target_row_dict ({ccle_id: score}); CSV path
    # needs to search the DataFrame's index for the gene label.
    if target_row_dict is not None:
        target_row = target_row_dict
    else:
        target_row = None
        for idx_label in rnai_df.index:
            symbol = _parse_gene_symbol(idx_label)
            if symbol == target_symbol:
                target_row = rnai_df.loc[idx_label].to_dict()
                break
    if target_row is None:
        load_errors.append(
            {
                "_live_read_error": "target_not_in_rnai_panel",
                "detail": f"Target {target_symbol} not found in D2_combined_gene_dep_scores.csv (RNAi panel)",
                "remediation": "Confirm HGNC symbol spelling; check whether target was screened in Achilles/DRIVE/Marcotte RNAi panels.",
            }
        )
        return {}, {}, load_errors, sample_info_df

    # === 4. Bridge CCLE_ID columns -> ModelID via Model.csv's CCLEName ===
    # Model.csv columns: ModelID, CCLEName, OncotreeLineage, ...
    if "CCLEName" not in model_df.columns or "ModelID" not in model_df.columns:
        load_errors.append(
            {
                "_live_read_error": "model_csv_missing_bridge_columns",
                "detail": "Model.csv lacks CCLEName or ModelID columns required for CCLE_ID -> ModelID bridge",
                "remediation": "Verify Model.csv schema; the 26Q1 release should carry both columns.",
            }
        )
        return {}, {}, load_errors, sample_info_df

    ccle_to_model = dict(zip(model_df["CCLEName"], model_df["ModelID"]))
    model_metadata_by_id = {row["ModelID"]: row.to_dict() for _, row in model_df.iterrows()}

    # Walk each cell-line column; record demeter score keyed by ModelID
    demeter_by_model_id = {}
    n_unbridged = 0
    for ccle_id, score in target_row.items():
        if pd.isna(score):
            continue
        model_id = ccle_to_model.get(ccle_id)
        if model_id is None:
            n_unbridged += 1
            continue
        demeter_by_model_id[model_id] = float(score)

    if n_unbridged > 0:
        click.echo(
            f"  Note: {n_unbridged} RNAi cell lines could not be bridged to ModelID (CCLE_ID not in Model.csv)",
            err=True,
        )

    return demeter_by_model_id, model_metadata_by_id, load_errors, sample_info_df


def compute_summary_stats(
    demeter_by_model: dict,
    model_metadata: dict,
    sample_info_df=None,
    strong_threshold: float = -0.5,
    moderate_threshold: float = -0.25,
    pan_essential_fraction: float = 0.85,
    selective_min: float = 0.05,
    selective_max: float = 0.60,
) -> dict:
    """Compute decision-grade summary scalars for the RNAi card.

    Mirrors depmap_chronos_distribution.compute_summary_stats but on DEMETER2 scale.
    """
    import numpy as np
    import pandas as pd

    if not demeter_by_model:
        return {"_no_data": True}

    scores = np.array(list(demeter_by_model.values()))
    n = len(scores)

    summary = {
        "rnai_n_cell_lines_evaluated": int(n),
        "rnai_median_dep_score": float(np.median(scores)),
        "rnai_p25_dep_score": float(np.percentile(scores, 25)),
        "rnai_p75_dep_score": float(np.percentile(scores, 75)),
        "rnai_p5_dep_score": float(np.percentile(scores, 5)),
        "rnai_p95_dep_score": float(np.percentile(scores, 95)),
        "rnai_dep_score_iqr": float(np.percentile(scores, 75) - np.percentile(scores, 25)),
    }

    summary["rnai_fraction_strongly_dependent"] = float(np.mean(scores <= strong_threshold))
    summary["rnai_fraction_moderately_dependent"] = float(
        np.mean((scores > strong_threshold) & (scores <= moderate_threshold))
    )
    summary["rnai_fraction_non_dependent"] = float(np.mean(scores > moderate_threshold))

    frac_strong = summary["rnai_fraction_strongly_dependent"]
    median_panel = summary["rnai_median_dep_score"]
    if frac_strong >= pan_essential_fraction:
        shape = "pan_essential"
    elif selective_min <= frac_strong <= selective_max:
        # #3/#9 fix: require GENUINE bimodality (Sarle BC), NOT the median-proxy the CRISPR card
        # rejected. BC unavailable (n<4) → fall back to median-shift routing.
        bc = _bimodality_coefficient(scores)
        summary["rnai_bimodality_coefficient"] = bc
        if bc is not None and bc > BIMODALITY_COEFFICIENT_THRESHOLD:
            shape = "bimodal_selective"
        elif median_panel <= moderate_threshold:
            shape = "shifted_dependent"
        else:
            shape = "non_essential"
    elif median_panel <= moderate_threshold and frac_strong > selective_max:
        shape = "shifted_dependent"
    else:
        shape = "non_essential"
    summary["rnai_distribution_shape"] = shape
    summary["rnai_pan_essential_score"] = frac_strong

    # Selectivity index: tail magnitude / (tail + background)
    tail = scores[scores <= strong_threshold]
    bg = scores[scores > moderate_threshold]
    if len(tail) > 0 and len(bg) > 0:
        tail_mag = abs(np.mean(tail))
        bg_mag = max(abs(np.mean(bg)), 0.01)
        summary["rnai_selectivity_index"] = float(tail_mag / (tail_mag + bg_mag))
    else:
        summary["rnai_selectivity_index"] = 0.0

    # Top dependent lineages
    lineage_records = []
    for model_id, score in demeter_by_model.items():
        meta = model_metadata.get(model_id, {})
        lineage = meta.get("OncotreeLineage") or meta.get("lineage") or meta.get("PrimaryDisease") or "unknown"
        lineage_records.append({"model_id": model_id, "lineage": lineage, "score": score})

    lineage_df = pd.DataFrame(lineage_records)
    top_lineages = []
    for lineage_name, subset in lineage_df.groupby("lineage"):
        if len(subset) < 5:
            continue
        frac_strong_lin = float((subset["score"] <= strong_threshold).mean())
        tail_total = max(1, int((lineage_df["score"] <= strong_threshold).sum()))
        top_lineages.append(
            {
                "lineage": lineage_name,
                "n_in_lineage": int(len(subset)),
                "fraction_strongly_dependent": frac_strong_lin,
                "median_dep_score": float(subset["score"].median()),
                "fraction_of_dependent_tail": float((subset["score"] <= strong_threshold).sum() / tail_total),
            }
        )
    top_lineages.sort(key=lambda x: x["fraction_strongly_dependent"], reverse=True)
    summary["rnai_top_dependent_lineages"] = top_lineages[:5]

    # rnai_dependency_class — same vocabulary as CRISPR card's dependency_class
    summary["rnai_dependency_class"] = _classify_rnai_dependency(
        fraction_strongly_dependent=frac_strong,
        median_dep_score=median_panel,
        distribution_shape=shape,
        n_cell_lines_evaluated=summary["rnai_n_cell_lines_evaluated"],
        moderate_threshold=moderate_threshold,
        pan_essential_fraction=pan_essential_fraction,
        selective_min=selective_min,
        selective_max=selective_max,
    )

    # Screens contributing — derive from sample_info.csv flags if provided
    if sample_info_df is not None and "CCLE_ID" in sample_info_df.columns:
        # Bridge model_ids back to CCLE_IDs to count screen membership
        screens = {"Achilles": 0, "DRIVE": 0, "Marcotte": 0}
        # Build ModelID -> CCLE_ID map by inverting the bridge (use any model_id we have)
        model_to_ccle = {}
        for model_id, meta in model_metadata.items():
            if "CCLEName" in meta and meta["CCLEName"]:
                model_to_ccle[model_id] = meta["CCLEName"]
        si_indexed = sample_info_df.set_index("CCLE_ID")
        for model_id in demeter_by_model.keys():
            ccle = model_to_ccle.get(model_id)
            if ccle is None or ccle not in si_indexed.index:
                continue
            row = si_indexed.loc[ccle]
            if isinstance(row, pd.DataFrame):
                row = row.iloc[0]
            if bool(row.get("in_Achilles", False)):
                screens["Achilles"] += 1
            if bool(row.get("in_DRIVE", False)):
                screens["DRIVE"] += 1
            if bool(row.get("in_Marcotte", False)):
                screens["Marcotte"] += 1
        summary["rnai_screens_contributing"] = [
            {"screen": name, "n_lines": cnt} for name, cnt in screens.items() if cnt > 0
        ]
    else:
        summary["rnai_screens_contributing"] = []

    return summary


# Panel-coverage floor for a trustworthy RNAi pan-essential VETO (H fix, 2026-07-20).
# Mirrors the CRISPR sibling. DEMETER2 panels (~700 lines) are smaller than Chronos, so
# 300 still only trips genuinely underpowered panels.
RNAI_PAN_ESSENTIAL_MIN_PANEL_N = 300

# FINDING #3/#9 (2026-08-13 review): the RNAi shape used a median-proxy for "bimodal" (median >
# moderate → bimodal), the exact shortcut the CRISPR card rejected. Port CRISPR's Sarle bimodality
# coefficient so `bimodal_selective` requires a GENUINE separated dependent mode, not a panel shift.
BIMODALITY_COEFFICIENT_THRESHOLD = 5.0 / 9.0  # uniform ≈ 0.556; unimodal-normal ≈ 0.33; bimodal → 1.0


def _bimodality_coefficient(scores) -> Optional[float]:
    """Sarle's bimodality coefficient, BC = (g1²+1)/(g2 + 3·(n-1)²/((n-2)(n-3))). Mirrors the CRISPR
    sibling (depmap_chronos_distribution._bimodality_coefficient). Returns None for n<4 or zero
    variance → caller falls back to median-shift routing."""
    import numpy as np
    from scipy.stats import skew, kurtosis

    x = np.asarray(scores, dtype=float)
    x = x[~np.isnan(x)]
    n = x.size
    if n < 4 or float(np.std(x)) == 0.0:
        return None
    g1 = float(skew(x, bias=True))
    g2 = float(kurtosis(x, fisher=True, bias=True))
    denom = g2 + 3.0 * (n - 1) ** 2 / ((n - 2) * (n - 3))
    if denom == 0:
        return None
    return (g1**2 + 1.0) / denom


def _classify_rnai_dependency(
    fraction_strongly_dependent: float,
    median_dep_score: float,
    distribution_shape: str,
    n_cell_lines_evaluated: int | None = None,
    moderate_threshold: float = -0.25,
    pan_essential_fraction: float = 0.85,
    selective_min: float = 0.05,
    selective_max: float = 0.60,
) -> str:
    """Map RNAi distribution stats to a DepMap-convention dependency_class categorical.

    Returns one of: common_essential | common_essential_underpowered |
                    strongly_selective | broadly_dependent | non_dependent |
                    data_unavailable

    Same vocabulary as the CRISPR sibling, applied to DEMETER2 scale. H fix (2026-07-20):
    a >=85% pan-essential call on a panel below RNAI_PAN_ESSENTIAL_MIN_PANEL_N is an
    underpowered artifact → common_essential_underpowered (routes to insufficient, NOT
    the pan-essential veto). Symmetric with the CRISPR guard.
    """
    if fraction_strongly_dependent >= pan_essential_fraction:
        if n_cell_lines_evaluated is not None and n_cell_lines_evaluated < RNAI_PAN_ESSENTIAL_MIN_PANEL_N:
            return "common_essential_underpowered"
        return "common_essential"
    # #3 fix: strongly_selective requires GENUINE bimodality (distribution_shape), NOT merely the
    # selective FRACTION band — mirrors the CRISPR classifier. A unimodal panel in the band is a shift
    # (broadly_dependent) or a heavy tail (non_dependent), not a selective dependency. The prior
    # band-only rule let a broadly-dependent RNAi panel read strongly_selective, which — combined with
    # a CRISPR broadly_dependent — fired the selective_dependent verdict for a non-selective target.
    if distribution_shape == "bimodal_selective":
        return "strongly_selective"
    if median_dep_score <= moderate_threshold and fraction_strongly_dependent > selective_max:
        return "broadly_dependent"
    if distribution_shape == "shifted_dependent":
        return "broadly_dependent"
    if distribution_shape == "non_essential":
        return "non_dependent"
    return "non_dependent"


def emit_waterfall_plot(
    demeter_by_model: dict,
    model_metadata: dict,
    target_symbol: str,
    summary: dict,
    out_dir: Path,
    target_contracts_dir: Path,
) -> Path:
    """Emit ranked-waterfall SVG (per-cell-line RNAi scores, lineage-colored)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette as pal  # type: ignore

    records = []
    for model_id, score in demeter_by_model.items():
        meta = model_metadata.get(model_id, {})
        lineage = meta.get("OncotreeLineage") or "unknown"
        records.append({"model_id": model_id, "lineage": lineage, "score": score})
    df = pd.DataFrame(records).sort_values("score").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.bar(range(len(df)), df["score"], width=1.0, color="#0a2540", linewidth=0)
    ax.axhline(-0.5, color="#cf2828", linestyle="--", linewidth=1, label="strong-dep (DEMETER2 ≤ -0.5)")
    ax.axhline(-0.25, color="#f0a020", linestyle="--", linewidth=1, label="moderate-dep")
    ax.set_xlabel(f"Cell lines (n={len(df)}, sorted by DEMETER2 score)")
    ax.set_ylabel("DEMETER2 score")
    ax.set_title(f"{target_symbol} — RNAi (DEMETER2 combined) pan-cancer dependency")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout()
    out_path = out_dir / "figure_waterfall_rnai.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_histogram_kde_plot(
    demeter_by_model: dict, target_symbol: str, summary: dict, out_dir: Path, target_contracts_dir: Path
) -> Path:
    """Emit density histogram + KDE SVG."""
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

    scores = np.array(list(demeter_by_model.values()))
    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.hist(scores, bins=50, density=True, alpha=0.5, color="#0a2540", edgecolor="white")
    if len(scores) >= 10:
        kde = gaussian_kde(scores)
        xs = np.linspace(scores.min() - 0.2, scores.max() + 0.2, 500)
        ax.plot(xs, kde(xs), color="#cf2828", linewidth=2)
    ax.axvline(-0.5, color="#cf2828", linestyle="--", linewidth=1, label="strong-dep")
    ax.axvline(-0.25, color="#f0a020", linestyle="--", linewidth=1, label="moderate-dep")
    ax.set_xlabel("DEMETER2 score")
    ax.set_ylabel("Density")
    ax.set_title(f"{target_symbol} — RNAi DEMETER2 distribution + KDE")
    ax.legend(fontsize=8)
    fig.tight_layout()
    out_path = out_dir / "figure_histogram_kde_rnai.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_plotly_specs(
    demeter_by_model: dict,
    model_metadata: dict,
    target_symbol: str,
    summary: dict,
    out_path: Path,
    contracts_root: Path,
) -> list:
    """Emit interactive Plotly specs SIBLING to the RNAi SVGs (Gate-C plotly debt, 2026-07-21).

    RNAi twin of depmap_chronos_distribution.emit_plotly_specs. Built from the SAME in-memory
    demeter_by_model the SVGs use — the interactive chart can NOT drift from the static figure or
    plot_data.parquet. DEMETER2 scale (strong -0.5 / moderate -0.25; different constants from
    Chronos), mirroring emit_waterfall_plot + emit_histogram_kde_plot exactly (navy bars, same
    reflines). Writes figure_waterfall_rnai.plotly.json + figure_histogram_kde_rnai.plotly.json.
    Best-effort: Plotly absent / any error → SVGs remain the guaranteed artifact, returns what it got."""
    try:
        import numpy as np
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001 — Plotly optional; never block the SVG artifacts
        print(f"[demeter-distribution] plotly spec emission skipped: {e}", file=sys.stderr)
        return []

    # reflines mirror the SVGs exactly: strong -0.5 (red dash), moderate -0.25 (amber dash).
    reflines = [(-0.25, "#f0a020", "dash", "moderate-dep"), (-0.5, "#cf2828", "dash", "strong-dep (DEMETER2 ≤ -0.5)")]
    written = []

    # --- Waterfall: sorted navy bars, hover = cell line + lineage + score (mirrors the SVG) ---
    try:
        rows = sorted(
            (
                (mid, s, (model_metadata.get(mid, {}).get("OncotreeLineage") or "unknown"))
                for mid, s in demeter_by_model.items()
            ),
            key=lambda r: r[1],
        )
        names = [model_metadata.get(mid, {}).get("CellLineName", mid) for mid, _, _ in rows]
        vals = [s for _, s, _ in rows]
        lineages = [lg for _, _, lg in rows]
        fig = go.Figure(
            go.Bar(
                x=list(range(len(rows))),
                y=vals,
                marker_color="#0a2540",
                customdata=list(zip(names, lineages)),
                hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>DEMETER2 %{y:.2f}<extra></extra>",
            )
        )
        for yv, col, dash, lab in reflines:
            fig.add_hline(
                y=yv, line=dict(color=col, dash=dash, width=1.5), annotation_text=lab, annotation_position="top left"
            )
        n = summary.get("rnai_n_cell_lines_evaluated", len(rows))
        shape = str(summary.get("rnai_distribution_shape", "?")).upper().replace("_", " ")
        fig.update_layout(
            title=f"{target_symbol} pan-cancer RNAi (DEMETER2) distribution (n={n}, {shape})",
            xaxis_title="Cell line (sorted by dependency)",
            yaxis_title="DEMETER2 score (more dependent ↓)",
            template="plotly_white",
            showlegend=False,
            bargap=0,
            margin=dict(l=60, r=20, t=50, b=50),
        )
        (out_path / "figure_waterfall_rnai.plotly.json").write_text(fig.to_json())
        written.append({"id": "waterfall_rnai", "path": "figure_waterfall_rnai.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[demeter-distribution] waterfall plotly skipped: {e}", file=sys.stderr)

    # --- Histogram (density): navy bars + reflines + strong-dep shade (mirrors the SVG) ---
    try:
        scores = np.array(list(demeter_by_model.values()), dtype=float)
        fig = go.Figure(
            go.Histogram(
                x=scores,
                histnorm="probability density",
                nbinsx=50,
                marker_color="#0a2540",
                marker_line_color="white",
                marker_line_width=0.5,
                opacity=0.75,
                hovertemplate="DEMETER2 %{x:.2f}<br>density %{y:.3f}<extra></extra>",
            )
        )
        fig.add_vrect(x0=float(scores.min()) - 0.2, x1=-0.5, fillcolor="#cf2828", opacity=0.10, line_width=0)
        for xv, col, dash, lab in reflines:
            fig.add_vline(
                x=xv, line=dict(color=col, dash=dash, width=1.5), annotation_text=lab, annotation_position="top"
            )
        n = summary.get("rnai_n_cell_lines_evaluated", len(scores))
        med = summary.get("rnai_median_dep_score", float(np.median(scores)))
        fig.update_layout(
            title=f"{target_symbol} RNAi DEMETER2 density (n={n}, median {med:.2f})",
            xaxis_title="DEMETER2 score",
            yaxis_title="Density",
            template="plotly_white",
            showlegend=False,
            margin=dict(l=60, r=20, t=50, b=50),
        )
        (out_path / "figure_histogram_kde_rnai.plotly.json").write_text(fig.to_json())
        written.append({"id": "histogram_kde_rnai", "path": "figure_histogram_kde_rnai.plotly.json", "type": "plotly"})
    except Exception as e:  # noqa: BLE001
        print(f"[demeter-distribution] histogram plotly skipped: {e}", file=sys.stderr)

    return written


def emit_plot_data(demeter_by_model: dict, model_metadata: dict, strong_threshold: float, out_path: Path) -> Path:
    """Emit per-cell-line long-format Parquet for re-rendering / downstream use."""
    import pandas as pd

    records = []
    for model_id, score in demeter_by_model.items():
        meta = model_metadata.get(model_id, {})
        records.append(
            {
                "model_id": model_id,
                "ccle_name": meta.get("CCLEName"),
                "lineage": meta.get("OncotreeLineage"),
                "demeter2_score": score,
                "is_strongly_dependent": score <= strong_threshold,
            }
        )
    df = pd.DataFrame(records)
    out_file = out_path / "plot_data_rnai.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_manifest(
    target_symbol: str, release_pin: str, summary: dict, demeter_by_model: dict, out_dir: Path, load_errors: list
) -> Path:
    """Emit provenance manifest YAML."""
    import yaml

    manifest = {
        "method_id": "depmap-demeter-distribution",
        "method_version": METHOD_VERSION,
        "card_id": "pan-cancer-rnai-dependency-distribution",
        "target": target_symbol,
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "rnai_matrix": f"{RNAI_S3_PREFIX}/D2_combined_gene_dep_scores.csv",
            "sample_info": f"{RNAI_S3_PREFIX}/sample_info.csv",
            "model_csv": f"{CRISPR_S3_PREFIX}/Model.csv",
        },
        "n_cell_lines_evaluated": summary.get("rnai_n_cell_lines_evaluated", 0),
        "rnai_dependency_class": summary.get("rnai_dependency_class", "data_unavailable"),
        "load_errors": load_errors,
    }
    out_file = out_dir / "manifest.yaml"
    with open(out_file, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return out_file


@click.command()
@click.option("--target", required=True, help="HGNC symbol")
@click.option("--release-pin", default="26q1")
@click.option("--strong-dependency-threshold", default=-0.5, type=float)
@click.option("--moderate-dependency-threshold", default=-0.25, type=float)
@click.option("--out", required=True, type=click.Path(file_okay=False, writable=True, path_type=Path))
def main(
    target: str, release_pin: str, strong_dependency_threshold: float, moderate_dependency_threshold: float, out: Path
) -> None:
    """CLI entrypoint — load RNAi data, compute summary, emit figures + manifest."""
    out.mkdir(parents=True, exist_ok=True)
    demeter_by_model, model_metadata, load_errors, sample_info_df = load_rnai_files(release_pin, target)
    if load_errors:
        click.echo(f"  Load errors: {load_errors}", err=True)
        # Write an _live_read_error summary.json + exit
        err_summary = {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "rnai_dependency_class": "data_unavailable",
            "rnai_distribution_shape": "unclassified",
        }
        (out / "summary.json").write_text(json.dumps(err_summary, indent=2))
        sys.exit(1)

    summary = compute_summary_stats(
        demeter_by_model,
        model_metadata,
        sample_info_df=sample_info_df,  # Track C fix: was dropped → rnai_screens_contributing always []
        strong_threshold=strong_dependency_threshold,
        moderate_threshold=moderate_dependency_threshold,
    )
    summary["rnai_dependency_class"] = summary.get("rnai_dependency_class", "data_unavailable")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))

    emit_waterfall_plot(demeter_by_model, model_metadata, target, summary, out, DEFAULT_TARGET_CONTRACTS)
    emit_histogram_kde_plot(demeter_by_model, target, summary, out, DEFAULT_TARGET_CONTRACTS)
    emit_plot_data(demeter_by_model, model_metadata, strong_dependency_threshold, out)
    emit_manifest(target, release_pin, summary, demeter_by_model, out, load_errors)
    click.echo(f"  -> {out}", err=True)


if __name__ == "__main__":
    main()
