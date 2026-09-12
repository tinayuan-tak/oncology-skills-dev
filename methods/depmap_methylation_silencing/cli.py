#!/usr/bin/env python3
"""depmap_methylation_silencing CLI — promoter-methylation → own-expression silencing compute.

The LoF/silencing analog of depmap_cis_dosage (which does amplification → over-expression). Computes the
cross-cell-line correlation between target T's OWN promoter methylation (CCLE RRBS TSS-1kb fractional
methylation) and its OWN log2(TPM+1) expression. A strong NEGATIVE correlation (high methylation → low
expression) is the epigenetic-SILENCING signature (MLH1/CDKN2A archetype) — the LoF cis leg the
amplification-driven cis-dosage card cannot see.

Pure compute over two loaded {ModelID -> value} dicts; the statistic (Spearman primary) mirrors
depmap_cis_dosage, with the coupling direction NEGATED (silencing = negative r).
"""

from __future__ import annotations

METHOD_VERSION = "0.2.0"

# --- classification thresholds (mirror cards/cellline-methylation-expression-coherence.card.yaml) ---
STRONG_SILENCING_SPEARMAN_R = -0.4  # silencing_coupled_strong (methylation ↓ expression)
MODERATE_SILENCING_SPEARMAN_R = -0.25  # silencing_coupled_moderate
SIGNIFICANCE_ALPHA = 0.01
MIN_CELL_LINES_FOR_CORRELATION = 50
# Methylation-variation floor → below this the gene is uniformly (un)methylated across the panel =
# untestable (methylation_invariant_panel). Keyed on the p90-p10 spread of the methylation fraction
# (tail-sensitive, per the cis-dosage ERBB2 calibration lesson): a gene silenced in only a subset still
# has a methylated tail that carries the correlation signal.
MIN_METHYL_P10_P90_SPREAD = 0.1  # methylation fraction is 0..1
# "Hypermethylated" cut for the subset contrast (fractional methylation).
HYPERMETHYLATION_THRESHOLD = 0.5
# Silencing is intrinsically a SUBSET phenomenon (most TSGs are silenced only in a subtype, e.g. MLH1
# in MSI/CIMP lines) — so the PRIMARY test is a hypermethylated-subset-vs-rest expression contrast
# (Mann-Whitney), like amp-expr's conjoint contrast, NOT a pan-panel correlation (which the minority
# tail dilutes). The pan-panel Spearman remains the path for BROADLY-methylated genes (e.g. MGMT).
# Power floor for the subset silencing contrast. Raised 10→20 (calibration finding 2026-09-12): an
# n=10 hypermethylated minority (ERBB2: 10/820 = 1.2% of the RRBS panel) is an underpowered Mann-Whitney
# and, for an amplification-driven oncogene, a lineage-confounded artifact (the 10 methylated lines are
# non-expressing lineages, not a targeted silencing) — it let ERBB2/MET-class amplicon drivers read a
# spurious silencing_coupled_strong. n>=20 (>=2.5% of the ~800-line RRBS panel) keeps every validated
# silenced TSG (MLH1 25, CDKN2A 52, MGMT 85) while dropping the fragile tail.
MIN_HYPERMETHYLATED = 20  # min hypermethylated lines to run the subset contrast
MIN_UNMETHYLATED_COMPARATOR = 30
STRONG_SILENCING_DELTA = -1.0  # median log2TPM (hyper - unmeth); strong under-expression
MODERATE_SILENCING_DELTA = -0.5

