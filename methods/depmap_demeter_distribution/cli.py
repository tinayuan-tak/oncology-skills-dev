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


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEFAULT_CATALOG_REPO = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"
)
DEFAULT_TARGET_CONTRACTS = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
)
RNAI_S3_PREFIX = "s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1-rnai"
CRISPR_S3_PREFIX = "s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1"
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


def load_rnai_files(release_pin: str, target_symbol: str) -> tuple[dict, dict, list]:
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
        from botocore.exceptions import ClientError, NoCredentialsError
        s3 = boto3.client("s3")
        bucket = "onc-compbio"

        if rnai_path is None:
            rnai_key = "data-catalog/sources/depmap-consortium/dmc-26q1-rnai/D2_combined_gene_dep_scores.csv"
            click.echo(f"  Fetching s3://{bucket}/{rnai_key}", err=True)
            obj = s3.get_object(Bucket=bucket, Key=rnai_key)
            # The D2 file is 161 MB but we only need the row matching the target gene.
            # Stream + filter by index. pandas can't natively do "read only matching rows"
            # so we read the whole file once; it's an in-memory operation (~600 MB peak
            # for the float matrix). Acceptable for live-mode.
            rnai_df = pd.read_csv(BytesIO(obj["Body"].read()), index_col=0, na_values=["NA", ""])
        else:
            rnai_df = pd.read_csv(rnai_path, index_col=0, na_values=["NA", ""])

        if sample_info_path is None:
            si_key = "data-catalog/sources/depmap-consortium/dmc-26q1-rnai/sample_info.csv"
            click.echo(f"  Fetching s3://{bucket}/{si_key}", err=True)
            obj = s3.get_object(Bucket=bucket, Key=si_key)
            sample_info_df = pd.read_csv(BytesIO(obj["Body"].read()))
        else:
            sample_info_df = pd.read_csv(sample_info_path)

        if model_path is None:
            model_key = "data-catalog/sources/depmap-consortium/dmc-26q1/Model.csv"
            click.echo(f"  Fetching s3://{bucket}/{model_key}", err=True)
            obj = s3.get_object(Bucket=bucket, Key=model_key)
            model_df = pd.read_csv(BytesIO(obj["Body"].read()))
        else:
            model_df = pd.read_csv(model_path)
    except ImportError as e:
        load_errors.append({
            "_live_read_error": "boto3_not_available",
            "detail": str(e),
            "remediation": f"Install boto3 or provide local RNAi cache at one of {[str(d) for d in RNAI_LOCAL_FALLBACK_DIRS]}",
        })
        return {}, {}, load_errors
    except Exception as e:
        load_errors.append({
            "_live_read_error": "s3_read_failed",
            "detail": str(e),
            "remediation": f"Ensure AWS credentials are set and {RNAI_S3_PREFIX} is accessible.",
        })
        return {}, {}, load_errors

    # === 3. Find target gene row in D2_combined ===
    target_row = None
    for idx_label in rnai_df.index:
        symbol = _parse_gene_symbol(idx_label)
        if symbol == target_symbol:
            target_row = rnai_df.loc[idx_label]
            break
    if target_row is None:
        load_errors.append({
            "_live_read_error": "target_not_in_rnai_panel",
            "detail": f"Target {target_symbol} not found in D2_combined_gene_dep_scores.csv (RNAi panel)",
            "remediation": "Confirm HGNC symbol spelling; check whether target was screened in Achilles/DRIVE/Marcotte RNAi panels.",
        })
        return {}, {}, load_errors

    # === 4. Bridge CCLE_ID columns -> ModelID via Model.csv's CCLEName ===
    # Model.csv columns: ModelID, CCLEName, OncotreeLineage, ...
    if "CCLEName" not in model_df.columns or "ModelID" not in model_df.columns:
        load_errors.append({
            "_live_read_error": "model_csv_missing_bridge_columns",
            "detail": "Model.csv lacks CCLEName or ModelID columns required for CCLE_ID -> ModelID bridge",
            "remediation": "Verify Model.csv schema; the 26Q1 release should carry both columns.",
        })
        return {}, {}, load_errors

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
        click.echo(f"  Note: {n_unbridged} RNAi cell lines could not be bridged to ModelID (CCLE_ID not in Model.csv)",
                   err=True)

    return demeter_by_model_id, model_metadata_by_id, load_errors


