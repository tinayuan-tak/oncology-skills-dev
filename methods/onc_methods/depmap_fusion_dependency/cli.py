#!/usr/bin/env python3
"""depmap_fusion_dependency CLI — fusion-stratified dependency compute.

Builds a fusion-positive-vs-negative boolean (the target appears as either the 5' or 3' partner in a
high-confidence DepMap fusion call for a line) and runs the shared single-boolean Mann-Whitney
stratified-dependency contrast (methods.depmap_common.boolean_stratification), so the statistic and
tiering are identical to the CN / amp-expr siblings and the mutation path. The boolean is built in
read.py from OmicsFusionFiltered.csv and passed in; this module is pure compute + classification.
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

_LABELS = StratificationLabels(
    strong="fusion_positive_strongly_dependent",
    moderate="fusion_positive_moderately_dependent",
    reverse_strong="fusion_negative_strongly_dependent",
    not_stratified="not_fusion_stratified",
    insufficient="insufficient_fusion_rate",
)


def compute_fusion_stratification(
    chronos_by_model: dict,
    fusion_by_model: dict,
    strong_effect_delta: float = STRONG_EFFECT_DELTA,
    moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
    stratification_alpha: float = STRATIFICATION_ALPHA,
    min_positive: int = MIN_POSITIVE_CELLS,
    min_negative: int = MIN_COMPARATOR_CELLS,
) -> dict:
    """Compute the fusion-stratified-dependency summary_fields.

    `fusion_by_model` is {ModelID -> bool} over the fusion-profiled universe (True = a high-confidence
    fusion INVOLVING the target, either partner). Comparator = every other fusion-profiled line.
    """
    res = mannwhitney_stratification(
        chronos_by_model, fusion_by_model, min_positive=min_positive, min_comparator=min_negative
    )
    cls = classify_stratification(
        res,
        _LABELS,
        strong_effect_delta=strong_effect_delta,
        moderate_effect_delta=moderate_effect_delta,
        stratification_alpha=stratification_alpha,
    )
    q = res.get("p_value")  # single boolean -> single test -> q == p
    n_evaluated = len(set(chronos_by_model) & set(fusion_by_model))
    return {
        "n_cell_lines_evaluated": int(n_evaluated),
        "n_fusion_positive": res["n_mutant"],
        "n_fusion_negative": res["n_wildtype"],
        "median_chronos_fusion_positive": res["median_mutant"],
        "median_chronos_fusion_negative": res["median_wildtype"],
        "delta_chronos_fusion_positive_vs_negative": res.get("delta_mut_vs_wt"),
        "fusion_stratification_mannwhitney_p": res.get("p_value"),
        "fusion_stratification_mannwhitney_q": q,
        "fusion_stratification_mannwhitney_q_reverse": res.get("p_value_reverse"),
        "fusion_stratification_effect_size": res.get("effect_size"),
        "fusion_stratification_class": cls,
        "_uncomputable": bool(res.get("_uncomputable")),
    }


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


def emit_fusion_stratified_strip_plot(
    chronos_by_model: dict,
    fusion_by_model: dict,
    target_symbol: str,
    summary: dict,
    out_path: "Path",
    contracts_root: "Path",
    *,
    model_metadata: dict = None,
    indication: str = None,
) -> list:
    """Emit fusion stratified strip plot: fusion-positive vs fusion-negative.

    Shows Chronos scores grouped by fusion status:
    - Fusion positive: cell lines where target is involved in a fusion
    - Fusion negative: cell lines without target fusion (comparator)

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

    if not chronos_by_model or not fusion_by_model:
        return []

    rng = np.random.default_rng(seed=42)

    # Build groups
    def build_group(label, is_positive, color):
        models = [m for m in chronos_by_model if m in fusion_by_model and fusion_by_model[m] == is_positive]
        scores = [chronos_by_model[m] for m in models]
        if indication_lineage and model_metadata:
            is_indication = [
                (model_metadata.get(m) or {}).get("OncotreeLineage") == indication_lineage
                for m in models
            ]
        else:
            is_indication = [False] * len(models)
        return label, models, scores, is_indication, color

    groups = [
        build_group("fusion\npositive", True, "#9467BD"),      # Purple
        build_group("fusion\nnegative", False, "#888888"),     # Gray (comparator)
    ]

    base_figsize = FIGSIZE_DOUBLE_COLUMN if isinstance(FIGSIZE_DOUBLE_COLUMN, tuple) else (8.0, 5.5)
    fig_height = base_figsize[1] + 1.2 if indication_lineage else base_figsize[1]
    fig, ax = plt.subplots(figsize=(base_figsize[0] * 0.85, fig_height))  # Wider for table readability

    # Plot each group
    for i, (label, models, scores, is_ind, color) in enumerate(groups):
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
    ax.set_xticklabels([label for label, _, _, _, _ in groups], fontsize=9)
    ax.set_ylabel("Chronos score (more dependent = lower)")
    cls = summary.get("fusion_stratification_class", "?")
    ax.set_title(f"{target_symbol}: fusion stratified dependency  ({cls})")
    ax.grid(axis="y")

    # Statistics table
    if indication_lineage and indication:
        from scipy import stats as scipy_stats

        def get_scores(is_positive):
            models = [m for m in chronos_by_model if m in fusion_by_model and fusion_by_model[m] == is_positive]
            scores_pan = [chronos_by_model[m] for m in models]
            scores_ind = [chronos_by_model[m] for m in models
                          if (model_metadata.get(m) or {}).get("OncotreeLineage") == indication_lineage]
            return scores_pan, scores_ind

        def compute_median(scores):
            return float(np.median(scores)) if scores else None

        def compute_qvalue(test_scores, comparator_scores):
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

        pos_pan, pos_ind = get_scores(True)
        neg_pan, neg_ind = get_scores(False)

        col_labels = ["", "Median\n(Fusion+)", "Median\n(Fusion-)", "q-value", ""]
        table_data = [
            ["Pan-DepMap", fmt_med(compute_median(pos_pan)), fmt_med(compute_median(neg_pan)),
             fmt_q(compute_qvalue(pos_pan, neg_pan)), "— solid"],
            [indication, fmt_med(compute_median(pos_ind)), fmt_med(compute_median(neg_ind)),
             fmt_q(compute_qvalue(pos_ind, neg_ind)), "-- dashed, o outlined"],
        ]

        table = ax.table(cellText=table_data, colLabels=col_labels, loc="bottom",
                         cellLoc="center", bbox=[0.0, -0.45, 1.0, 0.20])
        table.auto_set_font_size(False)
        table.set_fontsize(8)
        for (row, col), cell in table.get_celld().items():
            cell.set_edgecolor("#CCCCCC")
            cell.set_linewidth(0.5)
            if row == 0:
                cell.set_text_props(fontweight="bold")
                cell.set_facecolor("#F0F0F0")
                cell.set_height(cell.get_height() * 1.6)
            else:
                cell.set_facecolor("white")
        fig.subplots_adjust(bottom=0.28)

    fig.savefig(out_path / "figure_fusion_stratified_strip.svg", bbox_inches="tight")
    plt.close(fig)

    return ["figure_fusion_stratified_strip.svg"]
