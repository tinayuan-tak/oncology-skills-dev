"""depmap_cis_dosage.figures — cn_expression_scatter figure for cis-feature-expression-coherence.

Kept SEPARATE from cli.py (the compute) so the plotting deps (matplotlib) never load on the compute
path. Reuses depmap_expression_dependency's shared plot-style helper + the standard CN / expression
loaders — the emitter (compose-dashboard _emit_cis_feature_expression_coherence) recomputes via these
public helpers, mirroring _emit_card4. The figure the cis-dosage card was carrying as tracked viz-debt.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

from methods.target_id_sidecar import ensure_aws_profile


def load_cn_tpm_model(target: str, release_pin: str = "26q1") -> tuple[dict, dict, dict, list]:
    """Load relative CN + log2TPM + Model metadata for `target`. Returns
    (cn_by_model, tpm_by_model, model_metadata, load_errors). Mirrors the loaders the compute path
    (read_cis_dosage) uses, plus Model.csv for lineage colouring."""
    ensure_aws_profile()
    METHODS_REPO = Path(__file__).resolve().parent.parent.parent
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))

    from methods.depmap_cn_distribution import cli as cncli
    from methods.depmap_expression_distribution import cli as excli

    cn_by_model, _cn_meta, _assay, cn_errs = cncli.load_cn_files(release_pin=release_pin, target_symbol=target)
    if cn_errs or not cn_by_model:
        return {}, {}, {}, (cn_errs or [{"_live_read_error": "no_cn_for_target"}])
    tpm_by_model, _tpm_meta, tpm_errs = excli.load_expression_files(release_pin=release_pin, target_symbol=target)
    if tpm_errs or not tpm_by_model:
        return cn_by_model, {}, {}, (tpm_errs or [{"_live_read_error": "no_expression_for_target"}])

    try:
        from methods.depmap_common import load_model_csv

        model_df = load_model_csv(release_pin)
        id_col = "ModelID" if "ModelID" in model_df.columns else model_df.columns[0]
        model_metadata = {row[id_col]: row.to_dict() for _, row in model_df.iterrows()}
    except Exception:
        model_metadata = {}  # lineage colouring degrades to 'unknown'; scatter still renders

    return cn_by_model, tpm_by_model, model_metadata, []


def build_merged_data(cn_by_model: dict, tpm_by_model: dict, model_metadata: dict) -> list:
    """Per-cell-line long-format rows for the scatter + plot_data (evaluated = CN ∩ TPM)."""
    merged = []
    for mid in sorted(set(cn_by_model) & set(tpm_by_model)):
        meta = model_metadata.get(mid, {})
        lineage = meta.get("OncotreeLineage") or meta.get("lineage") or "unknown"
        merged.append(
            {
                "cell_line_id": mid,
                "cell_line_name": meta.get("CellLineName", mid),
                "relative_cn": float(cn_by_model[mid]),
                "tpm_logp1": float(tpm_by_model[mid]),
                "lineage": str(lineage),
            }
        )
    return merged


def emit_plot_data(merged: list, out_dir: Path) -> None:
    """Persist per_cell_line_cn_tpm_with_lineage.parquet (the card's declared plot_data)."""
    import pandas as pd

    out_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(merged).to_parquet(out_dir / "plot_data.parquet", index=False)


def emit_cn_expression_scatter(
    merged: list,
    target: str,
    indication: str,
    summary: dict,
    out_dir: Path,
    contracts_root: Path,
    amplification_threshold: float = 1.5,
) -> None:
    """Scatter of relative CN (x) vs log2TPM (y), lineage-coloured, OLS fit, amplification vline,
    annotated with Spearman r/p + slope. The cis-dosage plot the framework was missing."""
    from collections import Counter

    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from matplotlib.patches import Patch

    # Reuse the sibling's shared plot-style loader (mplstyle + palette) — one style source of truth.
    from methods.depmap_expression_dependency.cli import _setup_plot_style

    style = _setup_plot_style(contracts_root)

    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(merged)
    fig, ax = plt.subplots(figsize=style["FIGSIZE_DOUBLE_COLUMN"])
    if df.empty:
        ax.text(0.5, 0.5, "No data — see manifest", ha="center", va="center", transform=ax.transAxes, color="#666666")
        fig.savefig(out_dir / "figure_cn_expression_scatter.svg", bbox_inches="tight")
        plt.close(fig)
        return

    top_lineages = [lg for lg, _ in Counter(df["lineage"]).most_common(6)]
    for lg in top_lineages:
        sub = df[df["lineage"] == lg]
        ax.scatter(
            sub["relative_cn"],
            sub["tpm_logp1"],
            s=14,
            alpha=0.6,
            color=style["get_lineage_color"](lg),
            edgecolor="white",
            linewidth=0.3,
            zorder=2,
        )
    other = df[~df["lineage"].isin(top_lineages)]
    if not other.empty:
        ax.scatter(
            other["relative_cn"],
            other["tpm_logp1"],
            s=12,
            alpha=0.35,
            color="#CCCCCC",
            edgecolor="white",
            linewidth=0.2,
            zorder=1,
        )

    if len(df) >= 3 and df["relative_cn"].std() > 0:
        slope, intercept = np.polyfit(df["relative_cn"], df["tpm_logp1"], deg=1)
        xs = np.linspace(df["relative_cn"].min(), df["relative_cn"].max(), 50)
        ax.plot(xs, slope * xs + intercept, color="#444444", linewidth=1.5, alpha=0.85, zorder=3)

    ax.axvline(x=amplification_threshold, color="#B22222", linestyle="--", linewidth=1.0, alpha=0.7, zorder=1)
    ax.text(
        amplification_threshold,
        0.98,
        " focal-amp",
        fontsize=8,
        color="#B22222",
        ha="left",
        va="top",
        transform=ax.get_xaxis_transform(),
    )

    r, p = summary.get("cn_expr_spearman_r"), summary.get("cn_expr_spearman_p")
    n = summary.get("n_cell_lines_evaluated", len(df))
    cls = summary.get("cis_dosage_class", "")
    if r is not None:
        ax.text(
            0.97,
            0.03,
            f"n = {n}\nSpearman r = {r:.2f}\np = {p:.1e}\n{cls}",
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            family="monospace",
            bbox=dict(facecolor="white", edgecolor="#888888", alpha=0.92, pad=4, boxstyle="round,pad=0.4"),
            zorder=5,
        )

    if top_lineages:
        ax.legend(
            handles=[Patch(color=style["get_lineage_color"](lg), label=lg) for lg in top_lineages]
            + [Patch(color="#CCCCCC", label="other")],
            loc="upper left",
            framealpha=0.9,
            fontsize=8,
        )
    ax.set_xlabel("Relative copy-number (diploid ≈ 1.0)")
    ax.set_ylabel("Expression (log₂ TPM+1)")
    ax.set_title(f"{target}: cis-dosage (CN → own expression) across DepMap")
    ax.grid(axis="both", alpha=0.3)
    fig.savefig(out_dir / "figure_cn_expression_scatter.svg", bbox_inches="tight")
    plt.close(fig)


# ---- Offline render seam (figure-consolidation Stage 6) --------------------------------------------
_REQUIRED_COLUMNS = ("relative_cn", "tpm_logp1")


def render_from_plot_data(
    plot_data, summary: dict, out_dir, target: str, indication: "Optional[str]" = None, *, target_contracts_dir=None
) -> list:
    """Render the cis-feature-expression-coherence scatter OFFLINE from persisted plot_data
    (read_cis_dosage(plot_data_out=...)) — replays the merged CN×TPM frame into emit_cn_expression_scatter
    with NO second CN+expression load. Reference stats come from the passed `summary`."""
    import pandas as pd

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if target_contracts_dir is None:
        from methods.depmap_expression_dependency.cli import DEFAULT_TARGET_CONTRACTS

        target_contracts_dir = DEFAULT_TARGET_CONTRACTS

    df = plot_data if hasattr(plot_data, "columns") else pd.read_parquet(Path(plot_data))
    missing = [c for c in _REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"plot_data missing required columns {missing}; got {list(df.columns)}")
    merged = df.to_dict("records")

    emit_cn_expression_scatter(merged, target, indication, summary, out_dir, Path(target_contracts_dir))
    return [
        {
            "id": "cn_vs_expression_scatter",
            "path": "figure_cn_expression_scatter.svg",
            "type": "cn_expression_scatter",
            "primary": True,
        },
    ]