# --- LINEAGE-COLLAPSE guard (round-2 panel calibration 2026-09-12) ------------------------------------
# The subset contrast is an UNSTRATIFIED group comparison, so for a lineage-restricted gene the
# "hypermethylated" group is simply every lineage that does not express it — the delta then measures
# LINEAGE, not promoter silencing. Round-2 panel evidence (median log2TPM hyper-vs-unmethylated,
# pan-panel → pooled WITHIN-lineage, and the collapse ratio |within| / |pan|):
#   CDH1  -4.44 → -0.45  (ratio 0.10)   MET  -4.99 → -0.85 (0.17, dominant lineage 0.79)
#   FOXA1 -1.92 → -0.19  (0.10)         <- all three are lineage separation, not silencing
#   MLH1  -4.62 → -3.92  (0.85)   MGMT -3.36 → -2.81 (0.84)   CDKN2A -1.00 → -1.80 (1.80)
#   SOX10 (0.88)  <- the validated silenced genes all SURVIVE lineage conditioning
# A collapse ratio below MAX_LINEAGE_COLLAPSE_RATIO on a LARGE pan delta is therefore reported as
# silencing_lineage_confounded: measured, significant, and NOT interpretable as cis silencing. The guard
# only engages on large pan deltas (>= MIN_PAN_DELTA_FOR_COLLAPSE_CHECK) because a ratio computed on a
# small delta is noise-dominated, and the knife-edge moderates (RASSF1 0.43, MITF 0.46) are left alone.
MAX_LINEAGE_COLLAPSE_RATIO = 0.35
MIN_PAN_DELTA_FOR_COLLAPSE_CHECK = 1.0
MIN_PER_LINEAGE_SIDE = 3  # a lineage joins the within-lineage pooling only with >=3 lines a side

# EFFECT-SIZE FLOOR on the pan-panel correlation path (round-2 panel calibration 2026-09-12).
# The broad path was gated on the correlation ALONE (r <= -0.25, p <= 0.01) with no effect-size floor,
# so a large panel could turn a vanishing expression difference into silencing_coupled_moderate:
# AR/PRAD fired with a median hyper-vs-unmethylated delta of -0.075 log2TPM (and PDGFRA/GBM -0.15) —
# statistically significant, biologically vacuous, and it drove AR to a coherent_epigenetic_silencing
# verdict. The floor reads the methylation-QUARTILE contrast (top vs bottom quartile of methylation)
# because the broad path must remain available to genes with NO >0.5 hypermethylated subset at all.
MIN_BROAD_QUARTILE_DELTA = -0.5  # top-vs-bottom methylation quartile median log2TPM delta


def _within_lineage_delta(
    minority_vals, majority_vals, minority_lineages, majority_lineages, min_per_side: int = MIN_PER_LINEAGE_SIDE
):
    """Pooled WITHIN-lineage median delta (minority - majority), lineage-count-weighted.

    Mirrors depmap_cis_dosage.cli._within_lineage_delta (same contract, same threshold) — kept local so
    each method stays self-contained. Only lineages carrying >= min_per_side lines on BOTH sides
    contribute: a lineage present on one side only IS the confound. Returns
    (delta, n_lineages_contributing, dominant_lineage_fraction_of_minority), delta None when no lineage
    is jointly powered (the contrast is then wholly lineage-separated = uncontrollable).
    """
    from collections import defaultdict

    import numpy as np

    by_min, by_maj = defaultdict(list), defaultdict(list)
    for v, lin in zip(minority_vals, minority_lineages):
        by_min[lin].append(float(v))
    for v, lin in zip(majority_vals, majority_lineages):
        by_maj[lin].append(float(v))
    dom_frac = (max(len(v) for v in by_min.values()) / len(minority_vals)) if by_min else None
    deltas, weights = [], []
    for lin, vals in by_min.items():
        other = by_maj.get(lin, [])
        if len(vals) >= min_per_side and len(other) >= min_per_side:
            deltas.append(float(np.median(vals) - np.median(other)))
            weights.append(len(vals))
    if not deltas:
        return None, 0, dom_frac
    return float(np.average(deltas, weights=weights)), len(deltas), dom_frac


