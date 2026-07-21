"""cptac_protein_deg.read — CPTAC protein tumor-vs-normal DEG reader.

Consumer: protein-presence-cptac + surface-abundance-density evidence cards
(Phase A + F). Emits per-(target, cohort) protein-level tumor-vs-normal
differential expression stats from CPTAC-PDC mass-spec data (10 cohorts).

Cohorts: BRCA, CCRCC, COAD, GBM, HNSCC, LSCC, LUAD, OV, PDAC, UCEC.

Runtime discipline (v2, 2026-07-10):
  - Column-array iteration to build (cohort, gene) index (NOT df.iterrows —
    the pattern the kinome-atlas PR #7 refactored away from).
  - Lazy per-target row materialization: keep DataFrame in memory,
    materialize only the row(s) for a specific target at query time.
  - @lru_cache(maxsize=1) on load+index — cold path runs ONCE per process.
  - Module-level negative cache when derived not on S3.

Reads: derived parquet at
    s3://onc-compbio/data-catalog/derived/cptac-protein-tumor-vs-normal-per-cohort-v1/
Falls back to `data_unavailable` gracefully when derived product not on S3.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional


DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DERIVED_MANIFEST_ID = "cptac-protein-tumor-vs-normal-per-cohort-v1"
DERIVED_S3_KEY = (
    "data-catalog/derived/cptac-protein-tumor-vs-normal-per-cohort-v1/"
    "cptac_protein_deg.parquet"
)

CACHE_DIR = Path.home() / ".cache" / "framework-cptac"
CACHE_PARQUET = CACHE_DIR / "cptac_protein_deg.parquet"

_DERIVED_STATUS: Optional[bool] = None

# Indication → CPTAC cohort code mapping (some indications share codes)
INDICATION_TO_CPTAC = {
    "BRCA": "BRCA", "CCRCC": "CCRCC", "COAD": "COAD", "COADREAD": "COAD",
    "GBM": "GBM", "HNSC": "HNSCC", "HNSCC": "HNSCC",
    "LUSC": "LSCC", "LSCC": "LSCC",  # CPTAC uses LSCC for lung squamous
    "LUAD": "LUAD", "OV": "OV", "PAAD": "PDAC", "PDAC": "PDAC",
    "UCEC": "UCEC",
}


def _boto3_client():
    import boto3
    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


def _ensure_derived_cached() -> Optional[Path]:
    global _DERIVED_STATUS
    if _DERIVED_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_PARQUET.exists() and CACHE_PARQUET.stat().st_size > 0:
        _DERIVED_STATUS = True
        return CACHE_PARQUET
    if _DERIVED_STATUS is None:
        try:
            s3 = _boto3_client()
            s3.download_file(S3_BUCKET, DERIVED_S3_KEY, str(CACHE_PARQUET))
            _DERIVED_STATUS = True
            return CACHE_PARQUET
        except Exception as e:
            # Distinguish "genuinely not published yet" (a definitive 404 /
            # NoSuchKey / access-denied) from a TRANSIENT failure (expired
            # creds, network blip, throttling). Only latch _DERIVED_STATUS =
            # False on the definitive case — that safely short-circuits every
            # later call in the process. For a transient error, LEAVE
            # _DERIVED_STATUS = None so a subsequent call retries instead of
            # poisoning the whole process with a false data_unavailable.
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (code in ("404", "NoSuchKey", "403", "AccessDenied")
                          or e.__class__.__name__ in ("NoSuchKey", "404"))
            if definitive:
                _DERIVED_STATUS = False
            return None
    return None


@lru_cache(maxsize=1)
def _load_indexed():
    """Load derived parquet + build (cohort, gene) index + gene-only index.

    Returns (df, cohort_gene_idx, gene_idx):
        - df: pandas.DataFrame with all rows (~180K rows across 10 cohorts,
          fits trivially in memory).
        - cohort_gene_idx: dict[(cohort, gene_upper) -> row_index_in_df]
        - gene_idx: dict[gene_upper -> list[row_index_in_df]] (across cohorts)
        Empty structures if load failed.
    """
    path = _ensure_derived_cached()
    if path is None:
        import pandas as pd
        return pd.DataFrame(), {}, {}

    try:
        import pandas as pd
        df = pd.read_parquet(path)
    except Exception:
        import pandas as pd
        return pd.DataFrame(), {}, {}

    if df.empty:
        return df, {}, {}

    # Column-array iteration (NOT iterrows). Direct numpy access.
    cohort_gene_idx: dict[tuple, int] = {}
    gene_idx: dict[str, list[int]] = {}

    cohort_col = df["cohort"].values
    gene_col = df["gene_symbol"].values
    for idx in range(len(df)):
        cohort = str(cohort_col[idx]).strip().upper()
        gene = str(gene_col[idx]).strip().upper()
        if not cohort or not gene:
            continue
        cohort_gene_idx[(cohort, gene)] = idx
        gene_idx.setdefault(gene, []).append(idx)

    return df, cohort_gene_idx, gene_idx


def _row_to_summary(row: dict, matched_cohort: str) -> dict:
    return {
        "cohort": matched_cohort,
        "protein_expression_class": row.get("protein_expression_class", "ns"),
        "protein_effect_size": row.get("protein_effect_size"),
        "protein_bh_q_value": row.get("protein_bh_q_value"),
        "protein_p_value": row.get("protein_p_value"),
        "protein_median_log2_tumor": row.get("protein_median_log2_tumor"),
        "protein_median_log2_normal": row.get("protein_median_log2_normal"),
        "n_tumor_samples": row.get("n_tumor_samples"),
        "n_normal_samples": row.get("n_normal_samples"),
        "stat_test_used": row.get("stat_test_used", "msstatstmt_limma_ebayes_moderated"),
        "method_version": row.get("method_version", "1.0.0"),
        "_data_source": DERIVED_MANIFEST_ID,
    }


def _empty(note: str) -> dict:
    return {
        "cohort": None,
        "protein_expression_class": "data_unavailable",
        "protein_effect_size": None,
        "protein_bh_q_value": None,
        "protein_p_value": None,
        "protein_median_log2_tumor": None,
        "protein_median_log2_normal": None,
        "n_tumor_samples": None,
        "n_normal_samples": None,
        "stat_test_used": "skipped_low_n",
        "method_version": "1.0.0",
        "_data_note": note,
    }


def read_target_summary(target: str, indication: str = None) -> dict:
    """Per-target CPTAC protein tumor-vs-normal DEG summary.

    Args:
        target: HGNC gene symbol.
        indication: If given, restrict to the CPTAC cohort mapped from this
            indication. Otherwise return the largest-|effect_size| row
            across cohorts.
    """
    try:
        df, cohort_gene_idx, gene_idx = _load_indexed()
    except Exception as e:
        return _empty(f"cptac_load_failed: {type(e).__name__}: {e}")
    if df is None or df.empty:
        return _empty("cptac_data_unavailable")

    sym = target.upper().strip()

    # Resolve indication → CPTAC cohort
    cohort = None
    if indication:
        cohort = INDICATION_TO_CPTAC.get(indication.upper().strip())

    # Primary path: indication-specific lookup
    if cohort:
        idx = cohort_gene_idx.get((cohort, sym))
        if idx is None:
            return _empty(f"target_not_in_cptac_cohort_{cohort}")
        row = df.iloc[idx].to_dict()
        return _row_to_summary(row, matched_cohort=cohort)

    # Fallback: no indication or non-CPTAC indication → aggregate across
    # all cohorts, return "best-effect" row (largest |effect_size|)
    indices = gene_idx.get(sym, [])
    if not indices:
        return _empty("target_not_in_any_cptac_cohort")

    rows = df.iloc[indices].to_dict(orient="records")
    best_row = max(rows, key=lambda r: abs(float(r.get("protein_effect_size", 0) or 0)))
    return _row_to_summary(best_row, matched_cohort=str(best_row.get("cohort", "")).upper())


def read_all_cohorts(target: str) -> list[dict]:
    """Every CPTAC cohort row for a target — the per-cohort tumor-vs-normal panel data.

    The derived product is per-cohort SUMMARY statistics (no per-sample abundances), so this is the
    honest cross-cohort view: one record per cohort the target was tested in, sorted by effect size
    descending. Reused by (a) the per-cohort figure emitter, (b) the pan-cancer tumor_elevation_breadth
    measurement_type (Part 2). Empty list when the target is absent / product unavailable."""
    try:
        df, _cohort_gene_idx, gene_idx = _load_indexed()
    except Exception:
        return []
    if df is None or df.empty:
        return []
    indices = gene_idx.get(target.upper().strip(), [])
    if not indices:
        return []
    rows = [_row_to_summary(df.iloc[i].to_dict(),
                            matched_cohort=str(df.iloc[i]["cohort"]).strip().upper())
            for i in indices]
    rows.sort(key=lambda r: abs(float(r.get("protein_effect_size") or 0)), reverse=True)
    return rows


# --- tumor_elevation_breadth (Slice B1, 2026-07-21) ------------------------------------------
# A TARGET-GRAIN roll-up: "elevated in K of the N CPTAC cohorts this target was quantified in."
# CONTRACT NOTE: this is breadth over INDICATIONS for ONE target (allowed — precedent
# normal_tissue_protein_breadth), NOT a ranking over TARGETS (forbidden — the
# surfaceome-cohort-ranking non-goal, DATA_TO_SKILL_CONTRACT.md:467). It gives a target-ONLY
# query (no indication) a real pan-cancer tumor signal instead of falling back to cell-line-only.
#
# "Elevated" reuses the already-significance-gated per-cohort protein_expression_class: strong_up
# (q<0.05, effect>=1.5) or modest_up (q<0.05, 0.5<=effect<1.5). No new statistics — a count over
# the existing classes. Down/ns/data_unavailable cohorts are NOT elevated.

_ELEVATED_CLASSES = frozenset({"strong_up", "modest_up"})


def read_tumor_elevation_breadth(target: str) -> dict:
    """Pan-cancer tumor-elevation breadth for a target across all CPTAC cohorts.

    Built on read_all_cohorts (the per-cohort summary list). Returns a target-grain
    breadth summary:
        {
          tumor_elevation_breadth_class,   # categorical (drives rules)
          n_cohorts_tested,                # cohorts the target was quantified in
          n_cohorts_elevated,              # of those, class in {strong_up, modest_up}
          fraction_elevated,               # n_elevated / n_tested (None if n_tested == 0)
          median_effect_across_elevated,   # median protein_effect_size over elevated cohorts
          most_elevated_cohorts,           # [{cohort, protein_expression_class, protein_effect_size,
                                           #   protein_bh_q_value}] effect-desc, elevated only
          cohorts_tested,                  # sorted list of all cohort codes tested (provenance)
        }
    breadth_class ladder (default thresholds; interpretation lives in the card/rules but the
    class is computed here mirroring read_target_summary's protein_expression_class pattern):
        broadly_tumor_elevated  -> fraction_elevated >= 0.5 AND n_cohorts_elevated >= 3
        multi_tumor_elevated    -> n_cohorts_elevated >= 2
        single_tumor_elevated   -> n_cohorts_elevated == 1
        not_tumor_elevated      -> n_cohorts_tested >= 1 AND n_cohorts_elevated == 0
        data_unavailable        -> n_cohorts_tested == 0 (target absent / product unavailable)
    """
    rows = read_all_cohorts(target)
    n_tested = len(rows)
    if n_tested == 0:
        return {
            "tumor_elevation_breadth_class": "data_unavailable",
            "n_cohorts_tested": 0,
            "n_cohorts_elevated": 0,
            "fraction_elevated": None,
            "median_effect_across_elevated": None,
            "most_elevated_cohorts": [],
            "cohorts_tested": [],
        }

    elevated = [row for row in rows
                if row.get("protein_expression_class") in _ELEVATED_CLASSES]
    n_elevated = len(elevated)
    fraction = n_elevated / n_tested

    # median effect over the ELEVATED cohorts only (None when none elevated)
    median_effect = None
    if elevated:
        effs = sorted(float(row.get("protein_effect_size") or 0.0) for row in elevated)
        m = len(effs)
        median_effect = (effs[m // 2] if m % 2
                         else (effs[m // 2 - 1] + effs[m // 2]) / 2.0)

    if fraction >= 0.5 and n_elevated >= 3:
        cls = "broadly_tumor_elevated"
    elif n_elevated >= 2:
        cls = "multi_tumor_elevated"
    elif n_elevated == 1:
        cls = "single_tumor_elevated"
    else:
        cls = "not_tumor_elevated"

    # read_all_cohorts already sorts by |effect| desc; elevated preserves that order.
    most_elevated = [
        {"cohort": row.get("cohort"),
         "protein_expression_class": row.get("protein_expression_class"),
         "protein_effect_size": row.get("protein_effect_size"),
         "protein_bh_q_value": row.get("protein_bh_q_value")}
        for row in elevated
    ]

    return {
        "tumor_elevation_breadth_class": cls,
        "n_cohorts_tested": n_tested,
        "n_cohorts_elevated": n_elevated,
        "fraction_elevated": fraction,
        "median_effect_across_elevated": median_effect,
        "most_elevated_cohorts": most_elevated,
        "cohorts_tested": sorted(str(row.get("cohort")) for row in rows),
    }


# --- figure emitters (Slice 7 CPTAC protein viz) ---------------------------------------------
# The card declared `protein_boxplot_tumor_vs_normal` but the derived product is per-cohort SUMMARY,
# not per-sample — a true sample boxplot would require re-reading the 15 GB raw CPTAC-PDC matrix on
# every render. The honest, architecturally-correct figure from the summary product is a PER-COHORT
# tumor-vs-normal panel (dumbbell of tumor vs normal median per cohort + effect + q + n). Card figure
# declaration corrected to match (doc-truth, sibling target-contracts PR).

def _load_takeda_style(target_contracts_dir):
    import sys as _sys
    import matplotlib.pyplot as plt
    style_path = Path(target_contracts_dir) / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    _sys.path.insert(0, str(Path(target_contracts_dir) / "plot_styles"))
    try:
        import takeda_palette
        return takeda_palette
    except Exception:
        return None


def _sig_stars(q):
    if q is None or q != q:
        return ""
    if q < 1e-10:
        return "***"
    if q < 1e-4:
        return "**"
    if q < 0.05:
        return "*"
    return "ns"


def emit_per_cohort_panel(target: str, out_dir: Path,
                          target_contracts_dir="/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts") -> Path:
    """Dumbbell panel: per CPTAC cohort, tumor vs normal median log2 protein abundance, ordered by
    effect size; q-value stars annotate significance. The cross-cohort breadth of the target's
    tumor-elevated protein signal — the honest summary-level figure."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _load_takeda_style(target_contracts_dir)
    out_dir = Path(out_dir)
    out_path = out_dir / "figure_protein_per_cohort_tumor_vs_normal.svg"
    rows = read_all_cohorts(target)
    if not rows:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"{target} — not quantified in any CPTAC cohort", ha="center",
                va="center", fontsize=10, color="#777"); ax.set_axis_off()
        fig.savefig(out_path); plt.close(fig); return out_path

    # order by effect ascending so most-elevated is at top after invert
    rows = sorted(rows, key=lambda r: (r.get("protein_effect_size") or 0))
    labels = [r["cohort"] for r in rows]
    tum = [r.get("protein_median_log2_tumor") for r in rows]
    nor = [r.get("protein_median_log2_normal") for r in rows]
    fig_h = min(max(3.0, len(rows) * 0.4), 6.0)
    fig, ax = plt.subplots(figsize=(7, fig_h))
    for i, (t, n) in enumerate(zip(tum, nor)):
        if t is None or n is None:
            continue
        up = t >= n
        ax.plot([n, t], [i, i], color="#c9d1d9", linewidth=2, zorder=1)
        ax.scatter([n], [i], color="#7fa7c0", s=45, zorder=2, label="normal" if i == 0 else None)
        ax.scatter([t], [i], color="#0a2540" if up else "#cf2828", s=55, zorder=3,
                   label="tumor" if i == 0 else None)
        stars = _sig_stars(rows[i].get("protein_bh_q_value"))
        eff = rows[i].get("protein_effect_size")
        ax.text(max(t, n) + 0.1, i, f"{eff:+.2f} {stars}" if eff is not None else stars,
                va="center", fontsize=7, color="#222")
    ax.set_yticks(range(len(labels))); ax.set_yticklabels(labels, fontsize=8)
    ax.set_xlabel("median log2 protein abundance (CPTAC TMT MS)")
    ax.set_title(f"{target} — tumor vs normal protein, per CPTAC cohort (n={len(rows)} cohorts)")
    ax.legend(loc="lower right", fontsize=8)
    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_plot_data(target: str, out_dir: Path) -> Path:
    """Per-cohort long-format parquet (the honest plot_data: one row per cohort tested)."""
    import pandas as pd
    rows = read_all_cohorts(target)
    df = pd.DataFrame(rows)
    out_file = Path(out_dir) / "plot_data_protein_per_cohort.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_plotly_specs(target: str, out_dir: Path,
                      target_contracts_dir="/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts") -> list:
    """Interactive per-cohort dumbbell (tumor vs normal median per cohort) built from the SAME
    read_all_cohorts rows the SVG uses — no drift. Best-effort (plotly optional)."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        print(f"[cptac_protein_deg] plotly spec emission skipped: {e}", file=__import__("sys").stderr)
        return []
    rows = read_all_cohorts(target)
    if not rows:
        return []
    rows = sorted(rows, key=lambda r: (r.get("protein_effect_size") or 0))
    cohorts = [r["cohort"] for r in rows]
    tum = [r.get("protein_median_log2_tumor") for r in rows]
    nor = [r.get("protein_median_log2_normal") for r in rows]
    q = [r.get("protein_bh_q_value") for r in rows]
    fig = go.Figure()
    # connector lines
    for i, (t, n) in enumerate(zip(tum, nor)):
        if t is None or n is None:
            continue
        fig.add_shape(type="line", x0=n, x1=t, y0=cohorts[i], y1=cohorts[i],
                      line=dict(color="#c9d1d9", width=2))
    fig.add_trace(go.Scatter(x=nor, y=cohorts, mode="markers", name="normal",
                             marker=dict(color="#7fa7c0", size=10),
                             hovertemplate="%{y} normal median %{x:.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=tum, y=cohorts, mode="markers", name="tumor",
                             marker=dict(color="#0a2540", size=11),
                             customdata=[[qq if qq is not None else float('nan')] for qq in q],
                             hovertemplate="%{y} tumor median %{x:.2f}<br>q %{customdata[0]:.2e}<extra></extra>"))
    fig.update_layout(title=f"{target} — tumor vs normal protein, per CPTAC cohort",
                      xaxis_title="median log2 protein abundance (CPTAC TMT MS)",
                      template="plotly_white", margin=dict(l=90, r=40, t=50, b=50))
    (Path(out_dir) / "figure_protein_per_cohort_tumor_vs_normal.plotly.json").write_text(fig.to_json())
    return [{"id": "protein_per_cohort_tumor_vs_normal",
             "path": "figure_protein_per_cohort_tumor_vs_normal.plotly.json", "type": "plotly"}]
