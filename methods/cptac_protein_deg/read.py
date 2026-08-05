"""cptac_protein_deg.read — CPTAC protein tumor-vs-normal DEG reader.

Consumer: tumor-protein-abundance-cptac + surface-abundance-density evidence cards
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


def _row_to_summary(row: dict, matched_cohort: str,
                    allgene_percentile: float = None,
                    allgene_percentile_class: str = "data_unavailable") -> dict:
    return {
        "cohort": matched_cohort,
        "protein_expression_class": row.get("protein_expression_class", "ns"),
        "protein_effect_size": row.get("protein_effect_size"),
        # All-gene percentile null (additive, display + companion categorical): where the
        # target's protein_effect_size falls among ALL genes tested in THIS cohort.
        "allgene_percentile": allgene_percentile,
        "allgene_percentile_class": allgene_percentile_class,
        "allgene_percentile_context": (f"cptac-protein-tumor-vs-normal cohort={matched_cohort} "
                                       f"metric=protein_effect_size") if matched_cohort else None,
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
        pct, pct_class = _allgene_effect_percentile(df, cohort, row.get("protein_effect_size"))
        return _row_to_summary(row, matched_cohort=cohort,
                               allgene_percentile=pct, allgene_percentile_class=pct_class)

    # Fallback: no indication or non-CPTAC indication → aggregate across
    # all cohorts, return "best-effect" row (largest |effect_size|)
    indices = gene_idx.get(sym, [])
    if not indices:
        return _empty("target_not_in_any_cptac_cohort")

    rows = df.iloc[indices].to_dict(orient="records")
    best_row = max(rows, key=lambda r: abs(float(r.get("protein_effect_size", 0) or 0)))
    best_cohort = str(best_row.get("cohort", "")).upper()
    pct, pct_class = _allgene_effect_percentile(df, best_cohort, best_row.get("protein_effect_size"))
    return _row_to_summary(best_row, matched_cohort=best_cohort,
                           allgene_percentile=pct, allgene_percentile_class=pct_class)


def _allgene_effect_percentile(df, cohort: str, effect_size):
    """Percentile of `effect_size` among ALL genes' protein_effect_size in this cohort.

    Context-matched by construction: the null is the cohort's own slice of the resident
    df (no pooling across cohorts). Zero new I/O — df is already in the lru_cache."""
    from percentile_null import percentile_rank, classify_percentile
    try:
        null_vals = df.loc[df["cohort"].str.upper() == cohort, "protein_effect_size"].tolist()
    except Exception:
        return None, "data_unavailable"
    pct = percentile_rank(effect_size, null_vals)
    return pct, classify_percentile(pct)


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


@lru_cache(maxsize=64)
def per_cohort_distribution_stats(target: str) -> list[dict]:
    """Per-cohort tumor-vs-normal distribution + honest statistics recomputed from the SAMPLES.

    Memoized (retrieval-opt #5): the three figure emitters (emit_per_cohort_panel / emit_plot_data /
    emit_plotly_specs) each call this independently, so a single card render recomputed the stats
    3x — including re-reading the per-sample product + re-running Welch/MWU. Cached on `target`;
    emitters treat the returned list read-only (they iterate to draw). cache_clear() in tests.

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