def compute_summary_stats(demeter_by_model: dict, model_metadata: dict,
                          sample_info_df=None,
                          strong_threshold: float = -0.5,
                          moderate_threshold: float = -0.25,
                          pan_essential_fraction: float = 0.85,
                          selective_min: float = 0.05,
                          selective_max: float = 0.60) -> dict:
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
        shape = "bimodal_selective" if median_panel > moderate_threshold else "shifted_dependent"
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
        lineage = (meta.get("OncotreeLineage") or meta.get("lineage")
                   or meta.get("PrimaryDisease") or "unknown")
        lineage_records.append({"model_id": model_id, "lineage": lineage, "score": score})

    lineage_df = pd.DataFrame(lineage_records)
    top_lineages = []
    for lineage_name, subset in lineage_df.groupby("lineage"):
        if len(subset) < 5:
            continue
        frac_strong_lin = float((subset["score"] <= strong_threshold).mean())
        tail_total = max(1, int((lineage_df["score"] <= strong_threshold).sum()))
        top_lineages.append({
            "lineage": lineage_name,
            "n_in_lineage": int(len(subset)),
            "fraction_strongly_dependent": frac_strong_lin,
            "median_dep_score": float(subset["score"].median()),
            "fraction_of_dependent_tail": float((subset["score"] <= strong_threshold).sum() / tail_total),
        })
    top_lineages.sort(key=lambda x: x["fraction_strongly_dependent"], reverse=True)
    summary["rnai_top_dependent_lineages"] = top_lineages[:5]

    # rnai_dependency_class — same vocabulary as CRISPR card's dependency_class
    summary["rnai_dependency_class"] = _classify_rnai_dependency(
        fraction_strongly_dependent=frac_strong,
        median_dep_score=median_panel,
        distribution_shape=shape,
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


def _classify_rnai_dependency(fraction_strongly_dependent: float,
                               median_dep_score: float,
                               distribution_shape: str,
                               moderate_threshold: float = -0.25,
                               pan_essential_fraction: float = 0.85,
                               selective_min: float = 0.05,
                               selective_max: float = 0.60) -> str:
    """Map RNAi distribution stats to a DepMap-convention dependency_class categorical.

    Returns one of: common_essential | strongly_selective | broadly_dependent |
                    non_dependent | data_unavailable

    Same vocabulary as the CRISPR sibling, applied to DEMETER2 scale.
    """
    if fraction_strongly_dependent >= pan_essential_fraction:
        return "common_essential"
    if selective_min <= fraction_strongly_dependent <= selective_max:
        return "strongly_selective"
    if median_dep_score <= moderate_threshold and fraction_strongly_dependent > selective_max:
        return "broadly_dependent"
    return "non_dependent"


def emit_waterfall_plot(demeter_by_model: dict, model_metadata: dict, target_symbol: str,
                         summary: dict, out_dir: Path, target_contracts_dir: Path) -> Path:
    """Emit ranked-waterfall SVG (per-cell-line RNAi scores, lineage-colored)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    style_path = target_contracts_dir / "branding" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    records = []
    for model_id, score in demeter_by_model.items():
        meta = model_metadata.get(model_id, {})
        lineage = (meta.get("OncotreeLineage") or "unknown")
        records.append({"model_id": model_id, "lineage": lineage, "score": score})
    df = pd.DataFrame(records).sort_values("score").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=(10, 5))
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


def emit_histogram_kde_plot(demeter_by_model: dict, target_symbol: str, summary: dict,
                              out_dir: Path, target_contracts_dir: Path) -> Path:
    """Emit density histogram + KDE SVG."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scipy.stats import gaussian_kde

    style_path = target_contracts_dir / "branding" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))

    scores = np.array(list(demeter_by_model.values()))
    fig, ax = plt.subplots(figsize=(8, 5))
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


def emit_plot_data(demeter_by_model: dict, model_metadata: dict,
                    strong_threshold: float, out_path: Path) -> Path:
    """Emit per-cell-line long-format Parquet for re-rendering / downstream use."""
    import pandas as pd

    records = []
    for model_id, score in demeter_by_model.items():
        meta = model_metadata.get(model_id, {})
        records.append({
            "model_id": model_id,
            "ccle_name": meta.get("CCLEName"),
            "lineage": meta.get("OncotreeLineage"),
            "demeter2_score": score,
            "is_strongly_dependent": score <= strong_threshold,
        })
    df = pd.DataFrame(records)
    out_file = out_path / "plot_data_rnai.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_manifest(target_symbol: str, release_pin: str, summary: dict,
                   demeter_by_model: dict, out_dir: Path, load_errors: list) -> Path:
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
def main(target: str, release_pin: str, strong_dependency_threshold: float,
         moderate_dependency_threshold: float, out: Path) -> None:
    """CLI entrypoint — load RNAi data, compute summary, emit figures + manifest."""
    out.mkdir(parents=True, exist_ok=True)
    demeter_by_model, model_metadata, load_errors = load_rnai_files(release_pin, target)
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
        demeter_by_model, model_metadata,
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
