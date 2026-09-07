#!/usr/bin/env python3
"""depmap-prism-crispr-concordance CLI (E7 — thin lookup on shared v4 parquet).

Reads ONE row from the frozen derived parquet
`s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v4/prism_activity_per_gene.parquet`
(SAME parquet as E6; different card exposing the concordance fields).

Three figure emitters:
  1. concordance_scatter (primary) — for each annotated compound with CRISPR
     data, a 2D scatter of rho_crispr vs rho_rnai. Named points; dashed
     reference lines at 0.10 (weak) and 0.30 (strong); triangulated quadrant
     shaded. Direct visual of triangulation strength.
  2. dual_responders_bar — horizontal bar of dual-responder cell lines
     (Chronos + best-compound LFC as paired bars), colored by lineage.
  3. concordance_vocab_panel — text card: class + best_rho_crispr +
     best_rho_rnai + n_dual_responders + top-3 dual responders.

Sign convention (worth re-stating on every card):
  Chronos ↓ = more CRISPR-dependent. RNAi ↓ = more KD-dependent. LFC ↓ =
  more compound-killed. Target-engaged: dependent-cells die from compound →
  the negatives correlate POSITIVELY → rho > 0 is concordant.
"""

from __future__ import annotations
import os

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
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)

# Release-pin → parquet URI. Shares E6's v4 parquet.
RELEASE_PIN_TO_PARQUET = {
    "prism-activity-v4": "s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v4/prism_activity_per_gene.parquet",
}

# Vocabulary mirrors precompute definitions.
CONCORDANCE_TRIANGULATED = "triangulated_target_engaged"
CONCORDANCE_CRISPR_CONFIRMED = "crispr_confirmed_engagement"
CONCORDANCE_RNAI_CONFIRMED = "rnai_confirmed_engagement"
CONCORDANCE_MIXED = "mixed_engagement"
CONCORDANCE_OFF_TARGET = "discordant_off_target_likely"
CONCORDANCE_THIN = "thin_evidence"
CONCORDANCE_DATA_UNAVAILABLE = "data_unavailable"

CONCORDANCE_STRONG_SPEARMAN = 0.30
CONCORDANCE_WEAK_SPEARMAN = 0.10


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    if p.scheme != "s3" or not p.netloc:
        raise ValueError(f"Not an S3 URI: {uri}")
    return p.netloc, p.path.lstrip("/")


def fetch_concordance_row(parquet_uri: str, gene: str) -> Optional[dict]:
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
    """Map parquet row → E7 summary_fields shape.

    Focus on concordance fields; deliberately NOT re-expose the E6 activity
    fields (which are the sibling card's responsibility). Only cross-reference
    via drug_name → compound_id lookup when we need to attach drug names to
    concordance entries for rendering.
    """
    if row is None:
        return {
            "crispr_prism_concordance_class": CONCORDANCE_DATA_UNAVAILABLE,
            "_data_note": (
                f"Target {target!r} has no PRISM-annotated compounds. "
                "No concordance analysis possible; distinct from a real "
                "'discordant' call — this is a first-in-class gap."
            ),
            "n_compounds_evaluated": 0,
            "per_compound_concordance": [],
            "best_spearman_r_crispr": None,
            "best_spearman_r_rnai": None,
            "n_dual_responders": 0,
            "dual_responders": [],
        }
    per_compound = row.get("per_compound_concordance") or []
    top_compounds = row.get("top_compounds") or []
    # Enrich concordance rows with drug_name from top_compounds (join on compound_id)
    cid_to_name = {c["compound_id"]: c["drug_name"] for c in top_compounds}
    enriched = []
    for c in per_compound:
        e = dict(c)
        e["drug_name"] = cid_to_name.get(c["compound_id"], c["compound_id"])
        enriched.append(e)
    crispr_rhos = [c["spearman_r_crispr"] for c in enriched if c.get("spearman_r_crispr") is not None]
    rnai_rhos = [c["spearman_r_rnai"] for c in enriched if c.get("spearman_r_rnai") is not None]
    dual = row.get("dual_responders") or []
    return {
        "crispr_prism_concordance_class": row.get("crispr_prism_concordance_class"),
        "n_compounds_evaluated": len(enriched),
        "per_compound_concordance": enriched,
        "best_spearman_r_crispr": max(crispr_rhos) if crispr_rhos else None,
        "best_spearman_r_rnai": max(rnai_rhos) if rnai_rhos else None,
        "n_dual_responders": len(dual),
        "dual_responders": dual,
    }


