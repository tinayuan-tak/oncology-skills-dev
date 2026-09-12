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

METHOD_VERSION = "0.1.0"

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


def compute_methylation_silencing(
    methyl_by_model: dict,
    tpm_by_model: dict,
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

    # === PRIMARY: hypermethylated-subset-vs-rest contrast (silencing is a subset phenomenon) ===
    subset_p = None
    subset_delta_med = None
    if subset_testable:
        # one-sided Mann-Whitney: hypermethylated lines express LESS than the rest.
        hyper = tpm[meth > hypermethylation_threshold]
        rest = tpm[meth <= hypermethylation_threshold]
        try:
            _u, subset_p = stats.mannwhitneyu(hyper, rest, alternative="less")
            subset_p = float(subset_p)
        except ValueError:
            subset_p = None
        subset_delta_med = float(np.median(hyper) - np.median(rest))

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
        cls = "silencing_coupled_strong" if subset_delta_med <= STRONG_SILENCING_DELTA else "silencing_coupled_moderate"
        driver = "subset_hypermethylation"
    # Else the broad-correlation path (only meaningful when methylation varies across the panel).
    elif broad_testable and spearman_p == spearman_p and spearman_p <= significance_alpha:
        if spearman_r <= strong_r:
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
        silencing_driver=driver,
        **common,
    )
