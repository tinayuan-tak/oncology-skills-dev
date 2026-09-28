#!/usr/bin/env python3
"""depmap_cn_dependency CLI — copy-number-stratified dependency compute.

Builds an amplified-vs-neutral boolean (relative CN > focal cut) and runs the shared single-boolean
Mann-Whitney stratified-dependency contrast (methods.depmap_common.boolean_stratification), so the
statistic and the strong/moderate/reverse tiering are identical to the fusion / amp-expr siblings and
the mutation path. This module owns only the CN-specific boolean and output field names.
"""

from __future__ import annotations

from onc_methods.depmap_common.boolean_stratification import (
    MIN_COMPARATOR_CELLS,
    MIN_POSITIVE_CELLS,
    MODERATE_EFFECT_DELTA,
    STRATIFICATION_ALPHA,
    STRONG_EFFECT_DELTA,
    StratificationLabels,
    classify_stratification,
    mannwhitney_stratification,
)

METHOD_VERSION = "0.1.0"

# DepMap relative CN (diploid ~ 1.0; ploidy-relative, NOT raw copies, NOT log2). The dependency
# amplified-arm uses a FOCAL HIGH-LEVEL cut (>= ~2x ploidy baseline), not a shallow arm-level gain:
# empirically (ERBB2, 26Q1) >2.0 flags 46 lines vs 95 at >1.5, and the extra 49 shallow gains dilute
# the amplification-addiction signal. The patient path is already GISTIC-focal-only; this matches it.
FOCAL_AMP_HIGH = 2.0

_LABELS = StratificationLabels(
    strong="amplified_strongly_dependent",
    moderate="amplified_moderately_dependent",
    reverse_strong="neutral_strongly_dependent",
    not_stratified="not_cn_stratified",
    insufficient="insufficient_amplification_rate",
)


def compute_cn_stratification(
    chronos_by_model: dict,
    cn_by_model: dict,
    focal_amp: float = FOCAL_AMP_HIGH,
    strong_effect_delta: float = STRONG_EFFECT_DELTA,
    moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
    stratification_alpha: float = STRATIFICATION_ALPHA,
    min_amplified: int = MIN_POSITIVE_CELLS,
    min_neutral: int = MIN_COMPARATOR_CELLS,
) -> dict:
    """Compute the copy-number-stratified-dependency summary_fields.

    Amplified boolean = relative CN > focal_amp; neutral = every other line (broad comparator).
    """
    amp_by_model = {m: (cn > focal_amp) for m, cn in cn_by_model.items()}
    res = mannwhitney_stratification(
        chronos_by_model, amp_by_model, min_positive=min_amplified, min_comparator=min_neutral
    )
    cls = classify_stratification(
        res,
        _LABELS,
        strong_effect_delta=strong_effect_delta,
        moderate_effect_delta=moderate_effect_delta,
        stratification_alpha=stratification_alpha,
    )
    q = res.get("p_value")  # single boolean -> single test -> q == p
    n_evaluated = len(set(chronos_by_model) & set(cn_by_model))
    return {
        "n_cell_lines_evaluated": int(n_evaluated),
        "n_amplified": res["n_mutant"],
        "n_neutral": res["n_wildtype"],
        "median_chronos_amplified": res["median_mutant"],
        "median_chronos_neutral": res["median_wildtype"],
        "delta_chronos_amplified_vs_neutral": res.get("delta_mut_vs_wt"),
        "cn_stratification_mannwhitney_p": res.get("p_value"),
        "cn_stratification_mannwhitney_q": q,
        "cn_stratification_mannwhitney_q_reverse": res.get("p_value_reverse"),
        "cn_stratification_effect_size": res.get("effect_size"),
        "amplification_threshold_relative_cn": float(focal_amp),
        "cn_stratification_class": cls,
        "_uncomputable": bool(res.get("_uncomputable")),
    }


# CN thresholds for strip plot categories (relative CN scale, diploid ~1.0)
DEEP_DEL = 0.5       # GISTIC ≤-2 (homozygous deletion)
SHALLOW_DEL = 0.92   # GISTIC -2 to -1 boundary
SHALLOW_GAIN = 1.5   # GISTIC 1 to 2 boundary (same as FOCAL_AMP in cn_distribution)
FOCAL_AMP = 2.0      # GISTIC ≥2 boundary (same as FOCAL_AMP_HIGH)


