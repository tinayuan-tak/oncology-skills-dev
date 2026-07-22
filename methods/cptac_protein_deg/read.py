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

# Per-SAMPLE product (cptac-protein-tumor-vs-normal-per-sample-v1): the per-aliquot
# log-ratios the per-cohort summary threw away. Backs the true tumor-vs-normal
# distribution boxplot + honest per-cohort statistics (Welch + Mann-Whitney). 129 MB,
# sorted by (gene_symbol, cohort) so a per-gene predicate-pushdown read prunes to a few
# row-groups. See data-catalog manifest cptac-protein-tumor-vs-normal-per-sample-v1.
PER_SAMPLE_MANIFEST_ID = "cptac-protein-tumor-vs-normal-per-sample-v1"
PER_SAMPLE_S3_KEY = (
    "data-catalog/derived/cptac-protein-tumor-vs-normal-per-sample-v1/"
    "cptac_protein_per_sample.parquet"
)
CACHE_PER_SAMPLE = CACHE_DIR / "cptac_protein_per_sample.parquet"

_DERIVED_STATUS: Optional[bool] = None
_PER_SAMPLE_STATUS: Optional[bool] = None

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
            # Distinguish "genuinely not published yet" (a definitive 404 / NoSuchKey) from a
            # TRANSIENT failure (expired STS creds, IAM propagation delay, network blip, throttling).
            # Only latch _DERIVED_STATUS = False on the definitive (absent-object) case — that safely
            # short-circuits every later call. For a transient error LEAVE _DERIVED_STATUS = None so a
            # later call retries instead of poisoning the whole process with a false data_unavailable.
            #
            # 403/AccessDenied is TRANSIENT, not definitive: expired session creds are the common
            # cause and surface as AccessDenied — latching False there degraded every subsequent read
            # to data_unavailable for the process lifetime even though re-auth would recover. Only a
            # true missing-object 404/NoSuchKey latches.
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (code in ("404", "NoSuchKey")
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


# --- per-sample distribution (per-sample product; backs the true boxplot) --------------------
# The per-cohort product above keeps only medians/effect/q; it CANNOT back a distribution plot.
# cptac-protein-tumor-vs-normal-per-sample-v1 persists the per-aliquot log-ratios so we can draw a
# real tumor-vs-normal boxplot AND recompute honest per-cohort statistics from the samples
# themselves (Welch's t on the log-ratios + a nonparametric Mann-Whitney U), rather than trusting a
# median dumbbell.

def _ensure_per_sample_cached() -> Optional[Path]:
    """Download + cache the per-sample product. Same definitive-vs-transient latch as the
    per-cohort loader: only latch False on a real 404/403 so a transient blip retries."""
    global _PER_SAMPLE_STATUS
    if _PER_SAMPLE_STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_PER_SAMPLE.exists() and CACHE_PER_SAMPLE.stat().st_size > 0:
        _PER_SAMPLE_STATUS = True
        return CACHE_PER_SAMPLE
    if _PER_SAMPLE_STATUS is None:
        try:
            s3 = _boto3_client()
            s3.download_file(S3_BUCKET, PER_SAMPLE_S3_KEY, str(CACHE_PER_SAMPLE))
            _PER_SAMPLE_STATUS = True
            return CACHE_PER_SAMPLE
        except Exception as e:
            # 403/AccessDenied is TRANSIENT (expired STS creds / IAM propagation), not a missing
            # object — only 404/NoSuchKey latches definitive-absent. See _ensure_derived_cached.
            resp = getattr(e, "response", None)
            code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
            definitive = (code in ("404", "NoSuchKey")
                          or e.__class__.__name__ in ("NoSuchKey", "404"))
            if definitive:
                _PER_SAMPLE_STATUS = False
            return None
    return None


def read_per_sample(target: str):
    """Per-aliquot CPTAC protein log-ratios for one target, all cohorts.

    Predicate-pushdown read (filter gene_symbol == target) on the (gene_symbol, cohort)-sorted
    per-sample parquet — prunes to a few row-groups instead of scanning 15M rows. Returns a
    DataFrame with columns (gene_symbol, cohort, aliquot_submitter_id, sample_type, condition,
    log2_ratio); empty DataFrame when the target is absent / product unavailable."""
    path = _ensure_per_sample_cached()
    if path is None:
        import pandas as pd
        return pd.DataFrame(columns=["gene_symbol", "cohort", "aliquot_submitter_id",
                                     "sample_type", "condition", "log2_ratio"])
    try:
        import pyarrow.parquet as pq
        sym = target.upper().strip()
        tbl = pq.read_table(str(path), filters=[("gene_symbol", "==", sym)])
        return tbl.to_pandas()
    except Exception:
        import pandas as pd
        return pd.DataFrame(columns=["gene_symbol", "cohort", "aliquot_submitter_id",
                                     "sample_type", "condition", "log2_ratio"])


def per_cohort_distribution_stats(target: str) -> list[dict]:
    """Per-cohort tumor-vs-normal distribution + honest statistics recomputed from the SAMPLES.

    For each cohort the target was quantified in, split the per-aliquot log-ratios into Tumor vs
    Normal and compute, FROM THE SAMPLES (not the summary product's precomputed q):
        - n_tumor / n_normal, tumor/normal median + quartiles (the boxplot geometry)
        - welch_p     Welch's t-test (unequal-variance), tumor vs normal log-ratios
        - mwu_p       Mann-Whitney U (nonparametric; robust to the log-ratio tails)
        - delta_median = tumor_median - normal_median
    Cohorts with <3 samples on either side are kept but their p-values are None (n too low to test)
    so the boxplot still shows the distribution honestly. Sorted by delta_median descending
    (most tumor-elevated first). Empty list when absent / unavailable.

    NOTE these p-values are per-cohort two-group tests on the SAMPLES — they will differ from the
    per-cohort product's MSstatsTMT limma-moderated q (different estimator); that is expected and
    the plot labels which test it used. This function is the plot's source of truth, self-consistent
    with the boxes it draws."""
    import numpy as np

    df = read_per_sample(target)
    if df is None or df.empty:
        return []

    def _quartiles(vals):
        a = np.asarray(vals, dtype=float)
        a = a[~np.isnan(a)]
        if a.size == 0:
            return (None, None, None, None, None)
        return (float(np.min(a)), float(np.percentile(a, 25)), float(np.median(a)),
                float(np.percentile(a, 75)), float(np.max(a)))

    out = []
    for cohort, sub in df.groupby("cohort"):
        tvals = sub.loc[sub["condition"] == "Tumor", "log2_ratio"].to_numpy(dtype=float)
        nvals = sub.loc[sub["condition"] == "Normal", "log2_ratio"].to_numpy(dtype=float)
        tvals = tvals[~np.isnan(tvals)]
        nvals = nvals[~np.isnan(nvals)]
        n_t, n_n = int(tvals.size), int(nvals.size)
        t_lo, t_q1, t_med, t_q3, t_hi = _quartiles(tvals)
        n_lo, n_q1, n_med, n_q3, n_hi = _quartiles(nvals)

        welch_p = mwu_p = None
        if n_t >= 3 and n_n >= 3:
            try:
                from scipy import stats as _st
                welch_p = float(_st.ttest_ind(tvals, nvals, equal_var=False).pvalue)
                mwu_p = float(_st.mannwhitneyu(tvals, nvals, alternative="two-sided").pvalue)
            except Exception:
                welch_p = mwu_p = None

        delta = (t_med - n_med) if (t_med is not None and n_med is not None) else None
        out.append({
            "cohort": str(cohort).upper(),
            "n_tumor": n_t, "n_normal": n_n,
            "tumor_min": t_lo, "tumor_q1": t_q1, "tumor_median": t_med,
            "tumor_q3": t_q3, "tumor_max": t_hi,
            "normal_min": n_lo, "normal_q1": n_q1, "normal_median": n_med,
            "normal_q3": n_q3, "normal_max": n_hi,
            "delta_median": delta,
            "welch_p": welch_p, "mwu_p": mwu_p,
            # raw arrays for the boxplot (kept out of any parquet emit; used only in-memory)
            "_tumor_values": tvals.tolist(), "_normal_values": nvals.tolist(),
        })

    out.sort(key=lambda r: (r["delta_median"] if r["delta_median"] is not None else -1e9),
             reverse=True)
    return out


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


# --- figure emitters (upgraded 2026-07-22: true distribution boxplots) -----------------------
# ORIGINALLY (Slice 7) this figure was a per-cohort DUMBBELL of tumor/normal MEDIANS, because the
# only product available was per-cohort SUMMARY (cptac-protein-tumor-vs-normal-per-cohort-v1). The
# per-SAMPLE product (cptac-protein-tumor-vs-normal-per-sample-v1) now persists the per-aliquot
# log-ratios, so we draw the honest figure the card originally wanted: a grouped tumor-vs-normal
# BOXPLOT per cohort, with per-cohort statistics (Welch's t + Mann-Whitney U) recomputed FROM THE
# SAMPLES the boxes are drawn from — no median-only dumbbell, no drift between the stat and the box.
# The figure id + path + emitter function names are unchanged so the card decl + skill dispatcher
# stay wired; only the content changed (dumbbell -> distribution).

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


def _sig_stars(p):
    """Significance stars from a p-value (Welch/MWU on the samples — NOT the summary q)."""
    if p is None or p != p:
        return ""
    if p < 1e-10:
        return "***"
    if p < 1e-4:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"


# Tumor = deep navy, Normal = muted blue (matches the dumbbell's palette so the color identity of
# "tumor" vs "normal" is stable across the protein cards).
_TUMOR_FILL, _TUMOR_LINE = "#1f4e79", "#0a2540"
_NORMAL_FILL, _NORMAL_LINE = "#a9c5db", "#5b7f99"


def emit_per_cohort_panel(target: str, out_dir: Path,
                          target_contracts_dir="/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts") -> Path:
    """Grouped tumor-vs-normal BOXPLOT per CPTAC cohort, drawn from the per-aliquot log-ratios
    (per-sample product), ordered by tumor-vs-normal median delta. Each cohort shows the true
    tumor + normal distributions side by side; the per-cohort Welch/Mann-Whitney significance
    (recomputed from the same samples) + n annotate each pair. Replaces the median-only dumbbell."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    _load_takeda_style(target_contracts_dir)
    out_dir = Path(out_dir)
    out_path = out_dir / "figure_protein_per_cohort_tumor_vs_normal.svg"
    stats = per_cohort_distribution_stats(target)
    if not stats:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, f"{target} — not quantified in any CPTAC cohort", ha="center",
                va="center", fontsize=10, color="#777"); ax.set_axis_off()
        fig.savefig(out_path); plt.close(fig); return out_path

    # most tumor-elevated (largest delta_median) at TOP → reverse for bottom-up y axis
    stats = list(reversed(stats))
    n_cohorts = len(stats)
    fig_h = min(max(3.2, n_cohorts * 0.62), 8.0)
    fig, ax = plt.subplots(figsize=(7.6, fig_h))

    # single shared annotation column (right of the widest whisker across ALL cohorts) so the
    # significance labels line up in a column instead of laddering per-row.
    ann_x = max([v for s in stats for v in (s["tumor_max"], s["normal_max"]) if v is not None]
                or [0]) + 0.15

    yticks, ylabels = [], []
    for i, s in enumerate(stats):
        y_t = i + 0.18   # tumor box (upper of the pair)
        y_n = i - 0.18   # normal box (lower)
        drew = False
        if s["_tumor_values"]:
            bp = ax.boxplot([s["_tumor_values"]], positions=[y_t], orientation="horizontal", widths=0.30,
                            patch_artist=True, showfliers=False, manage_ticks=False)
            bp["boxes"][0].set(facecolor=_TUMOR_FILL, edgecolor=_TUMOR_LINE, linewidth=1.1)
            for w in bp["whiskers"] + bp["caps"]:
                w.set(color=_TUMOR_LINE, linewidth=1.0)
            for m in bp["medians"]:
                m.set(color="white", linewidth=1.4)
            drew = True
        if s["_normal_values"]:
            bp = ax.boxplot([s["_normal_values"]], positions=[y_n], orientation="horizontal", widths=0.30,
                            patch_artist=True, showfliers=False, manage_ticks=False)
            bp["boxes"][0].set(facecolor=_NORMAL_FILL, edgecolor=_NORMAL_LINE, linewidth=1.1)
            for w in bp["whiskers"] + bp["caps"]:
                w.set(color=_NORMAL_LINE, linewidth=1.0)
            for m in bp["medians"]:
                m.set(color=_NORMAL_LINE, linewidth=1.4)
            drew = True
        if not drew:
            continue
        yticks.append(i)
        ylabels.append(f"{s['cohort']}\n(T={s['n_tumor']} N={s['n_normal']})")
        # significance annotation at the right margin — MWU preferred (nonparametric), Welch fallback
        p = s["mwu_p"] if s["mwu_p"] is not None else s["welch_p"]
        stars = _sig_stars(p)
        d = s["delta_median"]
        label = (f"Δ{d:+.2f} {stars}" if d is not None else stars)
        ax.text(ann_x, i, label, va="center", fontsize=7, color="#222")

    # legend proxies (two boxes)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor=_TUMOR_FILL, edgecolor=_TUMOR_LINE, label="tumor"),
                       Patch(facecolor=_NORMAL_FILL, edgecolor=_NORMAL_LINE, label="normal")],
              loc="lower right", fontsize=8, frameon=True)
    ax.axvline(0.0, color="#bbb", linewidth=0.8, linestyle="--", zorder=0)
    # extend the right limit so the shared annotation column is inside the axes (tight_layout
    # only accounts for artists inside the data limits; text beyond them would otherwise clip).
    ax.set_xlim(right=ann_x + 0.9)
    ax.set_yticks(yticks); ax.set_yticklabels(ylabels, fontsize=7)
    ax.set_xlabel("log2 tumor-vs-reference protein ratio (CPTAC TMT MS, per aliquot)")
    ax.set_title(f"{target} — tumor vs normal protein distribution, per CPTAC cohort "
                 f"(n={n_cohorts}; * MWU p<.05)")
    fig.tight_layout(); fig.savefig(out_path); plt.close(fig)
    return out_path


def emit_plot_data(target: str, out_dir: Path) -> Path:
    """Per-cohort distribution-statistics parquet (one row per cohort tested): n_tumor/n_normal,
    tumor/normal quartiles, delta_median, welch_p, mwu_p. The recomputed-from-samples stats behind
    the boxplot (raw per-aliquot arrays are NOT persisted here — the source-of-record for those is
    the per-sample product itself)."""
    import pandas as pd
    stats = per_cohort_distribution_stats(target)
    df = pd.DataFrame([{k: v for k, v in s.items() if not k.startswith("_")} for s in stats])
    out_file = Path(out_dir) / "plot_data_protein_per_cohort.parquet"
    df.to_parquet(out_file, index=False)
    return out_file


def emit_plotly_specs(target: str, out_dir: Path,
                      target_contracts_dir="/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts") -> list:
    """Interactive grouped tumor-vs-normal boxplot per cohort, built from the SAME
    per_cohort_distribution_stats (and their raw per-aliquot arrays) the SVG uses — no drift.
    Best-effort (plotly optional)."""
    try:
        import plotly.graph_objects as go
    except Exception as e:  # noqa: BLE001
        print(f"[cptac_protein_deg] plotly spec emission skipped: {e}", file=__import__("sys").stderr)
        return []
    stats = per_cohort_distribution_stats(target)
    if not stats:
        return []
    # most tumor-elevated first (top of the plot); plotly categorical y stacks bottom-up so reverse
    stats = list(reversed(stats))
    # per-cohort y labels; the Δmedian + MWU significance is surfaced via right-margin annotations
    # below (add_annotation), matching the SVG — so no per-point hovertext is accumulated here.
    cohorts = [f"{s['cohort']} (T={s['n_tumor']} N={s['n_normal']})" for s in stats]

    fig = go.Figure()
    # tumor + normal as two box traces; y = cohort label, x = per-aliquot log-ratio
    t_y, t_x, n_y, n_x = [], [], [], []
    for label, s in zip(cohorts, stats):
        t_x.extend(s["_tumor_values"]);  t_y.extend([label] * len(s["_tumor_values"]))
        n_x.extend(s["_normal_values"]); n_y.extend([label] * len(s["_normal_values"]))
    fig.add_trace(go.Box(x=n_x, y=n_y, name="normal", orientation="h",
                         marker_color=_NORMAL_LINE, fillcolor=_NORMAL_FILL,
                         line=dict(width=1), boxpoints=False))
    fig.add_trace(go.Box(x=t_x, y=t_y, name="tumor", orientation="h",
                         marker_color=_TUMOR_LINE, fillcolor=_TUMOR_FILL,
                         line=dict(width=1), boxpoints=False))
    # significance annotations at the right
    xr = max([v for s in stats for v in (s["tumor_max"], s["normal_max"]) if v is not None] or [0])
    for label, s in zip(cohorts, stats):
        p = s["mwu_p"] if s["mwu_p"] is not None else s["welch_p"]
        d = s["delta_median"]
        if d is None:
            continue
        fig.add_annotation(x=xr + 0.2, y=label, text=f"Δ{d:+.2f} {_sig_stars(p)}",
                           showarrow=False, font=dict(size=9), xanchor="left")
    fig.update_layout(title=f"{target} — tumor vs normal protein distribution, per CPTAC cohort",
                      xaxis_title="log2 tumor-vs-reference protein ratio (CPTAC TMT MS, per aliquot)",
                      boxmode="group", template="plotly_white",
                      margin=dict(l=140, r=70, t=50, b=50))
    (Path(out_dir) / "figure_protein_per_cohort_tumor_vs_normal.plotly.json").write_text(fig.to_json())
    return [{"id": "protein_per_cohort_tumor_vs_normal",
             "path": "figure_protein_per_cohort_tumor_vs_normal.plotly.json", "type": "plotly"}]