def _load_takeda_palette(target_contracts_dir: Path):
    import matplotlib.pyplot as plt

    style_path = target_contracts_dir / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(target_contracts_dir / "plot_styles"))
    import takeda_palette

    return takeda_palette


def _placeholder_svg(msg_lines: list[str], out_path: Path, pal) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    y = 0.7
    for line in msg_lines:
        ax.text(
            0.5,
            y,
            line,
            transform=ax.transAxes,
            ha="center",
            fontsize=10 if y == 0.7 else 8,
            color="#444" if y == 0.7 else "#777",
        )
        y -= 0.1
    ax.set_axis_off()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_concordance_scatter(
    summary: dict, target: str, out_dir: Path, target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS
) -> Path:
    """2D scatter: rho_crispr on x, rho_rnai on y. One point per compound.

    Quadrant coloring:
      - Upper-right (both ≥ 0.30): triangulated navy shading (target-engaged)
      - Right-only (CRISPR ≥ 0.30, RNAi < 0.30): light-blue (CRISPR-confirmed)
      - Upper-only (RNAi ≥ 0.30, CRISPR < 0.30): light-green (RNAi-confirmed)
      - Others: gray

    Dashed reference lines at 0.10 (weak) and 0.30 (strong) on both axes.
    Named point labels for top-K compounds by |rho|.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_concordance_scatter.svg"

    per_compound = summary.get("per_compound_concordance") or []
    if not per_compound:
        return _placeholder_svg(
            [
                f"{target} — no concordance data",
                "(no compounds cleared the intersection minimum, or gene absent from CRISPR/RNAi)",
            ],
            out_path,
            pal,
        )

    # Points
    points = [c for c in per_compound if c.get("spearman_r_crispr") is not None or c.get("spearman_r_rnai") is not None]
    if not points:
        return _placeholder_svg(
            [f"{target} — thin evidence", "insufficient cell-line intersections for correlation"], out_path, pal
        )

    xs = [c.get("spearman_r_crispr") if c.get("spearman_r_crispr") is not None else 0.0 for c in points]
    ys = [c.get("spearman_r_rnai") if c.get("spearman_r_rnai") is not None else 0.0 for c in points]

    def _color(x, y):
        s = CONCORDANCE_STRONG_SPEARMAN
        w = CONCORDANCE_WEAK_SPEARMAN
        if x >= s and y >= s:
            return "#0a2540"  # triangulated (navy)
        if x >= s:
            return "#7fa7c0"  # CRISPR-confirmed (light blue)
        if y >= s:
            return "#7fbb99"  # RNAi-confirmed (light green)
        if x >= w or y >= w:
            return "#f0a020"  # mixed (ochre)
        return "#bbbbbb"  # discordant (gray)

    colors = [_color(x, y) for x, y in zip(xs, ys)]

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    # Shade triangulated quadrant lightly
    ax.axhspan(
        CONCORDANCE_STRONG_SPEARMAN, 1.0, xmin=(CONCORDANCE_STRONG_SPEARMAN + 1) / 2, alpha=0.06, color="#0a2540"
    )
    # Reference lines
    for thresh in [CONCORDANCE_WEAK_SPEARMAN, CONCORDANCE_STRONG_SPEARMAN]:
        ax.axvline(thresh, color="#888", linestyle="--", linewidth=0.5)
        ax.axhline(thresh, color="#888", linestyle="--", linewidth=0.5)
    # Zero lines
    ax.axhline(0, color="#333", linewidth=0.5)
    ax.axvline(0, color="#333", linewidth=0.5)

    ax.scatter(xs, ys, c=colors, s=48, edgecolor="white", linewidth=0.6, zorder=3)
    # Label top compounds by |rho_crispr + rho_rnai|
    for c, x, y in sorted(zip(points, xs, ys), key=lambda t: -(abs(t[1]) + abs(t[2])))[:8]:
        drug = c.get("drug_name") or c.get("compound_id")
        ax.annotate(drug, (x, y), xytext=(4, 4), textcoords="offset points", fontsize=7, color="#333")

    ax.set_xlim(-0.5, 1.0)
    ax.set_ylim(-0.5, 1.0)
    ax.set_xlabel("Spearman ρ  vs  CRISPR Chronos  (per-line KO effect)")
    ax.set_ylabel("Spearman ρ  vs  RNAi DEMETER2  (per-line KD effect)")

    handles = [
        plt.Line2D([], [], marker="o", linestyle="", color="#0a2540", label="Triangulated (both ≥ 0.30)"),
        plt.Line2D([], [], marker="o", linestyle="", color="#7fa7c0", label="CRISPR-confirmed"),
        plt.Line2D([], [], marker="o", linestyle="", color="#7fbb99", label="RNAi-confirmed"),
        plt.Line2D([], [], marker="o", linestyle="", color="#f0a020", label="Mixed"),
        plt.Line2D([], [], marker="o", linestyle="", color="#bbbbbb", label="Discordant / off-target"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=6, framealpha=0.9)

    cls = summary.get("crispr_prism_concordance_class") or "unknown"
    n = summary.get("n_compounds_evaluated", 0)
    ax.set_title(f"{target} — chemical-genetic concordance ({n} compounds · {cls.replace('_', ' ')})", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_dual_responders_bar(
    summary: dict, target: str, out_dir: Path, target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS, top_k: int = 15
) -> Path:
    """Horizontal paired bars: for each dual-responder cell line, Chronos-dep
    (left, red-ish) and best-compound-LFC (right, navy). Sorted by CRISPR-dep
    magnitude descending.

    Placeholder when no dual responders.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_dual_responders_bar.svg"

    dual = summary.get("dual_responders") or []
    if not dual:
        return _placeholder_svg(
            [
                f"{target} — no dual-responder cell lines",
                "no line is both CRISPR-dependent AND compound-responsive above thresholds",
            ],
            out_path,
            pal,
        )

    top = dual[:top_k]
    labels = [f"{d['model_id']} ({d.get('lineage', 'Unknown')})" for d in top]
    chronos = [-d["chronos_dep"] for d in top]  # bar length = |Chronos| (larger = more dep)
    lfcs = [-d["best_compound_lfc"] for d in top]  # bar length = |LFC| (larger = more killed)
    compounds = [d.get("best_compound_id") or "" for d in top]

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    y = list(range(len(labels)))
    ax.barh(
        [yy + 0.20 for yy in y],
        chronos,
        height=0.35,
        color="#cf2828",
        label="CRISPR |Chronos| (KO dependency)",
        edgecolor="white",
    )
    ax.barh(
        [yy - 0.20 for yy in y],
        lfcs,
        height=0.35,
        color="#0a2540",
        label="Best compound |LFC| (chemical kill)",
        edgecolor="white",
    )
    for i, cid in enumerate(compounds):
        ax.text(max(max(lfcs), max(chronos)) * 0.02, i - 0.20, f" via {cid}", va="center", fontsize=6, color="#666")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("Magnitude (larger = more dependent / more killed)")
    ax.legend(loc="lower right", fontsize=7, framealpha=0.9)

    ax.set_title(f"{target} — dual-validated responder cell lines  (top {len(top)} of {len(dual)})", fontsize=9)
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_concordance_vocabulary_panel(
    summary: dict, target: str, out_dir: Path, target_contracts_dir: Path = DEFAULT_TARGET_CONTRACTS
) -> Path:
    """Text summary: class + best rhos + n_dual_responders + top-3 dual responders."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    pal = _load_takeda_palette(target_contracts_dir)
    out_path = out_dir / "figure_concordance_vocab_panel.svg"

    cls = summary.get("crispr_prism_concordance_class") or CONCORDANCE_DATA_UNAVAILABLE
    n = summary.get("n_compounds_evaluated", 0)
    best_c = summary.get("best_spearman_r_crispr")
    best_r = summary.get("best_spearman_r_rnai")
    n_dual = summary.get("n_dual_responders", 0)
    dual = summary.get("dual_responders") or []

    def _fmt(v):
        return f"{v:+.2f}" if isinstance(v, (int, float)) else "NA"

    lines = [
        f"{target}  ·  chemical-genetic concordance",
        "",
        f"class:               {cls.replace('_', ' ')}",
        f"n_compounds_eval:    {n}",
        f"best ρ vs CRISPR:    {_fmt(best_c)}",
        f"best ρ vs RNAi:      {_fmt(best_r)}",
        f"dual responders:     {n_dual}",
    ]
    for d in dual[:3]:
        lines.append(
            f"  {d['model_id']} ({d.get('lineage', '?')})  chronos={d['chronos_dep']:.2f}  LFC={d['best_compound_lfc']:.2f}"
        )

    color = {
        CONCORDANCE_TRIANGULATED: "#0a2540",
        CONCORDANCE_CRISPR_CONFIRMED: "#7fa7c0",
        CONCORDANCE_RNAI_CONFIRMED: "#7fbb99",
        CONCORDANCE_MIXED: "#f0a020",
        CONCORDANCE_OFF_TARGET: "#cf2828",
        CONCORDANCE_THIN: "#888888",
        CONCORDANCE_DATA_UNAVAILABLE: "#bbbbbb",
    }.get(cls, "#444")

    fig, ax = plt.subplots(figsize=pal.FIGSIZE_DOUBLE_COLUMN)
    y = 0.9
    for i, line in enumerate(lines):
        weight = "bold" if i == 0 else "normal"
        size = 11 if i == 0 else 9
        ax.text(
            0.05,
            y,
            line,
            transform=ax.transAxes,
            ha="left",
            fontsize=size,
            weight=weight,
            color=color if i == 0 else "#333",
            family="monospace" if i > 0 else "sans-serif",
        )
        y -= 0.09
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(out_path)
    plt.close(fig)
    return out_path


def emit_plotly_specs(
    summary: dict, target: str, out_path: Path, contracts_root: Path = DEFAULT_TARGET_CONTRACTS
) -> list:
    """Emit interactive Plotly spec SIBLING to the concordance-scatter SVG (Gate-C plotly debt, 2026-07-21).

    Interactive twin of emit_concordance_scatter: per-compound Spearman ρ vs CRISPR (x) vs RNAi (y),
    SAME quadrant coloring (triangulated navy / CRISPR-confirmed / RNAi-confirmed / mixed / discordant)
    keyed on CONCORDANCE_STRONG_SPEARMAN (0.30) + CONCORDANCE_WEAK_SPEARMAN (0.10), same reflines,
    per-compound hover (drug name). Built from the SAME summary['per_compound_concordance'] the SVG +
    the shared v4 parquet use (no drift). Writes figure_concordance_scatter.plotly.json.
    Best-effort (Plotly optional → SVG guaranteed); thin/absent evidence → no-op."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001 — Plotly optional; never block the SVG artifact
        print(f"[prism-crispr-concordance] plotly spec emission skipped: {e}", file=sys.stderr)
        return []

    per_compound = summary.get("per_compound_concordance") or []
    points = [c for c in per_compound if c.get("spearman_r_crispr") is not None or c.get("spearman_r_rnai") is not None]
    if not points:
        return []  # thin evidence / no data — SVG placeholder already covers this state

    written = []
    try:
        s, w = CONCORDANCE_STRONG_SPEARMAN, CONCORDANCE_WEAK_SPEARMAN

        def _color(x, y):
            if x >= s and y >= s:
                return "#0a2540"  # triangulated (navy)
            if x >= s:
                return "#7fa7c0"  # CRISPR-confirmed
            if y >= s:
                return "#7fbb99"  # RNAi-confirmed
            if x >= w or y >= w:
                return "#f0a020"  # mixed
            return "#bbbbbb"  # discordant

        xs = [c.get("spearman_r_crispr") if c.get("spearman_r_crispr") is not None else 0.0 for c in points]
        ys = [c.get("spearman_r_rnai") if c.get("spearman_r_rnai") is not None else 0.0 for c in points]
        colors = [_color(x, y) for x, y in zip(xs, ys)]
        drugs = [c.get("drug_name") or c.get("compound_id") or "?" for c in points]
        fig = go.Figure(
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers",
                marker=dict(color=colors, size=10, line=dict(width=0.6, color="white")),
                customdata=drugs,
                hovertemplate="%{customdata}<br>ρ CRISPR %{x:.2f} / ρ RNAi %{y:.2f}<extra></extra>",
            )
        )
        # threshold + zero reflines mirror the SVG (0.10 weak, 0.30 strong, on both axes; 0 axes).
        for t in (w, s):
            fig.add_vline(x=t, line=dict(color="#888888", dash="dash", width=1))
            fig.add_hline(y=t, line=dict(color="#888888", dash="dash", width=1))
        fig.add_vline(x=0, line=dict(color="#333333", width=1))
        fig.add_hline(y=0, line=dict(color="#333333", width=1))
        cls = (summary.get("crispr_prism_concordance_class") or "unknown").replace("_", " ")
        n = summary.get("n_compounds_evaluated", len(points))
        fig.update_layout(
            title=f"{target} — chemical-genetic concordance ({n} compounds · {cls})",
            xaxis_title="Spearman ρ vs CRISPR Chronos",
            yaxis_title="Spearman ρ vs RNAi DEMETER2",
            xaxis=dict(range=[-0.5, 1.0]),
            yaxis=dict(range=[-0.5, 1.0]),
            template="plotly_white",
            showlegend=False,
            margin=dict(l=60, r=20, t=50, b=50),
        )
        (out_path / "figure_concordance_scatter.plotly.json").write_text(fig.to_json())
        written.append(
            {"id": "concordance_scatter", "path": "figure_concordance_scatter.plotly.json", "type": "plotly"}
        )
    except Exception as e:  # noqa: BLE001
        print(f"[prism-crispr-concordance] scatter plotly skipped: {e}", file=sys.stderr)

    return written