# --- surface-abundance-density (Tier 1.2, 2026-07-23) ----------------------------------------
# The surface-abundance-density card asks: "estimated surface copies-per-cell of {target} in
# {indication} tumors, above the TCE-viability threshold (>1,000/cell, Slaga 2018 Sci Transl Med)?"
#
# ⚠ EVIDENCE GRADE D — INFERRED, order-of-magnitude PRIOR. NOT a calibrated absolute anchor.
# (Domain-expert review 2026-07-23; see .claude/plans/surface-density-multi-anchor.md.) This function
# is the INTERIM v0.1: it unblocks the surface-modality-fit gate (its dispatcher errored with no method
# behind it) with an HONEST Level-D inference, pending the tiered-evidence rebuild (HPA graded IHC →
# CCLE/949 whole-cell priors → CSPA enrichment → a governed calibrated-flow ladder that alone sets the
# absolute scale). It DELIBERATELY does NOT claim the three things a real density model must earn:
#   (1) it is NOT a universal calibration — IHC intensity ≠ copies/cell (antibody affinity, epitope
#       accessibility, prep, dynamic range, scoring all confound); the copies numbers below are an
#       ORDER-OF-MAGNITUDE prior, reported with wide bands, never a cross-antibody quantitative claim;
#   (2) the CPTAC log2FC is applied as a coarse relative shift on a Level-D prior — NOT a calibrated
#       mapping of whole-proteome tumor abundance onto an absolute surface-copy scale;
#   (3) is_tce_viable / is_adc_high_payload_viable are WORKING-PRIOR calls against literature threshold
#       priors (Slaga 1,000 / 10,000), NOT biological GATES — real thresholds depend on affinity,
#       epitope, internalization, payload potency, DAR, linker, bystander, TCE geometry, CD3 affinity,
#       E:T ratio, heterogeneity (→ future modality_density_requirements format parameters).
# Every emitted estimate carries density_evidence_level='D'; a target with no anchor is level 'E'
# (expression evidence only, NO density estimate → surface_density_class 'unmeasured', never fabricated).
#
# WHY ONLY INFERRED. Neither substrate measures absolute surface copies/cell:
#   - CPTAC mass-spec (read_target_summary) = RELATIVE whole-proteome tumor-vs-normal log2 (a SHIFT).
#   - HPA IHC (hpa_normal_tissue_liability) = pathologist-scored intensity/breadth in NORMAL tissue.
# Both are Tier-4 PRIORS in the evidence model, not absolute anchors. The Level-D inference is:
#       copies_tumor  ~=  order_of_magnitude_prior(HPA IHC class)  x  2 ** (CPTAC log2FC)
# RANGED (lower/median/upper); when the prior weakens (no tissue-of-origin IHC, CPTAC-only) the BAND
# WIDENS so the card's `wide_uncertainty_band` warning fires — the estimate fails toward "confirm with
# calibrated flow", never toward a confident call.
#
# HPA does NOT ship per-tissue High/Med/Low IHC levels in the ingested master (that's the Phase-1A
# ingest); it ships (a) `Protein tissue distribution` (all/many/some/single) — breadth, and (b) a
# tissue-enriched NUMERIC intensity list over a closed 16-name vocabulary (~51% coverage). We map:
#   - the tumor tissue-of-origin's ENRICHED numeric intensity (when present) → an ordinal IHC class
#     via fixed percentiles (verified live 2026-07-23: p33 ~= 8e5, p66 ~= 7.4e6 → low/med/high);
#   - else the breadth class (all/many → medium; some/single → low; not detected → not_detected) — a
#     weaker prior → wider band.
# Each ordinal class maps to an ORDER-OF-MAGNITUDE copies/cell prior center + a multiplicative
# uncertainty factor (loosely from HER2/EGFR-family flow ranges; NOT a per-antibody calibration):
#   high ~= 3e5 (/12..x12), medium ~= 3e4 (/12..x12), low ~= 3e3 (/16..x16), not_detected ~= 3e2.
# The governed calibrated-flow ladder (Phase 2) will REPLACE these priors as the real absolute anchor.

