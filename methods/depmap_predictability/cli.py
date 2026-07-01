#!/usr/bin/env python3
"""depmap-predictability CLI — E5 thin lookup card.

Reads ONE row out of the frozen derived parquet
`s3://onc-compbio/data-catalog/derived/depmap-predictability-26q1-v1/predictability_per_gene.parquet`
via pyarrow predicate pushdown (row_group_size=64). The parquet was produced by
the sibling precompute method (`depmap_predictability_precompute`) — see that
method's docstring for the training procedure.

No sklearn at runtime; this card is purely a row lookup + per-target SVG emission.
Wall-time target: < 500 ms (network read of one row group + tiny matplotlib bar).

Output bundle (in --out directory):
  - summary.json
  - figure_feature_importance_bar.svg  (primary)
  - manifest.yaml
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import click


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

DEFAULT_TARGET_CONTRACTS = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
)

# Default release-pin → parquet S3 URI. Versioning lives in the path; when v2
# ships, the card's required_inputs.release_pin bump points it at a new URI.
RELEASE_PIN_TO_PARQUET = {
    "26q1-v1": "s3://onc-compbio/data-catalog/derived/depmap-predictability-26q1-v1/predictability_per_gene.parquet",
}

# Color map for feature_class → SVG bar color. Mirrors VARIANT_CLASS_COLORS in E4.
FEATURE_CLASS_COLORS = {
    "own_expression":   "#0a2540",  # Takeda navy — own omics signature
    "own_copy_number":  "#7fa7c0",  # light blue
    "own_mut_hotspot":  "#cf2828",  # red — hotspot mutation
    "own_mut_damaging": "#f0a020",  # orange — LOF mutation
    "lineage":          "#888888",  # gray — context, not target-intrinsic
    "other":            "#dddddd",
    "unpredictable":    "#bbbbbb",
}


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    if p.scheme != "s3" or not p.netloc:
        raise ValueError(f"Not an S3 URI: {uri}")
    return p.netloc, p.path.lstrip("/")


def fetch_predictability_row(parquet_uri: str, gene: str) -> Optional[dict]:
    """Pyarrow predicate-pushdown read for ONE gene row.

    Returns the dict-formatted row, or None if the gene is absent from the
    parquet (downstream caller maps None → predictability_class=data_unavailable).
    """
    import pyarrow.parquet as pq
    if parquet_uri.startswith("s3://"):
        import pyarrow.fs as pafs
        bucket, key = _parse_s3_uri(parquet_uri)
        fs = pafs.S3FileSystem()
        path = f"{bucket}/{key}"
    else:
        fs = None
        path = parquet_uri
    table = pq.read_table(path, filesystem=fs,
                            filters=[("gene_symbol", "=", gene)])
    if table.num_rows == 0:
        return None
    if table.num_rows > 1:
        # Defensive: shouldn't happen for a per-gene-unique parquet, but if it
        # ever does we prefer to surface it explicitly rather than silently pick one.
        raise RuntimeError(f"Multiple rows for {gene!r}; parquet violated uniqueness")
    return {col: table[col][0].as_py() for col in table.column_names}


def compute_summary(row: Optional[dict], target: str) -> dict:
    """Map a parquet row → the card's outputs.summary_fields shape.

    When `row` is None (gene not in the precomputed product), emits a
    data_unavailable summary with the rationale exposed in `_remediation`.
    """
    if row is None:
        return {
            "_live_read_error": "target_not_in_derived_product",
            "_remediation": "Target not in v1 medium-scope precompute "
                              "(~500 dependency-mappable genes). Either the gene has "
                              "no lineage with |median Chronos| > 0.3, or it lacks "
                              "feature coverage. Will be re-evaluated in v2 (full genome).",
            "pred_n_cell_lines_evaluated": 0,
            "pred_r2": None,
            "pred_top_features": [],
            "pred_dominant_feature": None,
            "pred_dominant_feature_class": "data_unavailable",
            "predictability_class": "data_unavailable",
        }
    top = row.get("top_features") or []
    top_feature_name = top[0]["feature"] if top else None
    return {
        "pred_n_cell_lines_evaluated": int(row.get("n_cell_lines_evaluated") or 0),
        "pred_r2": float(row["predictability_r2"]) if row.get("predictability_r2") is not None else None,
        "pred_top_features": top,
        "pred_dominant_feature": top_feature_name,
        "pred_dominant_feature_class": row.get("dominant_feature_class"),
        "predictability_class": row.get("predictability_class"),
    }


def _load_takeda_palette(target_contracts_dir: Path):
    import matplotlib.pyplot as plt
    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette  # type: ignore
    return takeda_palette


def emit_feature_importance_bar(summary: dict, target: str,
                                   out_dir: Path,
                                   target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS) -> Path:
    """Horizontal bar chart of top-5 feature importances, colored by feature_class.

    Renders an explanatory subtitle that captures both the R² magnitude and the
    predictability_class — the card's two main scalars. When predictability is
    data_unavailable, emits a placeholder SVG with the explanatory message.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_feature_importance_bar.svg"

    if summary.get("predictability_class") == "data_unavailable":
        fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
        ax.text(0.5, 0.55, f"{target} not in precomputed predictability product (v1 medium-scope)",
                  transform=ax.transAxes, ha="center", fontsize=10, color="#444")
        ax.text(0.5, 0.45,
                  "Likely cause: no lineage with |median Chronos| > 0.3 or insufficient feature coverage",
                  transform=ax.transAxes, ha="center", fontsize=8, color="#777")
        ax.set_axis_off()
        fig.savefig(out_path); plt.close(fig)
        return out_path

    top = summary.get("pred_top_features") or []
    if not top:
        fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
        ax.text(0.5, 0.5, "No feature-importance data",
                  transform=ax.transAxes, ha="center", fontsize=10, color="#666")
        ax.set_axis_off()
        fig.savefig(out_path); plt.close(fig)
        return out_path

    # Top features come back sorted desc by importance. We display them top-to-bottom.
    names = [t["feature"] for t in top]
    imps = [t["importance"] for t in top]
    classes = [t["feature_class"] for t in top]
    colors = [FEATURE_CLASS_COLORS.get(c, "#bbbbbb") for c in classes]

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    ax.barh(range(len(names)), imps, color=colors, edgecolor="white")
    for i, imp in enumerate(imps):
        ax.text(imp + max(imps) * 0.01, i, f"{imp:.3f}",
                  va="center", fontsize=8, color="#222")
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=8)
    ax.invert_yaxis()  # most-important on top
    ax.set_xlabel("RandomForest feature importance")
    r2 = summary.get("pred_r2")
    r2_text = f"R²={r2:.2f}" if isinstance(r2, (int, float)) else "R²=NA"
    pred_class = (summary.get("predictability_class") or "unknown").replace("_", " ")
    ax.set_title(f"{target} — predictability ({r2_text}, class={pred_class})")

    # Legend for feature classes present in the top-5
    seen_classes = []
    handles = []
    for c, color in zip(classes, colors):
        if c not in seen_classes:
            seen_classes.append(c)
            handles.append(plt.Rectangle((0, 0), 1, 1, color=color, label=c.replace("_", " ")))
    if handles:
        ax.legend(handles=handles, loc="lower right", fontsize=7, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_manifest(target: str, release_pin: str, summary: dict,
                    out_dir: Path, parquet_uri: str) -> Path:
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
        "pred_r2": summary.get("pred_r2"),
        "pred_dominant_feature_class": summary.get("pred_dominant_feature_class"),
    }
    out_file = out_dir / "manifest.yaml"
    with open(out_file, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return out_file


@click.command()
@click.option("--target", required=True, help="HGNC symbol")
@click.option("--release-pin", default="26q1-v1", show_default=True,
              type=click.Choice(list(RELEASE_PIN_TO_PARQUET.keys())))
@click.option("--parquet-uri", default=None,
              help="Override the parquet URI (testing / local fixture). When unset, "
                    "resolves via --release-pin.")
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
    emit_manifest(target, release_pin, summary, out, parquet_uri)
    click.echo(f"  -> {out}", err=True)


if __name__ == "__main__":
    main()