def emit_manifest(target: str, release_pin: str, summary: dict, out_dir: Path, parquet_uri: str) -> Path:
    import yaml

    manifest = {
        "method_id": "depmap-prism-crispr-concordance",
        "method_version": METHOD_VERSION,
        "card_id": "prism-crispr-concordance",
        "target": target,
        "release_pin": release_pin,
        "derived_product_uri": parquet_uri,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "crispr_prism_concordance_class": summary.get("crispr_prism_concordance_class"),
        "n_compounds_evaluated": summary.get("n_compounds_evaluated"),
        "best_spearman_r_crispr": summary.get("best_spearman_r_crispr"),
        "best_spearman_r_rnai": summary.get("best_spearman_r_rnai"),
        "n_dual_responders": summary.get("n_dual_responders"),
    }
    out_file = out_dir / "manifest.yaml"
    with open(out_file, "w") as f:
        yaml.safe_dump(manifest, f, sort_keys=False)
    return out_file


@click.command()
@click.option("--target", required=True, help="HGNC symbol")
@click.option(
    "--release-pin",
    default="prism-activity-v4",
    show_default=True,
    type=click.Choice(list(RELEASE_PIN_TO_PARQUET.keys())),
)
@click.option("--parquet-uri", default=None, help="Override the parquet URI (for testing / local fixture).")
@click.option("--out", required=True, type=click.Path(file_okay=False, writable=True, path_type=Path))
def main(target, release_pin, parquet_uri, out):
    out.mkdir(parents=True, exist_ok=True)
    parquet_uri = parquet_uri or RELEASE_PIN_TO_PARQUET[release_pin]
    try:
        row = fetch_concordance_row(parquet_uri, target)
        summary = compute_summary(row, target)
    except Exception as e:
        summary = {
            "_live_read_error": "derived_product_read_failed",
            "_remediation": f"Could not read {parquet_uri}: {type(e).__name__}: {e}",
            "crispr_prism_concordance_class": CONCORDANCE_DATA_UNAVAILABLE,
            "n_compounds_evaluated": 0,
            "per_compound_concordance": [],
            "best_spearman_r_crispr": None,
            "best_spearman_r_rnai": None,
            "n_dual_responders": 0,
            "dual_responders": [],
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    emit_concordance_scatter(summary, target, out)
    emit_dual_responders_bar(summary, target, out)
    emit_concordance_vocabulary_panel(summary, target, out)
    emit_manifest(target, release_pin, summary, out, parquet_uri)
    click.echo(f"  -> {out}", err=True)


if __name__ == "__main__":
    main()