# Indication (OncoTree-ish code) → HPA normal tissue-of-origin name (closed 16-name enriched vocab
# where possible; None when the tissue-of-origin is not in HPA's enriched list → breadth-only anchor).
_INDICATION_TO_HPA_TISSUE = {
    "COAD": "intestine", "COADREAD": "intestine", "READ": "intestine",
    "STAD": "stomach", "ESCA": "stomach",
    "PAAD": "pancreas", "PDAC": "pancreas",
    "LIHC": "liver", "CHOL": "liver",
    "LUAD": "lung", "LUSC": "lung", "LSCC": "lung", "NSCLC": "lung", "MESO": "lung",
    "KIRC": "kidney", "CCRCC": "kidney", "KIRP": "kidney", "KICH": "kidney",
    "OV": "ovary",
    "GBM": "cerebral cortex", "LGG": "cerebral cortex",
    "DLBCL": "lymphoid tissue", "AML": "bone marrow",
    "SKCM": "skin",
    # tissue-of-origin NOT in HPA's enriched vocabulary → breadth-only anchor (wider band):
    "BRCA": None, "UCEC": None, "HNSC": None, "HNSCC": None, "PRAD": None, "BLCA": None,
}

# IHC intensity class → (copies_per_cell CENTER, multiplicative uncertainty factor).
# CENTERs calibrated to HER2/EGFR-family surface-antigen flow-cytometry ranges (Nathanson 2018;
# Slaga 2018 Sci Transl Med >1,000/cell TCE threshold). The factor sets lower=center/f, upper=center*f.
_IHC_CLASS_CALIBRATION = {
    "high":         (3.0e5, 12.0),
    "medium":       (3.0e4, 12.0),
    "low":          (3.0e3, 16.0),   # straddles the 1,000/cell TCE threshold (wide by design)
    "not_detected": (3.0e2, 10.0),
}

# HPA enriched-intensity tertile cutoffs (verified live 2026-07-23: p33 8.05e5, p66 7.43e6 over
# n=14,311 enriched (tissue,intensity) pairs). A tissue-of-origin numeric intensity below p33 → low,
# below p66 → medium, else → high. Baked in (NOT recomputed at read time) so the class is stable.
_HPA_ENRICHED_P33 = 8.05e5
_HPA_ENRICHED_P66 = 7.43e6

# HPA breadth class → IHC anchor class (the weaker fallback when tissue-of-origin has no enriched
# numeric intensity). Broad presence ~= medium abundance; restricted ~= low; absent ~= not_detected.
_BREADTH_TO_IHC_CLASS = {
    "broad_normal_expression":      "medium",
    "moderate_normal_expression":   "low",
    "restricted_normal_expression": "low",
    "not_detected_in_normal":       "not_detected",
}

_TCE_VIABILITY_COPIES = 1000.0        # Slaga 2018 Sci Transl Med
_ADC_HIGH_PAYLOAD_COPIES = 10000.0

_DENSITY_METHOD_VERSION = "0.1.0"


def _density_class(copies: Optional[float]) -> str:
    """copies-per-cell → surface_density_class (card vocabulary), MEDIAN-driven.

    high     > 10,000/cell   moderate 1,000-10,000   low 100-1,000   very_low < 100
    """
    if copies is None:
        return "unmeasured"
    if copies > _ADC_HIGH_PAYLOAD_COPIES:
        return "high"
    if copies >= _TCE_VIABILITY_COPIES:
        return "moderate"
    if copies >= 100.0:
        return "low"
    return "very_low"