def compute_methylation_silencing(
    methyl_by_model: dict,
    tpm_by_model: dict,
    lineage_by_model: dict | None = None,
    strong_r: float = STRONG_SILENCING_SPEARMAN_R,
    moderate_r: float = MODERATE_SILENCING_SPEARMAN_R,
    significance_alpha: float = SIGNIFICANCE_ALPHA,
    min_cell_lines: int = MIN_CELL_LINES_FOR_CORRELATION,
    min_methyl_spread: float = MIN_METHYL_P10_P90_SPREAD,
    hypermethylation_threshold: float = HYPERMETHYLATION_THRESHOLD,
) -> dict:
    """Compute the cellline-methylation-expression-coherence summary_fields.

    Evaluated universe = lines with BOTH promoter methylation AND log2TPM present. methylation_silencing_class
    is driven by the methylation↔expression Spearman correlation; a uniformly-(un)methylated panel
    (methylation p90-p10 spread < min) is methylation_invariant_panel (untestable), NOT
    methylation_uncoupled. Higher methylation → lower expression = NEGATIVE r = silencing.

    `lineage_by_model` ({ModelID -> lineage}) is OPTIONAL and purely a CONTROL: when supplied, a large
    subset delta whose WITHIN-lineage counterpart collapses is reported as silencing_lineage_confounded
    instead of silencing_coupled_* (CDH1 -4.44 pan → -0.45 within lineage). When it is absent the classes
    are exactly as before.
    """
    import numpy as np
    from scipy import stats

    evaluated = sorted(set(methyl_by_model) & set(tpm_by_model))
    n = len(evaluated)

    def _base(cls: str, **extra) -> dict:
        out = {
            "n_cell_lines_evaluated": n,
            "methyl_expr_spearman_r": None,
            "methyl_expr_spearman_p": None,
            "methyl_expr_pearson_r": None,
            "methyl_expr_pearson_p": None,
            "methyl_expr_slope_log2tpm_per_methyl": None,
            "methylation_p10_p90_spread": None,
            "log2tpm_iqr": None,
            "median_methylation": None,
            "median_log2tpm": None,
            "n_hypermethylated": 0,
            "n_unmethylated": 0,
            "mean_log2tpm_hypermethylated": None,
            "mean_log2tpm_unmethylated": None,
            "delta_log2tpm_hyper_vs_unmethylated": None,  # mean-based (interpretability)
            "subset_median_delta_log2tpm": None,  # median-based (the subset class driver)
            "subset_mannwhitney_p": None,
            # lineage-collapse guard provenance (all None when no lineage labels are supplied)
            "subset_within_lineage_delta_log2tpm": None,
            "subset_n_lineages_compared": None,
            "hypermethylated_dominant_lineage_fraction": None,
            "lineage_collapse_ratio": None,  # |within-lineage delta| / |pan-panel delta|
            # effect-size floor on the broad path: top-vs-bottom methylation quartile median delta
            "broad_quartile_delta_log2tpm": None,
            "broad_quartile_within_lineage_delta_log2tpm": None,
            "silencing_driver": None,  # subset_hypermethylation | pan_panel_correlation
            "hypermethylation_threshold": float(hypermethylation_threshold),
            "methylation_silencing_class": cls,
        }
        out.update(extra)
        return out

    if n < min_cell_lines:
        return _base("data_unavailable")

    meth = np.array([methyl_by_model[m] for m in evaluated], dtype=float)
    tpm = np.array([tpm_by_model[m] for m in evaluated], dtype=float)

    m_p10, m_p90 = np.quantile(meth, [0.10, 0.90])
    tpm_q25, tpm_q75 = np.quantile(tpm, [0.25, 0.75])
    meth_spread = float(m_p90 - m_p10)
    tpm_iqr = float(tpm_q75 - tpm_q25)

    # Hypermethylated-vs-unmethylated expression contrast (interpretability aid; not the class driver).
    hyper_tpm = tpm[meth > hypermethylation_threshold]
    unmeth_tpm = tpm[meth <= hypermethylation_threshold]
    n_hyper = int(hyper_tpm.size)
    mean_hyper = float(hyper_tpm.mean()) if hyper_tpm.size else None
    mean_unmeth = float(unmeth_tpm.mean()) if unmeth_tpm.size else None
    delta = (mean_hyper - mean_unmeth) if (mean_hyper is not None and mean_unmeth is not None) else None

    n_unmeth = int(unmeth_tpm.size)
    common = dict(
        methylation_p10_p90_spread=meth_spread,
        log2tpm_iqr=tpm_iqr,
        median_methylation=float(np.median(meth)),
        median_log2tpm=float(np.median(tpm)),
        n_hypermethylated=n_hyper,
        n_unmethylated=n_unmeth,
        mean_log2tpm_hypermethylated=mean_hyper,
        mean_log2tpm_unmethylated=mean_unmeth,
        delta_log2tpm_hyper_vs_unmethylated=delta,
    )

    # Testable if EITHER a hypermethylated subset exists (n_hyper >= MIN_HYPERMETHYLATED — the subset
    # path, for subtype-silenced TSGs like MLH1) OR methylation varies broadly (p90-p10 spread — the
    # correlation path, for broadly-methylated genes like MGMT). Otherwise the panel is uniformly
    # (un)methylated → methylation_invariant_panel (untestable, honest; distinct from uncoupled).
    subset_testable = n_hyper >= MIN_HYPERMETHYLATED and n_unmeth >= MIN_UNMETHYLATED_COMPARATOR
    broad_testable = meth_spread >= min_methyl_spread and meth.std() > 1e-9
    if tpm.std() < 1e-9 or not (subset_testable or broad_testable):
        return _base("methylation_invariant_panel", **common)

    lineages = None
    if lineage_by_model:
        lineages = [str(lineage_by_model.get(m) or "unknown") for m in evaluated]

    # === PRIMARY: hypermethylated-subset-vs-rest contrast (silencing is a subset phenomenon) ===
    subset_p = None
    subset_delta_med = None
    subset_within = subset_n_lin = dom_frac = collapse_ratio = None
    hyper_mask = meth > hypermethylation_threshold
    if subset_testable:
        # one-sided Mann-Whitney: hypermethylated lines express LESS than the rest.
        hyper = tpm[hyper_mask]
        rest = tpm[~hyper_mask]
        try:
            _u, subset_p = stats.mannwhitneyu(hyper, rest, alternative="less")
            subset_p = float(subset_p)
        except ValueError:
            subset_p = None
        subset_delta_med = float(np.median(hyper) - np.median(rest))
        if lineages is not None:
            lin_hyper = [lin for lin, keep in zip(lineages, hyper_mask) if keep]
            lin_rest = [lin for lin, keep in zip(lineages, hyper_mask) if not keep]
            subset_within, subset_n_lin, dom_frac = _within_lineage_delta(hyper, rest, lin_hyper, lin_rest)
            if subset_within is not None and abs(subset_delta_med) > 1e-9:
                collapse_ratio = abs(subset_within) / abs(subset_delta_med)

    # Effect-size floor for the broad path: top-vs-bottom methylation quartile median delta. Computed
    # unconditionally (provenance) — it is the only effect size available when there is no >0.5 subset.
    # It carries the SAME lineage exposure as the subset contrast, so it gets the same within-lineage
    # control (ERBB2 has only 10 hypermethylated lines, so it reaches the class through THIS path:
    # quartile delta -2.70, r=-0.53 — a top-methylation quartile made of non-expressing lineages).
    broad_quartile_delta = broad_quartile_within = None
    m_q25, m_q75 = np.quantile(meth, [0.25, 0.75])
    hi_mask, lo_mask = meth >= m_q75, meth <= m_q25
    hi, lo = tpm[hi_mask], tpm[lo_mask]
    if hi.size and lo.size and m_q75 > m_q25:
        broad_quartile_delta = float(np.median(hi) - np.median(lo))
        if lineages is not None:
            lin_hi = [lin for lin, keep in zip(lineages, hi_mask) if keep]
            lin_lo = [lin for lin, keep in zip(lineages, lo_mask) if keep]
            broad_quartile_within, _bn, _bd = _within_lineage_delta(hi, lo, lin_hi, lin_lo)

    # === SECONDARY: pan-panel negative Spearman (broadly-methylated genes) ===
    spearman_r, spearman_p = stats.spearmanr(meth, tpm)
    pearson_r, pearson_p = stats.pearsonr(meth, tpm)
    try:
        slope = float(np.polyfit(meth, tpm, deg=1)[0])  # provenance-only; SVD can fail → None
    except (np.linalg.LinAlgError, ValueError):
        slope = None

    driver = None
    cls = "methylation_uncoupled"
    # Subset path takes precedence (the biologically-primary silencing test).
    if (
        subset_p is not None
        and subset_p <= significance_alpha
        and subset_delta_med is not None
        and subset_delta_med <= MODERATE_SILENCING_DELTA
    ):
        if (
            collapse_ratio is not None
            and abs(subset_delta_med) >= MIN_PAN_DELTA_FOR_COLLAPSE_CHECK
            and collapse_ratio < MAX_LINEAGE_COLLAPSE_RATIO
        ):
            # Measured and significant, but the effect COLLAPSES within lineage → it is lineage
            # separation (a non-expressing lineage is also a methylated lineage), not cis silencing.
            cls, driver = "silencing_lineage_confounded", "subset_hypermethylation"
        else:
            cls = (
                "silencing_coupled_strong"
                if subset_delta_med <= STRONG_SILENCING_DELTA
                else "silencing_coupled_moderate"
            )
            driver = "subset_hypermethylation"
    # Else the broad-correlation path — for genes with NO powered hypermethylated subset. Three changes
    # over v0.1.0, all round-2 panel calibration:
    #   (a) it is now a FALLBACK, not an alternative: when the subset contrast IS powered and FAILS the
    #       moderate floor, the direct test has answered and a diluted panel-wide correlation must not
    #       resurrect it (AR/PRAD: 164 hypermethylated lines, subset delta -0.08, yet r=-0.38 p<1e-25
    #       drove silencing_coupled_moderate and a coherent_epigenetic_silencing verdict);
    #   (b) it requires a real effect size (the methylation-quartile delta), not significance alone;
    #   (c) it gets the same lineage-collapse guard as the subset path.
    elif (
        not subset_testable
        and broad_testable
        and spearman_p == spearman_p
        and spearman_p <= significance_alpha
        and broad_quartile_delta is not None
        and broad_quartile_delta <= MIN_BROAD_QUARTILE_DELTA
    ):
        if (
            broad_quartile_within is not None
            and abs(broad_quartile_delta) >= MIN_PAN_DELTA_FOR_COLLAPSE_CHECK
            and abs(broad_quartile_within) / abs(broad_quartile_delta) < MAX_LINEAGE_COLLAPSE_RATIO
        ):
            cls, driver = "silencing_lineage_confounded", "pan_panel_correlation"
        elif spearman_r <= strong_r:
            cls, driver = "silencing_coupled_strong", "pan_panel_correlation"
        elif spearman_r <= moderate_r:
            cls, driver = "silencing_coupled_moderate", "pan_panel_correlation"

    return _base(
        cls,
        methyl_expr_spearman_r=(None if spearman_r != spearman_r else float(spearman_r)),
        methyl_expr_spearman_p=(None if spearman_p != spearman_p else float(spearman_p)),
        methyl_expr_pearson_r=(None if pearson_r != pearson_r else float(pearson_r)),
        methyl_expr_pearson_p=(None if pearson_p != pearson_p else float(pearson_p)),
        methyl_expr_slope_log2tpm_per_methyl=slope,
        subset_median_delta_log2tpm=subset_delta_med,
        subset_mannwhitney_p=subset_p,
        subset_within_lineage_delta_log2tpm=subset_within,
        subset_n_lineages_compared=subset_n_lin,
        hypermethylated_dominant_lineage_fraction=dom_frac,
        lineage_collapse_ratio=collapse_ratio,
        broad_quartile_delta_log2tpm=broad_quartile_delta,
        broad_quartile_within_lineage_delta_log2tpm=broad_quartile_within,
        silencing_driver=driver,
        **common,
    )
