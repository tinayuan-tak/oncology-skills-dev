#!/usr/bin/env python3
"""depmap-predictability CLI (v2 — DepMap-parity + extensions thin lookup).

Reads ONE row out of the frozen derived parquet (default pin 26q1-v3)
`s3://onc-compbio/data-catalog/derived/depmap-predictability-26q1-v3/predictability_per_gene.parquet`
via pyarrow predicate pushdown. The parquet was produced by the sibling
precompute method (`depmap_predictability_precompute`). v2 remains selectable
via --release-pin for reproducibility (identical schema; v3 only widens the
gene-set gate 0.30 → 0.15).

v2 schema exposes:
  - pearson_r_rf + r² + bootstrap 95% CI (primary DepMap-parity scalar)
  - pearson_r_xgb + r² + CI (XGBoost companion)
  - model_agreement + delta_r2 (dual-model divergence diagnostic)
  - top_features_rf_shap + top_features_xgb_shap: top-ranked features. NOTE: the
    `_shap` column suffix is retained for schema-compat with v1/v2, but the shipped
    26q1 products carry RF impurity importances / XGB gain importances, NOT SHAP
    values (the precompute lazy-imports `shap` and took its documented fallback path
    when shap was absent at runtime; see the derived-manifest provenance note). Human-
    facing figure labels say "feature importance" accordingly. Re-run with `shap`
    installed for true TreeExplainer attributions.
  - per_lineage_predictability (RF-only lineage-conditional table)
  - predictability_class (own_omics_driven / context_or_driver_dependent /
    weakly_predictable / unpredictable / data_unavailable)
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click

from methods.catalog_query.read import s3_uri_for

METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.2.0"

DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

# Release-pin → parquet S3 URI. v3 (wider 0.15 gate, 9,240 genes) is the canonical build;
# v2 (0.30 gate, 3,730 genes) is RETAINED for reproducibility of historical runs. v2/v3
# resolve from their data-catalog manifests (single source of truth); v1's manifest is NOT
# in the catalog (BLOCKED) so its URI stays hardcoded until that manifest lands.
RELEASE_PIN_TO_PARQUET = {
    "26q1-v1": "s3://onc-compbio/data-catalog/derived/depmap-predictability-26q1-v1/predictability_per_gene.parquet",
    "26q1-v2": s3_uri_for("depmap-predictability-26q1-v2"),
    "26q1-v3": s3_uri_for("depmap-predictability-26q1-v3"),
}

# Feature-class → SVG color map. Extended for v2 (arm + driver_gof/lof + cross-gene).
FEATURE_CLASS_COLORS = {
    "own_expression": "#0a2540",  # Takeda navy — target-own transcriptome
    "own_copy_number": "#7fa7c0",  # light blue — target-own CN
    "own_mut_hotspot": "#cf2828",  # red — target-own hotspot
    "own_mut_damaging": "#f0a020",  # orange — target-own damaging
    "cross_gene_expression": "#2e5cb8",  # deeper blue — other-gene expression
    "cross_gene_copy_number": "#8fa8c8",  # slate — other-gene CN
    "arm_level_cn": "#9b3192",  # purple — arm-mean CN
    "oncokb_gof": "#e05a5a",  # coral — driver GoF flag
    "oncokb_lof": "#f4b360",  # ochre — driver LoF flag
    "lineage": "#888888",  # gray — context, not target-intrinsic
    "other": "#dddddd",
    "unpredictable": "#bbbbbb",
    "data_unavailable": "#bbbbbb",
}


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    if p.scheme != "s3" or not p.netloc:
        raise ValueError(f"Not an S3 URI: {uri}")
    return p.netloc, p.path.lstrip("/")


def fetch_predictability_row(parquet_uri: str, gene: str) -> Optional[dict]:
    """Pyarrow predicate-pushdown read for ONE gene row. Returns dict or None."""
    import pyarrow.parquet as pq

    if parquet_uri.startswith("s3://"):
        import pyarrow.fs as pafs

        bucket, key = _parse_s3_uri(parquet_uri)
        fs = pafs.S3FileSystem()
        path = f"{bucket}/{key}"
    else:
        fs = None
        path = parquet_uri
    table = pq.read_table(path, filesystem=fs, filters=[("gene_symbol", "=", gene)])
    if table.num_rows == 0:
        return None
    if table.num_rows > 1:
        raise RuntimeError(f"Multiple rows for {gene!r}; parquet violated uniqueness")
    return {col: table[col][0].as_py() for col in table.column_names}


def compute_summary(row: Optional[dict], target: str) -> dict:
    """Map a v2 parquet row → the card's summary_fields shape.

    When the row is None (target absent from the derived product), emit a
    data_unavailable summary with rationale in _remediation.
    """
    if row is None:
        return {
            "_live_read_error": "target_not_in_derived_product",
            "_remediation": "Target not in v2 medium-scope precompute. Will be re-evaluated in the genome-wide batch.",
            "pred_n_cell_lines_evaluated": 0,
            "pearson_r_rf": None,
            "pearson_r_squared_rf": None,
            "pearson_r_squared_rf_ci_lo": None,
            "pearson_r_squared_rf_ci_hi": None,
            "pearson_r_xgb": None,
            "pearson_r_squared_xgb": None,
            "model_agreement": "data_unavailable",
            "delta_r2": None,
            "pred_top_features_rf": [],
            "pred_top_features_xgb": [],
            "pred_dominant_feature": None,
            "pred_dominant_feature_class": "data_unavailable",
            "predictability_class": "data_unavailable",
            "per_lineage_predictability": [],
        }
    top_rf = row.get("top_features_rf_shap") or []
    top_xgb = row.get("top_features_xgb_shap") or []
    top_feature_name = top_rf[0]["feature"] if top_rf else None
    return {
        "pred_n_cell_lines_evaluated": int(row.get("n_cell_lines_evaluated") or 0),
        "pearson_r_rf": row.get("pearson_r_rf"),
        "pearson_r_squared_rf": row.get("pearson_r_squared_rf"),
        "pearson_r_squared_rf_ci_lo": row.get("pearson_r_squared_rf_ci_lo"),
        "pearson_r_squared_rf_ci_hi": row.get("pearson_r_squared_rf_ci_hi"),
        "pearson_r_xgb": row.get("pearson_r_xgb"),
        "pearson_r_squared_xgb": row.get("pearson_r_squared_xgb"),
        "model_agreement": row.get("model_agreement"),
        "delta_r2": row.get("delta_r2"),
        "pred_top_features_rf": top_rf,
        "pred_top_features_xgb": top_xgb,
        "pred_dominant_feature": top_feature_name,
        "pred_dominant_feature_class": row.get("dominant_feature_class"),
        "predictability_class": row.get("predictability_class"),
        "per_lineage_predictability": row.get("per_lineage_predictability") or [],
    }


def _load_takeda_palette(target_contracts_dir: Path):
    import matplotlib.pyplot as plt

    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette

    return takeda_palette


def emit_feature_importance_bar(
    summary: dict, target: str, out_dir: Path, target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS
) -> Path:
    """Multi-panel v2 figure: RF feature importance bar (primary) + optional
    XGBoost comparison + lineage-conditional r² tile. Falls back to a
    placeholder SVG when predictability_class is data_unavailable.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_feature_importance_bar.svg"

    if summary.get("predictability_class") == "data_unavailable":
        fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
        ax.text(
            0.5,
            0.55,
            f"{target} not in v2 predictability derived product",
            transform=ax.transAxes,
            ha="center",
            fontsize=10,
            color="#444",
        )
        ax.text(
            0.5, 0.45, summary.get("_remediation", ""), transform=ax.transAxes, ha="center", fontsize=8, color="#777"
        )
        ax.set_axis_off()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    top = summary.get("pred_top_features_rf") or []
    if not top:
        fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
        ax.text(0.5, 0.5, "No feature-importance data", transform=ax.transAxes, ha="center", fontsize=10, color="#666")
        ax.set_axis_off()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    # Top 10 importance-ranked (RF impurity; see module docstring on the _shap suffix)
    names = [t["feature"] for t in top]
    imps = [t["importance"] for t in top]
    classes = [t["feature_class"] for t in top]
    colors = [FEATURE_CLASS_COLORS.get(c, "#bbbbbb") for c in classes]

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.barh(range(len(names)), imps, color=colors, edgecolor="white")
    for i, imp in enumerate(imps):
        ax.text(imp + max(imps) * 0.01, i, f"{imp:.3f}", va="center", fontsize=8, color="#222")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("feature importance (RF impurity)")

    r_rf = summary.get("pearson_r_rf")
    r2_rf = summary.get("pearson_r_squared_rf")
    ci_lo = summary.get("pearson_r_squared_rf_ci_lo")
    ci_hi = summary.get("pearson_r_squared_rf_ci_hi")
    r2_txt = f"r²={r2_rf:.2f}" if isinstance(r2_rf, (int, float)) and r2_rf is not None else "r²=NA"
    if ci_lo is not None and ci_hi is not None:
        r2_txt += f" [95% CI {ci_lo:.2f}, {ci_hi:.2f}]"
    r_txt = f", r={r_rf:.2f}" if isinstance(r_rf, (int, float)) and r_rf is not None else ""
    pred_class = (summary.get("predictability_class") or "unknown").replace("_", " ")

    # XGBoost delta caveat: subtitle if divergent
    agreement = summary.get("model_agreement") or ""
    delta = summary.get("delta_r2")
    subtitle = ""
    if agreement == "divergent" and isinstance(delta, (int, float)):
        subtitle = f"  |  RF↔XGB divergent (Δr²={delta:+.2f})"

    ax.set_title(f"{target} — predictability ({r2_txt}{r_txt}, {pred_class}){subtitle}", fontsize=9)

    # Legend (unique feature classes)
    seen = []
    handles = []
    for c, color in zip(classes, colors):
        if c not in seen:
            seen.append(c)
            handles.append(plt.Rectangle((0, 0), 1, 1, color=color, label=c.replace("_", " ")))
    if handles:
        ax.legend(handles=handles, loc="lower right", fontsize=7, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_lineage_conditional_panel(
    summary: dict, target: str, out_dir: Path, target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS
) -> Path:
    """Per-lineage r² horizontal bar. Complement to the main importance figure.

    Ordered by r² descending; annotated with top-feature name. Highlights
    context-specific biomarker signals — e.g. WRN in MSI lineages, KRAS in
    Bowel/Pancreas.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_lineage_predictability.svg"

    lineage = summary.get("per_lineage_predictability") or []
    if not lineage:
        fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
        ax.text(0.5, 0.5, "No lineage-conditional data", transform=ax.transAxes, ha="center", fontsize=10, color="#666")
        ax.set_axis_off()
        fig.savefig(out_path)
        plt.close(fig)
        return out_path

    # Sort by r² descending
    lineage = sorted(lineage, key=lambda l: -(l.get("r2") or 0))[:12]
    names = [f"{l['lineage']} (n={l['n_cell_lines']})" for l in lineage]
    r2s = [l["r2"] for l in lineage]
    top_feats = [l.get("top_feature") or "" for l in lineage]
    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.barh(range(len(names)), r2s, color="#0a2540", edgecolor="white")
    for i, (r2, tf) in enumerate(zip(r2s, top_feats)):
        ax.text(r2 + max(max(r2s), 0.01) * 0.02, i, f"{r2:.2f}  ({tf})", va="center", fontsize=7, color="#333")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("Lineage-conditional r² (RF)")
    ax.set_title(f"{target} — lineage-conditional predictability")
    ax.axvline(0.16, color="#888", linestyle="--", linewidth=0.7)  # DepMap high-conf floor
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_plotly_specs(
    summary: dict, target: str, out_path: Path, contracts_root: Path = DEFAULT_TARGET_CONTRACTS
) -> list:
    """Emit interactive Plotly spec SIBLING to the feature-importance SVG (Gate-C plotly debt, 2026-07-21).

    Interactive twin of emit_feature_importance_bar: horizontal bar of the top-10 importance-ranked RF
    features (pred_top_features_rf), colored by feature_class (SAME FEATURE_CLASS_COLORS as the SVG),
    per-feature hover (name / class / importance), title with r² + 95% CI + predictability_class +
    RF↔XGB divergence caveat. Built from the SAME summary the SVG + v2 parquet use (no drift).
    Writes figure_feature_importance_bar.plotly.json. Best-effort (Plotly optional → SVG guaranteed);
    no feature data → no-op."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001 — Plotly optional; never block the SVG artifact
        print(f"[depmap_predictability] plotly spec emission skipped: {e}", file=sys.stderr)
        return []

    top = summary.get("pred_top_features_rf") or []
    if not top:
        return []  # no feature-importance data — SVG placeholder covers this state

    written = []
    try:
        # Reverse so the TOP importance feature sits at the top of the horizontal bar (mirrors invert_yaxis).
        top10 = list(top[:10])[::-1]
        names = [t["feature"] for t in top10]
        imps = [t["importance"] for t in top10]
        classes = [t["feature_class"] for t in top10]
        colors = [FEATURE_CLASS_COLORS.get(c, "#bbbbbb") for c in classes]
        fig = go.Figure(
            go.Bar(
                x=imps,
                y=list(range(len(names))),
                orientation="h",
                marker_color=colors,
                customdata=list(zip(names, classes)),
                hovertemplate="%{customdata[0]}<br>%{customdata[1]}<br>feature importance %{x:.3f}<extra></extra>",
            )
        )
        r2_rf = summary.get("pearson_r_squared_rf")
        ci_lo, ci_hi = (summary.get("pearson_r_squared_rf_ci_lo"), summary.get("pearson_r_squared_rf_ci_hi"))
        r2_txt = f"r²={r2_rf:.2f}" if isinstance(r2_rf, (int, float)) else "r²=NA"
        if ci_lo is not None and ci_hi is not None:
            r2_txt += f" [95% CI {ci_lo:.2f}, {ci_hi:.2f}]"
        pred_class = (summary.get("predictability_class") or "unknown").replace("_", " ")
        subtitle = ""
        if summary.get("model_agreement") == "divergent" and isinstance(summary.get("delta_r2"), (int, float)):
            subtitle = f"  |  RF↔XGB divergent (Δr²={summary['delta_r2']:+.2f})"
        fig.update_layout(
            title=f"{target} — predictability ({r2_txt}, {pred_class}){subtitle}",
            xaxis_title="feature importance (RF impurity)",
            yaxis=dict(tickmode="array", tickvals=list(range(len(names))), ticktext=names),
            template="plotly_white",
            showlegend=False,
            margin=dict(l=160, r=20, t=50, b=50),
        )
        (out_path / "figure_feature_importance_bar.plotly.json").write_text(fig.to_json())
        written.append(
            {"id": "feature_importance_bar", "path": "figure_feature_importance_bar.plotly.json", "type": "plotly"}
        )
    except Exception as e:  # noqa: BLE001
        print(f"[depmap_predictability] feature-importance plotly skipped: {e}", file=sys.stderr)

    return written


def emit_manifest(target: str, release_pin: str, summary: dict, out_dir: Path, parquet_uri: str) -> Path:
    import yaml

    manifest = {
        "method_id": "depmap-predictability",
        "method_version": METHOD_VERSION,
        "card_id": "dependency-predictability",
        "target": target,
        "release_pin": release_pin,
        "derived_product_uri": parquet_uri,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "predictability_class": summary.get("predictability_class"),
        "pearson_r_rf": summary.get("pearson_r_rf"),
        "pearson_r_squared_rf": summary.get("pearson_r_squared_rf"),
        "pearson_r_squared_rf_ci": [
            summary.get("pearson_r_squared_rf_ci_lo"),
            summary.get("pearson_r_squared_rf_ci_hi"),
        ],
        "model_agreement": summary.get("model_agreement"),
        "pred_dominant_feature_class": summary.get("pred_dominant_feature_class"),
    }
    out_file = out_dir / "manifest.yaml"
    with open(out_file, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return out_file


@click.command()
@click.option("--target", required=True, help="HGNC symbol")
@click.option(
    "--release-pin", default="26q1-v3", show_default=True, type=click.Choice(list(RELEASE_PIN_TO_PARQUET.keys()))
)
@click.option("--parquet-uri", default=None, help="Override the parquet URI (testing / local fixture).")
@click.option("--out", required=True, type=click.Path(file_okay=False, writable=True, path_type=Path))
def main(target, release_pin, parquet_uri, out):
    out.mkdir(parents=True, exist_ok=True)
    parquet_uri = parquet_uri or RELEASE_PIN_TO_PARQUET[release_pin]
    try:
        row = fetch_predictability_row(parquet_uri, target)
        summary = compute_summary(row, target)
    except Exception as e:
        summary = {
            "_live_read_error": "derived_product_read_failed",
            "_remediation": f"Could not read {parquet_uri}: {e}",
            "predictability_class": "data_unavailable",
            "pred_dominant_feature_class": "data_unavailable",
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_feature_importance_bar(summary, target, out)
    emit_lineage_conditional_panel(summary, target, out)
    emit_manifest(target, release_pin, summary, out, parquet_uri)
    click.echo(f"  -> {out}", err=True)


if __name__ == "__main__":
    main()