def _hpa_ihc_anchor(target: str, indication: Optional[str]) -> dict:
    """Resolve the HPA IHC calibration anchor for a target in the tumor tissue-of-origin.

    Returns {hpa_ihc_intensity_class, hpa_ihc_anchor_used, anchor_strength} where anchor_strength
    is 'tissue_specific' (strong — numeric enriched intensity in the tissue-of-origin),
    'breadth_only' (weak — no tissue-of-origin enriched value, fell back to distribution breadth),
    or 'unmeasured' (HPA has no call at all). Never raises — HPA read failure degrades to unmeasured.
    """
    try:
        from methods.hpa_normal_tissue_liability import cli as _hpa
        summary = _hpa.load_and_classify(target)
    except Exception:
        return {"hpa_ihc_intensity_class": "unmeasured",
                "hpa_ihc_anchor_used": None, "anchor_strength": "unmeasured"}

    breadth = summary.get("normal_tissue_breadth_class")
    if breadth in (None, "data_unavailable"):
        return {"hpa_ihc_intensity_class": "unmeasured",
                "hpa_ihc_anchor_used": None, "anchor_strength": "unmeasured"}

    # Strong anchor: the tumor tissue-of-origin appears in HPA's enriched (numeric-intensity) list.
    tissue = _INDICATION_TO_HPA_TISSUE.get((indication or "").upper().strip())
    if tissue:
        for t in (summary.get("specific_tissues") or []):
            if t.get("tissue") == tissue and t.get("intensity") is not None:
                v = float(t["intensity"])
                cls = ("low" if v < _HPA_ENRICHED_P33
                       else "medium" if v < _HPA_ENRICHED_P66 else "high")
                return {"hpa_ihc_intensity_class": cls,
                        "hpa_ihc_anchor_used": f"HPA enriched intensity in {tissue}",
                        "anchor_strength": "tissue_specific"}

    # Weak anchor: no tissue-of-origin enriched value → fall back to the distribution breadth class.
    cls = _BREADTH_TO_IHC_CLASS.get(breadth, "unmeasured")
    if cls == "unmeasured":
        return {"hpa_ihc_intensity_class": "unmeasured",
                "hpa_ihc_anchor_used": None, "anchor_strength": "unmeasured"}
    label = tissue or "distribution breadth (no tissue-of-origin map)"
    return {"hpa_ihc_intensity_class": cls,
            "hpa_ihc_anchor_used": f"HPA {breadth} ({label})",
            "anchor_strength": "breadth_only"}


def _empty_density(note: str) -> dict:
    """Honest unmeasured density card (no CPTAC coverage OR no HPA anchor).

    density_evidence_level='E' — expression evidence only, NO density estimate emitted (the honest
    floor of the evidence model; never a fabricated copies/cell number)."""
    return {
        "surface_density_class": "unmeasured",
        "density_evidence_level": "E",   # expression only; no density estimate
        "estimated_copies_per_cell_median": None,
        "estimated_copies_per_cell_lower": None,
        "estimated_copies_per_cell_upper": None,
        "hpa_ihc_anchor_used": None,
        "hpa_ihc_intensity_class": "unmeasured",
        "is_tce_viable": False,
        "is_adc_high_payload_viable": False,
        "method_version": _DENSITY_METHOD_VERSION,
        "_data_note": note,
    }


def _ladder_measurement(target: str, indication: Optional[str]) -> Optional[dict]:
    """If the governed absolute-density corpus has a MEASURED anchor for target, build the card summary
    from it (measured PRIMARY + the grade-D estimate retained as fallback context). Else None.

    Never raises — a missing ladder module / empty corpus / grade-E read all return None so the caller
    falls through to the HPA×CPTAC estimate. No fabrication: only a real admissible measurement wins."""
    try:
        from methods.surface_antigen_density_ladder import read_absolute_density
    except Exception:
        return None
    try:
        m = read_absolute_density(target, indication)
    except Exception:
        return None
    if not m or m.get("density_evidence_level") in (None, "E") or m.get("value_best") is None:
        return None

    density_class = m["absolute_density_class"]        # {high|moderate|low|very_low}
    grade = m["density_evidence_level"]                 # A | A- | B | B-
    # The grade-D HPA×CPTAC estimate is still computed + reported alongside (context, not the verdict).
    est = _hpa_cptac_estimate(target, indication)
    return {
        "surface_density_class": density_class,         # PRIMARY — now from a MEASURED anchor
        "density_evidence_level": grade,
        # measured absolute anchor (the promotion): value + unit + semantics + provenance
        "absolute_value_best": m["value_best"],
        "absolute_reported_unit": m["reported_unit"],
        "absolute_value_qualifier": m.get("value_qualifier_best"),
        "absolute_measurement_semantics": m.get("measurement_semantics_best"),
        "absolute_record_partition": m.get("record_partition_best"),
        "absolute_n_measurements": m.get("n_admissible_measurements"),
        "absolute_n_patient": m.get("n_patient"),
        "absolute_n_cell_line": m.get("n_cell_line"),
        # card viability flags — now backed by a measured value, not a working-prior
        "is_tce_viable": density_class in ("high", "moderate"),
        "is_adc_high_payload_viable": density_class == "high",
        # grade-D estimate retained as FALLBACK context (so both are visible; grade says which to trust)
        "estimated_copies_per_cell_median": est.get("estimated_copies_per_cell_median"),
        "estimated_copies_per_cell_lower": est.get("estimated_copies_per_cell_lower"),
        "estimated_copies_per_cell_upper": est.get("estimated_copies_per_cell_upper"),
        "hpa_ihc_anchor_used": est.get("hpa_ihc_anchor_used"),
        "hpa_ihc_intensity_class": est.get("hpa_ihc_intensity_class"),
        "method_version": _DENSITY_METHOD_VERSION,
        "_density_source": "governed_ladder",
        "_estimate_grade_d_class": est.get("surface_density_class"),
    }