def _resolve_indication_lineage(indication: str) -> str | None:
    """Map indication code to DepMap OncotreeLineage value."""
    mapping = {
        "COADREAD": "Bowel", "COAD": "Bowel", "READ": "Bowel",
        "LUAD": "Lung", "LUSC": "Lung", "NSCLC": "Lung", "SCLC": "Lung",
        "BRCA": "Breast",
        "PAAD": "Pancreas", "PDAC": "Pancreas",
        "SKCM": "Skin", "MELANOMA": "Skin",
        "STAD": "Esophagus/Stomach", "ESCA": "Esophagus/Stomach", "GC": "Esophagus/Stomach",
        "PRAD": "Prostate",
        "OV": "Ovary/Fallopian Tube",
        "KIRC": "Kidney", "KIRP": "Kidney",
        "GBM": "CNS/Brain", "LGG": "CNS/Brain",
        "HNSC": "Head and Neck",
        "BLCA": "Bladder/Urinary Tract",
        "LIHC": "Liver",
        "UCEC": "Uterus",
        "LAML": "Myeloid", "AML": "Myeloid", "CML": "Myeloid",
        "DLBC": "Lymphoid",
    }
    return mapping.get(indication.upper())


def emit_cn_stratified_strip_plot(
    chronos_by_model: dict,
    cn_by_model: dict,
    target_symbol: str,
    summary: dict,
    out_path: "Path",
    contracts_root: "Path",
    *,
    model_metadata: dict = None,
    indication: str = None,
) -> list:
    """Emit two separate CN stratified strip plots: amplification and deletion.

    Amplification figure (figure_cn_amplification_strip.svg):
    - Focal amp (GISTIC >=2): relative CN > 2.0
    - Shallow gain (GISTIC 1-2): 1.5 < relative CN <= 2.0
    - No gain (GISTIC <=1): relative CN <= 1.5 (comparator)

    Deletion figure (figure_cn_deletion_strip.svg):
    - Deep del (GISTIC <=-2): relative CN < 0.5
    - Shallow del (GISTIC -2 to -1): 0.5 <= relative CN < 0.92
    - No del (GISTIC >=-1): relative CN >= 0.92 (comparator)

    Returns list of figure filenames created.
    """
    import sys
    from pathlib import Path

    import matplotlib.pyplot as plt
    import numpy as np

    out_path = Path(out_path)
    contracts_root = Path(contracts_root)

    style_path = contracts_root / "plot_styles" / "takeda_oncology.mplstyle"
    if style_path.exists():
        plt.style.use(str(style_path))
    sys.path.insert(0, str(contracts_root / "plot_styles"))
    try:
        from takeda_palette import (
            CHRONOS_STRONG_DEPENDENCY,
            FIGSIZE_DOUBLE_COLUMN,
            REFLINE_KILLER,
            REFLINE_NOMINAL,
        )
    except ImportError:
        CHRONOS_STRONG_DEPENDENCY = -0.5
        FIGSIZE_DOUBLE_COLUMN = (8.0, 5.5)
        REFLINE_KILLER = {"color": "#D62728", "linestyle": "--", "linewidth": 1.0, "alpha": 0.7}
        REFLINE_NOMINAL = {"color": "#888888", "linestyle": "-", "linewidth": 0.8, "alpha": 0.5}

    # Resolve indication lineage for highlighting
    indication_lineage = None
    if indication and model_metadata:
        indication_lineage = _resolve_indication_lineage(indication)

    if not chronos_by_model or not cn_by_model:
        return []

    rng = np.random.default_rng(seed=42)

    # Categorize models by CN status
    def get_cn_category(model_id):
        cn = cn_by_model.get(model_id)
        if cn is None:
            return None
        if cn < DEEP_DEL:
            return "deep_del"
        elif cn < SHALLOW_DEL:
            return "shallow_del"
        elif cn > FOCAL_AMP:
            return "focal_amp"
        elif cn > SHALLOW_GAIN:
            return "shallow_gain"
        else:
            return "neutral"

    # Build groups with model IDs for indication highlighting
    def build_group(label, category, color):
        if category == "no_gain":
            models = [m for m in chronos_by_model if m in cn_by_model and cn_by_model[m] <= SHALLOW_GAIN]
        elif category == "no_del":
            models = [m for m in chronos_by_model if m in cn_by_model and cn_by_model[m] >= SHALLOW_DEL]
        else:
            models = [m for m in chronos_by_model if get_cn_category(m) == category]
        scores = [chronos_by_model[m] for m in models]
        if indication_lineage and model_metadata:
            is_indication = [
                (model_metadata.get(m) or {}).get("OncotreeLineage") == indication_lineage
                for m in models
            ]
        else:
            is_indication = [False] * len(models)
        return label, models, scores, is_indication, color, category

    def get_scores_for_group(category):
        if category == "no_gain":
            models = [m for m in chronos_by_model if m in cn_by_model and cn_by_model[m] <= SHALLOW_GAIN]
        elif category == "no_del":
            models = [m for m in chronos_by_model if m in cn_by_model and cn_by_model[m] >= SHALLOW_DEL]
        else:
            models = [m for m in chronos_by_model if get_cn_category(m) == category]
        scores_pan = [chronos_by_model[m] for m in models]
        scores_ind = [chronos_by_model[m] for m in models
                      if (model_metadata.get(m) or {}).get("OncotreeLineage") == indication_lineage] if indication_lineage else []
        return scores_pan, scores_ind

    def compute_median(scores):
        return float(np.median(scores)) if scores else None

    def compute_qvalue(test_scores, comparator_scores):
        from scipy import stats as scipy_stats
        if len(test_scores) >= 3 and len(comparator_scores) >= 3:
            try:
                _, p = scipy_stats.mannwhitneyu(test_scores, comparator_scores, alternative='less')
                return p
            except Exception:
                pass
        return None

    def fmt_med(v):
        return f"{v:.2f}" if v is not None else "—"

    def fmt_q(v):
        return f"{v:.1e}" if v is not None else "—"

    def plot_strip(ax, groups, title):
        for i, (label, models, scores, is_ind, color, category) in enumerate(groups):
            if not scores:
                ax.axvline(x=i, color="#EEEEEE", linewidth=20, alpha=0.3, zorder=0)
                continue

            scores_arr = np.array(scores)
            is_ind_arr = np.array(is_ind)
            xs = i + rng.uniform(-0.25, 0.25, size=len(scores_arr))

            if indication_lineage:
                non_ind_mask = ~is_ind_arr
                if np.any(non_ind_mask):
                    ax.scatter(xs[non_ind_mask], scores_arr[non_ind_mask], s=30, alpha=0.4,
                               color=color, edgecolor="white", linewidth=0.3, zorder=2)
                ind_mask = is_ind_arr
                if np.any(ind_mask):
                    ax.scatter(xs[ind_mask], scores_arr[ind_mask], s=50, alpha=0.9,
                               color=color, edgecolor="black", linewidth=0.8, zorder=3)
                med_all = float(np.median(scores_arr))
                ax.plot([i - 0.35, i + 0.35], [med_all, med_all], color="#222222",
                        linewidth=2.0, zorder=4, linestyle="-")
                if np.any(ind_mask):
                    med_ind = float(np.median(scores_arr[ind_mask]))
                    ax.plot([i - 0.35, i + 0.35], [med_ind, med_ind], color="#222222",
                            linewidth=2.0, zorder=5, linestyle="--")
            else:
                ax.scatter(xs, scores_arr, s=14, alpha=0.55, color=color, edgecolor="white", linewidth=0.3, zorder=2)
                med = float(np.median(scores_arr))
                ax.plot([i - 0.35, i + 0.35], [med, med], color="#222222", linewidth=1.5, zorder=3)

        ax.axhline(y=0, **REFLINE_NOMINAL, zorder=1)
        ax.axhline(y=CHRONOS_STRONG_DEPENDENCY, **REFLINE_KILLER, zorder=1)
        ax.set_xticks(range(len(groups)))
        ax.set_xticklabels([label for label, _, _, _, _, _ in groups], fontsize=9)
        ax.set_ylabel("Chronos score (more dependent = lower)")
        cls = summary.get("cn_stratification_class", "?")
        ax.set_title(f"{target_symbol}: {title}  ({cls})")
        ax.grid(axis="y")

    figures_created = []
    base_figsize = FIGSIZE_DOUBLE_COLUMN if isinstance(FIGSIZE_DOUBLE_COLUMN, tuple) else (8.0, 5.5)

    # === AMPLIFICATION FIGURE ===
    amp_groups = [
        build_group("focal\namp\n(>=+2)", "focal_amp", "#B22222"),      # Dark red
        build_group("shallow\ngain\n(+1 to +2)", "shallow_gain", "#E69F00"),  # Orange
        build_group("no\ngain\n(<=+1)", "no_gain", "#888888"),          # Gray (comparator)
    ]

    fig_height = base_figsize[1] + 1.5 if indication_lineage else base_figsize[1]
    fig, ax = plt.subplots(figsize=(base_figsize[0], fig_height))
    plot_strip(ax, amp_groups, "amplification dependency")

    if indication_lineage and indication:
        focal_pan, focal_ind = get_scores_for_group("focal_amp")
        shallow_gain_pan, shallow_gain_ind = get_scores_for_group("shallow_gain")
        no_gain_pan, no_gain_ind = get_scores_for_group("no_gain")

        amp_col_labels = ["Amplification", "Median\n(Focal)", "Median\n(Shallow)", "Median\n(No Gain)",
                          "q (Focal)", "q (Shallow)", ""]
        amp_table_data = [
            ["Pan-DepMap", fmt_med(compute_median(focal_pan)), fmt_med(compute_median(shallow_gain_pan)),
             fmt_med(compute_median(no_gain_pan)), fmt_q(compute_qvalue(focal_pan, no_gain_pan)),
             fmt_q(compute_qvalue(shallow_gain_pan, no_gain_pan)), "— solid"],
            [indication, fmt_med(compute_median(focal_ind)), fmt_med(compute_median(shallow_gain_ind)),
             fmt_med(compute_median(no_gain_ind)), fmt_q(compute_qvalue(focal_ind, no_gain_ind)),
             fmt_q(compute_qvalue(shallow_gain_ind, no_gain_ind)), "-- dashed, o outlined"],
        ]

        amp_table = ax.table(cellText=amp_table_data, colLabels=amp_col_labels, loc="bottom",
                             cellLoc="center", bbox=[0.0, -0.42, 1.0, 0.18])
        amp_table.auto_set_font_size(False)
        amp_table.set_fontsize(7)
        for (row, col), cell in amp_table.get_celld().items():
            cell.set_edgecolor("#CCCCCC")
            cell.set_linewidth(0.5)
            if row == 0:
                cell.set_text_props(fontweight="bold")
                cell.set_facecolor("#F0F0F0")
                cell.set_height(cell.get_height() * 1.8)
            else:
                cell.set_facecolor("white")
        fig.subplots_adjust(bottom=0.28)

    fig.savefig(out_path / "figure_cn_amplification_strip.svg", bbox_inches="tight")
    plt.close(fig)
    figures_created.append("figure_cn_amplification_strip.svg")

    # === DELETION FIGURE ===
    del_groups = [
        build_group("deep\ndel\n(<=-2)", "deep_del", "#0072B2"),        # Blue
        build_group("shallow\ndel\n(-2 to -1)", "shallow_del", "#2E7D32"),  # Green
        build_group("no\ndel\n(>=-1)", "no_del", "#888888"),            # Gray (comparator)
    ]

    fig, ax = plt.subplots(figsize=(base_figsize[0], fig_height))
    plot_strip(ax, del_groups, "deletion dependency")

    if indication_lineage and indication:
        deep_del_pan, deep_del_ind = get_scores_for_group("deep_del")
        shallow_del_pan, shallow_del_ind = get_scores_for_group("shallow_del")
        no_del_pan, no_del_ind = get_scores_for_group("no_del")

        del_col_labels = ["Deletion", "Median\n(Deep)", "Median\n(Shallow)", "Median\n(No Del)",
                          "q (Deep)", "q (Shallow)", ""]
        del_table_data = [
            ["Pan-DepMap", fmt_med(compute_median(deep_del_pan)), fmt_med(compute_median(shallow_del_pan)),
             fmt_med(compute_median(no_del_pan)), fmt_q(compute_qvalue(deep_del_pan, no_del_pan)),
             fmt_q(compute_qvalue(shallow_del_pan, no_del_pan)), "— solid"],
            [indication, fmt_med(compute_median(deep_del_ind)), fmt_med(compute_median(shallow_del_ind)),
             fmt_med(compute_median(no_del_ind)), fmt_q(compute_qvalue(deep_del_ind, no_del_ind)),
             fmt_q(compute_qvalue(shallow_del_ind, no_del_ind)), "-- dashed, o outlined"],
        ]

        del_table = ax.table(cellText=del_table_data, colLabels=del_col_labels, loc="bottom",
                             cellLoc="center", bbox=[0.0, -0.42, 1.0, 0.18])
        del_table.auto_set_font_size(False)
        del_table.set_fontsize(7)
        for (row, col), cell in del_table.get_celld().items():
            cell.set_edgecolor("#CCCCCC")
            cell.set_linewidth(0.5)
            if row == 0:
                cell.set_text_props(fontweight="bold")
                cell.set_facecolor("#F0F0F0")
                cell.set_height(cell.get_height() * 1.8)
            else:
                cell.set_facecolor("white")
        fig.subplots_adjust(bottom=0.28)

    fig.savefig(out_path / "figure_cn_deletion_strip.svg", bbox_inches="tight")
    plt.close(fig)
    figures_created.append("figure_cn_deletion_strip.svg")

    return figures_created
