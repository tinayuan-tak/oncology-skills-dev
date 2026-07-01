#!/usr/bin/env python3
"""depmap-expression-distribution CLI — pan-cancer expression distribution analysis.

Consumes DepMap 26Q1 OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv + Model.csv,
emits per-target expression distribution stats across the cell-line panel + per-
lineage breakdown + waterfall + per-lineage strip figures + plot_data.parquet.

Anchored to DepMap's log2(TPM+1) convention:
  log2(TPM+1) >= 1.0  = expressed
  log2(TPM+1) >= 5.0  = highly expressed
  log2(TPM+1) <  1.0  = not expressed

Filters cell lines via IsDefaultEntryForModel column when present (string "Yes"/"No"
in 26Q1, NOT boolean — see [feedback_compose_dashboard_execution_modes]).
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

DEFAULT_TARGET_CONTRACTS = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
)
DEPMAP_S3_PREFIX = "s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1"
DEPMAP_LOCAL_FALLBACK_DIRS = [
    Path("/home/sagemaker-user/depmap-26q1"),
    Path("/data/depmap/26q1"),
    Path.home() / "depmap-26q1",
]


def load_expression_files(release_pin: str, target_symbol: str) -> tuple[dict, dict, list]:
    """Load OmicsExpressionTPMLogp1HumanProteinCodingGenes target column + Model.csv.

    Returns:
        tpm_by_model: {model_id -> log2(TPM+1) float}
        model_metadata: {model_id -> meta dict (OncotreeLineage, CCLEName, ...)}
        load_errors: list (empty on success)

    Filters by IsDefaultEntryForModel == 'Yes' / boolean True when present.
    """
    import pandas as pd

    load_errors = []
    tpm_path = None
    model_path = None

    for fallback in DEPMAP_LOCAL_FALLBACK_DIRS:
        tt = fallback / "OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv"
        mm = fallback / "Model.csv"
        if tt.exists() and mm.exists():
            tpm_path = tt
            model_path = mm
            click.echo(f"  Using local DepMap cache at {fallback}", err=True)
            break

    try:
        if tpm_path is None:
            import boto3
            # Model.csv via shared cached loader
            from methods.depmap_common import load_model_csv
            model_df = load_model_csv(release_pin)

            s3 = boto3.client("s3")
            bucket = "onc-compbio"
            tpm_key = "data-catalog/sources/depmap-consortium/dmc-26q1/OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv"

            click.echo(f"  Fetching s3://{bucket}/{tpm_key} (target column only)", err=True)
            tpm_obj = s3.get_object(Bucket=bucket, Key=tpm_key)
            tpm_df = pd.read_csv(BytesIO(tpm_obj["Body"].read()))
        else:
            model_df = pd.read_csv(model_path)
            tpm_df = pd.read_csv(tpm_path)
    except ImportError as e:
        load_errors.append({
            "_live_read_error": "boto3_not_available",
            "detail": str(e),
            "remediation": f"Install boto3 or provide local cache at {[str(d) for d in DEPMAP_LOCAL_FALLBACK_DIRS]}",
        })
        return {}, {}, load_errors
    except Exception as e:
        load_errors.append({
            "_live_read_error": "s3_read_failed",
            "detail": str(e),
            "remediation": f"Ensure AWS credentials are set and {DEPMAP_S3_PREFIX} is accessible.",
        })
        return {}, {}, load_errors

    # Find target column in TPM matrix
    target_cols = [c for c in tpm_df.columns
                    if c == target_symbol or c.split(" ")[0] == target_symbol]
    if not target_cols:
        load_errors.append({
            "_live_read_error": "target_not_in_expression_matrix",
            "detail": f"Target {target_symbol} not in TPM matrix",
        })
        return {}, {}, load_errors

    target_col = target_cols[0]
    # 26Q1 TPM matrix puts metadata columns FIRST (SequencingID, ModelConditionID,
    # ModelID, IsDefaultEntryForModel, IsDefaultEntryForMC); the first physical
    # column is the unnamed pandas row-index. Explicit lookup for ModelID required.
    if "ModelID" in tpm_df.columns:
        id_col = "ModelID"
    else:
        # Fallback for older releases where the matrix was cell-line-indexed directly.
        id_col = tpm_df.columns[0]

    # IsDefaultEntryForModel filter — string "Yes" / boolean True in 26Q1
    if "IsDefaultEntryForModel" in tpm_df.columns:
        mask = tpm_df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])
        tpm_df = tpm_df[mask]

    tpm_by_model = {}
    for _, row in tpm_df[[id_col, target_col]].iterrows():
        if pd.notna(row[target_col]):
            tpm_by_model[row[id_col]] = float(row[target_col])

    model_id_col = "ModelID" if "ModelID" in model_df.columns else model_df.columns[0]
    model_metadata = {row[model_id_col]: row.to_dict() for _, row in model_df.iterrows()}

    return tpm_by_model, model_metadata, load_errors


def compute_summary_stats(tpm_by_model: dict, model_metadata: dict,
                           expressed_threshold: float = 1.0,
                           highly_expressed_threshold: float = 5.0,
                           broadly_expressed_fraction: float = 0.70,
                           broadly_high_fraction: float = 0.30,
                           lineage_restricted_min_fraction: float = 0.10,
                           lineage_restricted_max_fraction: float = 0.70,
                           min_lineage_size: int = 5) -> dict:
    """Compute decision-grade summary scalars for the expression-distribution card."""
    import numpy as np
    import pandas as pd

    if not tpm_by_model:
        return {"_no_data": True}

    scores = np.array(list(tpm_by_model.values()))
    n = len(scores)

    summary = {
        "n_cell_lines_evaluated": int(n),
        "median_log2tpm_panel": float(np.median(scores)),
        "p25_log2tpm_panel": float(np.percentile(scores, 25)),
        "p75_log2tpm_panel": float(np.percentile(scores, 75)),
        "p5_log2tpm_panel": float(np.percentile(scores, 5)),
        "p95_log2tpm_panel": float(np.percentile(scores, 95)),
        "log2tpm_iqr": float(np.percentile(scores, 75) - np.percentile(scores, 25)),
    }

    frac_expressed = float(np.mean(scores >= expressed_threshold))
    frac_highly = float(np.mean(scores >= highly_expressed_threshold))
    summary["fraction_expressed"] = frac_expressed
    summary["fraction_highly_expressed"] = frac_highly
    summary["fraction_not_expressed"] = float(np.mean(scores < expressed_threshold))

    # Per-lineage stats
    lineage_records = []
    for model_id, log2tpm in tpm_by_model.items():
        meta = model_metadata.get(model_id, {})
        lineage = (meta.get("OncotreeLineage") or meta.get("lineage")
                   or meta.get("PrimaryDisease") or "unknown")
        lineage_records.append({"model_id": model_id, "lineage": lineage, "log2tpm": log2tpm})
    lineage_df = pd.DataFrame(lineage_records)

    per_lineage = []
    n_lineage_restricted = 0
    for lineage_name, subset in lineage_df.groupby("lineage"):
        if len(subset) < min_lineage_size:
            continue
        frac_expr_lin = float((subset["log2tpm"] >= expressed_threshold).mean())
        per_lineage.append({
            "lineage": lineage_name,
            "n": int(len(subset)),
            "median_log2tpm": float(subset["log2tpm"].median()),
            "fraction_expressed": frac_expr_lin,
        })
        # Lineage-restricted-driver: lineage's expression frac is ≥0.4 ABOVE the panel
        # average. This handles the case where the panel itself is mid-range (e.g.
        # 33% expressed driven by ONE lineage) without requiring strict panel<30%.
        if (frac_expr_lin - frac_expressed) >= 0.40:
            n_lineage_restricted += 1
    per_lineage.sort(key=lambda x: x["median_log2tpm"], reverse=True)

    summary["n_lineages_evaluated"] = len(per_lineage)
    summary["per_lineage_stats"] = per_lineage[:20]  # top-20 by median expression
    summary["n_lineage_restricted_lineages"] = n_lineage_restricted

    # expression_class derivation
    summary["expression_class"] = _classify_expression(
        frac_expressed=frac_expressed,
        frac_highly=frac_highly,
        n_lineage_restricted=n_lineage_restricted,
        broadly_expressed_fraction=broadly_expressed_fraction,
        broadly_high_fraction=broadly_high_fraction,
        lineage_restricted_min_fraction=lineage_restricted_min_fraction,
        lineage_restricted_max_fraction=lineage_restricted_max_fraction,
    )

    return summary


def _classify_expression(frac_expressed: float, frac_highly: float,
                          n_lineage_restricted: int,
                          broadly_expressed_fraction: float = 0.70,
                          broadly_high_fraction: float = 0.30,
                          lineage_restricted_min_fraction: float = 0.10,
                          lineage_restricted_max_fraction: float = 0.70) -> str:
    """Map distribution stats to expression_class vocabulary.

    Returns one of:
      broadly_high | broadly_moderate | lineage_restricted | broadly_low | data_unavailable
    """
    if frac_expressed >= broadly_expressed_fraction:
        if frac_highly >= broadly_high_fraction:
            return "broadly_high"
        return "broadly_moderate"
    if lineage_restricted_min_fraction <= frac_expressed <= lineage_restricted_max_fraction:
        return "lineage_restricted"
    if frac_expressed < lineage_restricted_min_fraction:
        return "broadly_low"
    return "broadly_moderate"   # 70-90% range fallback


def _load_takeda_style(target_contracts_dir: Path):
    """Load the Takeda mplstyle + palette constants. Idempotent.

    Returns the palette module so callers can pull constants like
    FIGSIZE_DOUBLE_COLUMN, REFLINE_NEUTRAL, REFLINE_KILLER.
    """
    import matplotlib.pyplot as plt
    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette  # type: ignore
    return takeda_palette


def emit_density_plot(tpm_by_model: dict, target_symbol: str, summary: dict,
                       out_dir: Path, target_contracts_dir: Path) -> Path:
    """Emit pan-cancer KDE + histogram density plot — PRIMARY figure for E3.a.

    Histogram + KDE overlay with threshold reference lines at log2(TPM+1)=1.0
    ('expressed') and =5.0 ('highly expressed'). Mirrors the depmap-portal
    convention for the per-gene expression panel.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from scipy.stats import gaussian_kde

    pal = _load_takeda_style(target_contracts_dir)
    scores = np.array(list(tpm_by_model.values()))

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.hist(scores, bins=50, density=True, alpha=0.45, color="#0a2540", edgecolor="white")
    if len(scores) >= 10:
        kde = gaussian_kde(scores)
        xs = np.linspace(scores.min() - 0.2, scores.max() + 0.2, 500)
        ax.plot(xs, kde(xs), color="#cf2828", linewidth=2)
    ax.axvline(1.0, color="#f0a020", linestyle="--", linewidth=1, label="expressed (≥1.0)")
    ax.axvline(5.0, color="#cf2828", linestyle="--", linewidth=1, label="highly expressed (≥5.0)")
    ax.set_xlabel("log2(TPM+1)")
    ax.set_ylabel("Density")
    ax.set_title(f"{target_symbol} — pan-cancer expression distribution (n={len(scores)})")
    ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()
    out_path = out_dir / "figure_density_expression.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_waterfall_plot(tpm_by_model: dict, model_metadata: dict, target_symbol: str,
                         summary: dict, out_dir: Path, target_contracts_dir: Path) -> Path:
    """Emit ranked-waterfall SVG — SECONDARY figure (demoted from primary).

    Shows the per-cell-line distribution sorted ascending. Less interpretable than
    the density plot at-a-glance but preserves the per-line resolution that
    density bins out.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    pal = _load_takeda_style(target_contracts_dir)

    records = []
    for model_id, log2tpm in tpm_by_model.items():
        meta = model_metadata.get(model_id, {})
        lineage = meta.get("OncotreeLineage") or "unknown"
        records.append({"model_id": model_id, "lineage": lineage, "log2tpm": log2tpm})
    df = pd.DataFrame(records).sort_values("log2tpm").reset_index(drop=True)

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.bar(range(len(df)), df["log2tpm"], width=1.0, color="#0a2540", linewidth=0)
    ax.axhline(1.0, color="#f0a020", linestyle="--", linewidth=1, label="expressed (≥1.0)")
    ax.axhline(5.0, color="#cf2828", linestyle="--", linewidth=1, label="highly expressed (≥5.0)")
    ax.set_xlabel(f"Cell lines (n={len(df)}, sorted by expression)")
    ax.set_ylabel("log2(TPM+1)")
    ax.set_title(f"{target_symbol} — pan-cancer expression (ranked waterfall)")
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    out_path = out_dir / "figure_waterfall_expression.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_lineage_strip(tpm_by_model: dict, model_metadata: dict, target_symbol: str,
                        summary: dict, out_dir: Path, target_contracts_dir: Path) -> Path:
    """Emit per-lineage strip plot SVG. Lineages ordered by median expression desc,
    n>=5 only. Sized via FIGSIZE_SINGLE_COLUMN_TALL with vertical room scaled to
    n_lineages — most targets give 25-30 lineages, each ~0.2in vertical."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    pal = _load_takeda_style(target_contracts_dir)

    records = []
    for model_id, log2tpm in tpm_by_model.items():
        meta = model_metadata.get(model_id, {})
        lineage = meta.get("OncotreeLineage") or "unknown"
        records.append({"lineage": lineage, "log2tpm": log2tpm})
    df = pd.DataFrame(records)

    lineage_medians = df.groupby("lineage")["log2tpm"].agg(["median", "count"])
    lineage_medians = lineage_medians[lineage_medians["count"] >= 5].sort_values("median", ascending=False)
    lineages_ordered = list(lineage_medians.index)

    # Vertical sizing: scale n_lineages * 0.2in but cap to a reasonable max so it
    # never dwarfs the rest of the dashboard layout
    fig_h = min(max(3.5, len(lineages_ordered) * 0.2), 7.0)
    fig, ax = plt.subplots(figsize=(pal.FIGSIZE_DOUBLE_COLUMN[0], fig_h))
    for i, lin in enumerate(lineages_ordered):
        scores = df[df["lineage"] == lin]["log2tpm"].values
        xs = np.full(len(scores), i)
        jitter = np.random.RandomState(42 + i).uniform(-0.15, 0.15, size=len(scores))
        ax.scatter(scores, xs + jitter, alpha=0.5, s=8, color=pal.get_lineage_color(lin))
        ax.scatter([np.median(scores)], [i], color="#B22222", s=30, marker="|", zorder=5)
    ax.axvline(1.0, color="#f0a020", linestyle="--", linewidth=1)
    ax.axvline(5.0, color="#cf2828", linestyle="--", linewidth=1)
    ax.set_yticks(range(len(lineages_ordered)))
    ax.set_yticklabels(lineages_ordered, fontsize=8)
    # Invert y-axis so highest-median lineage is on top (matches ordered-by-median-desc semantics)
    ax.invert_yaxis()
    ax.set_xlabel("log2(TPM+1)")
    ax.set_title(f"{target_symbol} — per-lineage expression (n≥5; ordered by median, top=highest)")
    fig.tight_layout()
    out_path = out_dir / "figure_lineage_strip_expression.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_plot_data(tpm_by_model: dict, model_metadata: dict,
                    expressed_threshold: float, out_path: Path) -> Path:
    import pandas as pd
    records = []
    for model_id, log2tpm in tpm_by_model.items():
        meta = model_metadata.get(model_id, {})
        records.append({
            "model_id": model_id,
            "ccle_name": meta.get("CCLEName"),
            "lineage": meta.get("OncotreeLineage"),
            "log2tpm": log2tpm,
            "is_expressed": log2tpm >= expressed_threshold,
        })
    df = pd.DataFrame(records)
    out_file = out_path / "plot_data_expression.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_manifest(target_symbol: str, release_pin: str, summary: dict,
                   out_dir: Path, load_errors: list) -> Path:
    import yaml
    manifest = {
        "method_id": "depmap-expression-distribution",
        "method_version": METHOD_VERSION,
        "card_id": "expression-distribution",
        "target": target_symbol,
        "release_pin": release_pin,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "tpm_matrix": f"{DEPMAP_S3_PREFIX}/OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv",
            "model_csv": f"{DEPMAP_S3_PREFIX}/Model.csv",
        },
        "n_cell_lines_evaluated": summary.get("n_cell_lines_evaluated", 0),
        "expression_class": summary.get("expression_class", "data_unavailable"),
        "load_errors": load_errors,
    }
    out_file = out_dir / "manifest.yaml"
    with open(out_file, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return out_file


@click.command()
@click.option("--target", required=True)
@click.option("--release-pin", default="26q1")
@click.option("--expressed-threshold", default=1.0, type=float)
@click.option("--out", required=True, type=click.Path(file_okay=False, writable=True, path_type=Path))
def main(target, release_pin, expressed_threshold, out):
    out.mkdir(parents=True, exist_ok=True)
    tpm_by_model, model_meta, load_errors = load_expression_files(release_pin, target)
    if load_errors:
        err = {
            "_live_read_error": load_errors[0].get("_live_read_error", "unknown"),
            "errors": load_errors,
            "expression_class": "data_unavailable",
        }
        (out / "summary.json").write_text(json.dumps(err, indent=2))
        sys.exit(1)
    summary = compute_summary_stats(tpm_by_model, model_meta, expressed_threshold=expressed_threshold)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_density_plot(tpm_by_model, target, summary, out, DEFAULT_TARGET_CONTRACTS)
    emit_waterfall_plot(tpm_by_model, model_meta, target, summary, out, DEFAULT_TARGET_CONTRACTS)
    emit_lineage_strip(tpm_by_model, model_meta, target, summary, out, DEFAULT_TARGET_CONTRACTS)
    emit_plot_data(tpm_by_model, model_meta, expressed_threshold, out)
    emit_manifest(target, release_pin, summary, out, [])
    click.echo(f"  -> {out}", err=True)


if __name__ == "__main__":
    main()