def read_abundance_density_summary(target: str, indication: str = None) -> dict:
    """surface-abundance-density card: estimated surface copies-per-cell + TCE/ADC viability.

    Anchors an absolute copies-per-cell scale on the HPA IHC intensity for the tumor tissue-of-
    origin, then shifts it by the CPTAC tumor-vs-normal protein log2FC:
        median = anchor_center x 2 ** log2FC
    and widens the band when the anchor is weak (breadth-only) or CPTAC is absent (anchor-only),
    so the card's `wide_uncertainty_band` warning fires honestly rather than emitting false
    precision. `unmeasured` (never a fabricated number) when EITHER substrate is missing:
    no HPA anchor OR no CPTAC coverage in the tissue-matched cohort.

    Returns the surface-abundance-density card summary_fields contract:
        surface_density_class in {high, moderate, low, very_low, unmeasured}   (PRIMARY)
        estimated_copies_per_cell_{median, lower, upper}
        hpa_ihc_anchor_used, hpa_ihc_intensity_class
        is_tce_viable (class in {high, moderate}),  is_adc_high_payload_viable (class == high)
        method_version

    LADDER OVERRIDE (2026-07-23): if the governed absolute-density corpus
    (surface_antigen_density_ladder) has a MEASURED value for this target (evidence grade A patient /
    B cell-line, directly-calibrated flow / single-molecule counting), that measurement is PRIMARY —
    surface_density_class is set from it, density_evidence_level reflects the measured grade, and the
    absolute_* field group carries the measured value + unit + semantics + provenance. The HPA×CPTAC
    grade-D estimate is retained as the FALLBACK (and still reported alongside a measurement, so a
    consumer sees both). This is the tiered-evidence promotion: a real calibrated anchor overrides an
    inferred prior. No fabrication — an empty/held corpus simply falls through to the grade-D estimate.
    """
    ladder = _ladder_measurement(target, indication)
    if ladder is not None:
        return ladder

    return _hpa_cptac_estimate(target, indication)


def _surface_accessibility(target: str) -> dict:
    """SURFACE-ACCESSIBILITY tier for the grade-D estimate — a SOFT, NON-SUPPRESSING gate.

    The grade-D estimate derives from HPA×CPTAC WHOLE-CELL proteomics, which cannot distinguish an
    antibody-ACCESSIBLE surface antigen from an intracellular / inner-leaflet / secreted protein. A
    multiagent verification (2026-07-23) showed the surfaceome classifier's `is_surface_protein`
    boolean is unreliable BOTH ways — intracellular false-positives (NRAS/GAPDH/APC via HPA-substring)
    AND surface false-negatives at full confidence (STEAP1/TFRC/DR5/ENPP3 missed by SURFY+HPA). So it
    must NOT be a hard veto.

    Per the design principle (user, 2026-07-23): separate TARGET VISIBILITY from SURFACE-DENSITY
    ADMISSIBILITY. The whole-cell abundance estimate is ALWAYS retained; this function only labels
    whether that number may be called "surface density":
        admissible   — positive surface evidence (SURFY-positive OR HPA-plasma-membrane in the table)
        unsupported  — IN the table, but NO positive surface evidence (SURFY-neg AND HPA-neg): the
                       estimate is RETAINED but flagged not-a-surface-density (the NRAS case)
        provisional  — absent from the classifier table (coverage gap) OR any read error: absence is
                       NEVER negative evidence — the estimate stands, flagged provisional
    ⚠ INTERIM (schema v2): this uses only the CURRENT SURFY|HPA signals. The full spec (UniProt/
    Swiss-Prot topology + extracellular-domain requirement + CSPA + QuickGO, A–U tiers) is a separate
    ingestion program — until it lands, `unsupported` here is a WEAK signal (it will miss STEAP1-like
    topology-only surface antigens), so it DOWNGRADES, never suppresses. Never raises."""
    try:
        from methods.surfaceome_family_fusion import read_target_summary as _surf
        s = _surf(target)
    except Exception:
        return {"surface_density_admissibility": "provisional",
                "surface_accessibility_note": "surfaceome_read_error_absence_not_negative_evidence",
                "_surfaceome_family": None}
    if s.get("_data_note"):
        return {"surface_density_admissibility": "provisional",
                "surface_accessibility_note": "absent_from_surfaceome_table_coverage_gap_not_negative",
                "_surfaceome_family": None}
    positive = bool(s.get("source_surfy_positive")) or bool(s.get("source_hpa_plasma_membrane"))
    if positive:
        return {"surface_density_admissibility": "admissible",
                "surface_accessibility_note": "positive_surface_evidence_surfy_or_hpa_pm",
                "_surfaceome_family": s.get("surface_protein_family")}
    return {"surface_density_admissibility": "unsupported",
            "surface_accessibility_note": ("no_positive_surface_evidence_in_table_"
                                           "whole_cell_estimate_retained_not_a_surface_density"),
            "_surfaceome_family": s.get("surface_protein_family")}


def _hpa_cptac_estimate(target: str, indication: Optional[str] = None) -> dict:
    """The grade-D HPA-IHC × CPTAC-log2FC estimate (the fallback when the ladder has no measurement).

    Extracted so both the fallback path AND the ladder's alongside-context reuse one implementation.
    Order-of-magnitude prior, NOT a calibrated anchor — see read_abundance_density_summary docstring.

    SOFT surface-accessibility gate (NOT a veto): the estimate is always computed + returned, but
    tagged with `surface_density_admissibility` {admissible|unsupported|provisional} so a consumer
    knows whether a WHOLE-CELL-derived number may be treated as an antibody-accessible surface density.
    A non-surface target (KRAS) still gets its abundance estimate, but flagged `unsupported` — never
    silently zeroed (which would have discarded the observation AND risked suppressing a real
    STEAP1-like antigen the classifier under-calls). See _surface_accessibility."""
    access = _surface_accessibility(target)
    anchor = _hpa_ihc_anchor(target, indication)
    ihc_class = anchor["hpa_ihc_intensity_class"]
    if ihc_class == "unmeasured":
        out = _empty_density("no_hpa_ihc_anchor")
        out.update(access)
        return out

    center, base_factor = _IHC_CLASS_CALIBRATION[ihc_class]

    # CPTAC tumor shift (relative). read_target_summary returns the tissue-matched cohort row when an
    # indication maps to a cohort; else best-effect across cohorts. Missing coverage → anchor-only
    # (log2FC = 0) with a widened band, NOT unmeasured — the normal-tissue anchor alone is still an
    # audit-defensible first-pass, just less certain.
    cptac = read_target_summary(target, indication)
    log2fc = cptac.get("protein_effect_size")
    # A non-FINITE log2FC (inf/-inf/NaN) is a degenerate CPTAC value — inf arises when the normal-tissue
    # reference median is 0 (tumor-detected, normal-absent): meaningful biology, but nonsense as a 2**x
    # shift multiplier. Treat it as CPTAC-not-usable → anchor-only (shift=1) with the widened band, same
    # as the CPTAC-absent path. Guards STEAP1 (effect=inf → previously produced median=inf).
    import math
    _log2fc_finite = (log2fc is not None and math.isfinite(float(log2fc)))
    cptac_covered = (cptac.get("protein_expression_class") not in (None, "data_unavailable")
                     and _log2fc_finite)
    shift = (2.0 ** float(log2fc)) if cptac_covered else 1.0

    median = center * shift

    # Band width: base multiplicative factor, WIDENED when the evidence is thinner. A tissue-specific
    # HPA anchor + CPTAC coverage is the tightest; breadth-only or CPTAC-absent each widen it (they
    # compound), so a doubly-weak estimate has the widest, most-honest band.
    factor = base_factor
    if anchor["anchor_strength"] == "breadth_only":
        factor *= 1.6
    if not cptac_covered:
        factor *= 1.6

    lower = median / factor
    upper = median * factor

    density_class = _density_class(median)
    # Surface-density ADMISSIBILITY gates the VIABILITY calls + the surface class LABEL, but NEVER the
    # abundance numbers (which are always retained). `unsupported` = a whole-cell estimate that is not
    # a valid surface density → surface_density_class is relabeled and the TCE/ADC flags are False
    # (you cannot be surface-modality-viable on a number that isn't a surface density). `admissible` /
    # `provisional` keep the whole-cell class as the surface estimate (provisional = weaker confidence).
    admissibility = access["surface_density_admissibility"]
    if admissibility == "unsupported":
        surface_class = "not_surface_density_whole_cell_estimate"
        tce_viable = adc_viable = False
    else:
        surface_class = density_class
        tce_viable = density_class in ("high", "moderate")
        adc_viable = density_class == "high"
    return {
        "surface_density_class": surface_class,
        # Evidence grade D: INFERRED from whole-cell/tissue PRIORS (IHC + CPTAC), no direct surface
        # calibration. NOT a calibrated absolute anchor (that is level A/B/C — calibrated flow). The
        # copies numbers are an order-of-magnitude prior; is_tce/adc flags are WORKING-PRIOR calls.
        "density_evidence_level": "D",
        # whole-cell abundance estimate — ALWAYS retained (visibility != admissibility)
        "estimated_copies_per_cell_median": round(median, 1),
        "estimated_copies_per_cell_lower": round(lower, 1),
        "estimated_copies_per_cell_upper": round(upper, 1),
        "hpa_ihc_anchor_used": anchor["hpa_ihc_anchor_used"],
        "hpa_ihc_intensity_class": ihc_class,
        "is_tce_viable": tce_viable,
        "is_adc_high_payload_viable": adc_viable,
        # surface-accessibility soft gate (admissible | unsupported | provisional) + note + family
        **access,
        "method_version": _DENSITY_METHOD_VERSION,
        # provenance (leading underscore = not a card summary_field; for audit/debug only)
        "_whole_cell_class": density_class,   # the raw class before the admissibility relabel
        "_cptac_covered": cptac_covered,
        "_cptac_log2fc": log2fc if cptac_covered else None,
        "_cptac_cohort": cptac.get("cohort") if cptac_covered else None,
        "_anchor_strength": anchor["anchor_strength"],
        "_band_factor": round(factor, 2),
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
