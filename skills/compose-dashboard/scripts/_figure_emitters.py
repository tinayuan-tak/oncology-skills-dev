"""compose-dashboard phase-2 figure-emission registry.

The dispatchers in `_live_readers.py` return summary dicts only — they don't write
figures. This module is the registry of "given this card's summary, draw its
figures into <out_dir>." Phase-2 calls these AFTER receiving the summary, so the
summary->figure pipeline is centralized and the dispatchers stay small.

Each emitter:
  - Takes (summary: dict, out_dir: Path, target: str, indication: str) -> list[dict]
  - Returns a list of {id, path, type, primary} dicts (one per emitted figure),
    OR returns [] if the card's summary contained a `_live_read_error` (no data
    to plot, graceful no-op).
  - Writes SVGs into out_dir using each method's existing CLI helpers.

The map is centralized in CARD_FIGURE_EMITTERS at the bottom. Adding a card's
figure-emission means: write an emitter function + register it.

Design choice — why not call dispatchers' methods directly:
  We could import each method's `_emit_*_plot` helpers, but we need the merged
  DataFrame the method already constructed internally. Re-computing it from the
  summary is wasteful AND loses provenance. So each emitter here re-invokes the
  method's CLI `load_depmap_files` + `_compute_*` path AND `_emit_*_plot` —
  same code paths the unit tests exercise — and writes to a card-specific subdir.

  When live-read errored, the summary contains `_live_read_error`. Emitter returns
  [] in that case — phase-2 attaches no figures, dashboard.md says "no figures".
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
TARGET_CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")


def _ensure_methods_path() -> None:
    """Idempotent: put methods repo on sys.path so `methods.<x>.cli` resolves."""
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))


def _has_live_read_error(summary: dict) -> bool:
    return isinstance(summary, dict) and "_live_read_error" in summary


def _plotly_from(module, fn_name: str, *args) -> list[dict]:
    """Best-effort call of a method's `emit_plotly_specs` (dynamic-dashboard Phase A/B).

    The method builds `.plotly.json` interactive specs SIBLING to the matplotlib SVGs, from the
    SAME in-memory series the SVGs use (no drift). This is purely additive: a method that has not
    yet grown a Plotly emitter (fn_name absent) contributes no descriptors, and any error is
    swallowed — the SVGs remain the guaranteed artifact. Returned descriptors carry a `dynamic:
    True` flag so the renderer can prefer the interactive spec when present, SVG otherwise.
    """
    fn = getattr(module, fn_name, None)
    if fn is None:
        return []
    try:
        specs = fn(*args) or []
    except Exception as e:  # noqa: BLE001
        import sys as _sys
        print(f"[compose-dashboard:figures] plotly spec emission skipped "
              f"({getattr(module, '__name__', module)}.{fn_name}): {type(e).__name__}: {e}",
              file=_sys.stderr)
        return []
    return [{**s, "dynamic": True} for s in specs]


# The 4-cell sensitivity contrasts the tumor-vs-normal-selectivity SVG forest draws (Cell A/B/C/D).
# Kept in step with dge_deseq2.emit.emit_tumor_vs_normal_selectivity_4panel's `cells` list so the
# interactive forest shows the SAME contrasts (no recompute — read straight off the summary).
_DGE_SENSITIVITY_CELLS = [
    ("tumor vs TCGA adj (raw)", "log2fc_cell_a", "q_value_cell_a"),
    ("tumor vs TCGA adj (ComBat)", "log2fc_cell_b", "q_value_cell_b"),
    ("tumor vs GTEx (raw joint)", "log2fc_cell_c", "q_value_cell_c"),
    ("tumor vs GTEx (ComBat)", "log2fc_cell_d", "q_value_cell_d"),
]


def _dge_cell_contrasts(summary: dict) -> list[dict]:
    rows = []
    for label, lfc_k, q_k in _DGE_SENSITIVITY_CELLS:
        lfc = summary.get(lfc_k)
        if lfc is None or lfc != lfc:   # skip absent / NaN cells (matches the SVG)
            continue
        rows.append({"label": label, "log2_fc": float(lfc), "q_value": summary.get(q_k)})
    return rows


def _emit_tumor_vs_normal_selectivity(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit tumor-vs-normal-selectivity 4-panel figure (v3, four-cell).

    Uses the v3 sensitivity summary produced by the live-reader dispatcher
    (already contains the 4 cell log2fc + concordance fields). Pulls per-
    sample log2(CPM+1) for tumor + adjacent-normal + GTEx-normal from
    recount3 for the box+strip panel.

    Fetch time: ~30s for a fresh (target, indication) — dominated by the 3
    gzipped-counts streams + 3 metadata fetches. Backwards-compatible with
    the v2_two_product_fallback summary shape from read_tumor_vs_normal_
    selectivity (missing cells B/D render as absent forest rows).
    """
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.dge_deseq2 import read as dge_read
    from methods.dge_deseq2 import emit as dge_emit

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        per_sample = dge_read.read_per_sample_expression_all_three_groups(
            target=target, indication=indication,
        )
    except Exception:
        per_sample = None

    dge_emit.emit_tumor_vs_normal_selectivity_4panel(
        sensitivity_summary=summary,
        per_sample_data=per_sample,
        target=target, indication=indication,
        out_dir=out_dir, target_contracts_dir=TARGET_CONTRACTS,
    )
    figures = [
        {"id": "tumor_vs_normal_selectivity_4panel",
         "path": "figure_tumor_vs_normal_selectivity_4panel.svg",
         "type": "box_forest_sensitivity_panel", "primary": True},
    ]
    # Interactive twin — same per_sample_data + the 4-cell contrasts the SVG forest draws
    # (extracted from the SAME sensitivity_summary; no recompute).
    contrasts = _dge_cell_contrasts(summary)
    figures += _plotly_from(dge_emit, "emit_plotly_specs", per_sample, contrasts,
                            target, indication, out_dir, TARGET_CONTRACTS,
                            "tumor_vs_normal")
    return figures


def _emit_expression_tumor_vs_adjacent(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit tumor-vs-adjacent compound figure (box+strip + DGE-stats callout).

    Pulls per-sample log2(CPM+1) from recount3 at emit-time via
    dge_deseq2.read.read_per_sample_expression_tumor_vs_adjacent. First call
    per (target, indication) takes ~10-20s (streams two ~50MB gzipped counts
    files from S3); subsequent lookups in the same process are hot-cached at
    the Ensembl-ID-map level.

    Placeholder rendered when the indication has no recount3 study mapping,
    or the target's HGNC symbol doesn't resolve to an Ensembl ID.
    """
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.dge_deseq2 import read as dge_read
    from methods.dge_deseq2 import emit as dge_emit

    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        per_sample = dge_read.read_per_sample_expression_tumor_vs_adjacent(
            target=target, indication=indication,
        )
    except Exception:
        per_sample = None
    dge_emit.emit_tumor_vs_adjacent_compound(
        summary=summary, per_sample_data=per_sample,
        target=target, indication=indication,
        out_dir=out_dir, target_contracts_dir=TARGET_CONTRACTS,
    )
    figures = [
        {"id": "tumor_vs_adjacent_compound",
         "path": "figure_tumor_vs_adjacent_compound.svg",
         "type": "violin_paired_with_significance", "primary": True},
    ]
    # Interactive twin — same per_sample_data + the single tumor-vs-adjacent contrast the SVG
    # callout reports (log2_fc / q_value from the SAME summary). basename keys the output so it
    # can't collide with the 3-group selectivity card in the same package dir.
    contrasts = []
    if summary.get("log2_fc") is not None:
        contrasts = [{"label": "tumor vs adj-normal",
                      "log2_fc": summary["log2_fc"], "q_value": summary.get("q_value")}]
    figures += _plotly_from(dge_emit, "emit_plotly_specs", per_sample, contrasts,
                            target, indication, out_dir, TARGET_CONTRACTS,
                            "tumor_vs_adjacent")
    return figures


def _emit_card1_pan_cancer_dependency_distribution(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Re-runs Card 1's method internals to emit waterfall + histogram_kde SVGs.

    Strategy: invoke methods.depmap_chronos_distribution.cli.load_depmap_files
    + compute_summary_stats + emit_waterfall_plot + emit_histogram_kde_plot
    + emit_plot_data + emit_manifest, writing into out_dir. The summary the
    dispatcher already returned is structurally equivalent to what these helpers
    re-compute — but the helpers need the raw chronos_by_model / model_metadata
    dicts which the summary doesn't preserve.
    """
    if _has_live_read_error(summary):
        return []

    _ensure_methods_path()
    from methods.depmap_chronos_distribution import cli as c1cli

    out_dir.mkdir(parents=True, exist_ok=True)
    chronos_by_model, model_metadata, load_errors = c1cli.load_depmap_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors:
        return []

    recomputed_summary = c1cli.compute_summary_stats(
        chronos_by_model, model_metadata,
        strong_threshold=-1.0, moderate_threshold=-0.5,
    )
    c1cli.emit_waterfall_plot(
        chronos_by_model, model_metadata, target,
        recomputed_summary, out_dir, TARGET_CONTRACTS,
    )
    c1cli.emit_histogram_kde_plot(
        chronos_by_model, target, recomputed_summary, out_dir, TARGET_CONTRACTS,
    )
    c1cli.emit_plot_data(chronos_by_model, model_metadata, -1.0, out_dir)
    c1cli.emit_manifest(target, "26q1", recomputed_summary, chronos_by_model, out_dir, [])

    figures = [
        {"id": "waterfall", "path": "figure_waterfall.svg", "type": "waterfall_plot", "primary": True},
        {"id": "histogram_kde", "path": "figure_histogram_kde.svg", "type": "histogram_kde", "primary": False},
    ]
    figures += _plotly_from(c1cli, "emit_plotly_specs", chronos_by_model, model_metadata,
                            target, recomputed_summary, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_card2_dependency_lineage_selectivity(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Re-runs Card 2's method internals to emit forest_plot + lineage_strip SVGs."""
    if _has_live_read_error(summary):
        return []

    _ensure_methods_path()
    from methods.depmap_chronos import cli as c2cli

    out_dir.mkdir(parents=True, exist_ok=True)
    chronos_by_model, model_metadata, load_errors = c2cli.load_depmap_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors:
        return []

    lineage_summary = c2cli.compute_lineage_summary(
        chronos_by_model, model_metadata, indication=indication,
    )
    # Card 2 v3.0.0 is indication-decoupled. The method output no longer carries
    # `lineage_label`; figure emitter resolves the target lineage from the indication
    # → lineage map (shared INDICATION_LINEAGE constant in the method module). This
    # is the synthesis-layer responsibility per Decision 2A.
    target_lineage = c2cli.INDICATION_LINEAGE.get(indication, "")
    merged_data = c2cli.emit_plot_data(
        chronos_by_model, model_metadata, target_lineage,
        strong_threshold=-1.0, out_path=out_dir,
    )
    c2cli.emit_forest_plot(
        lineage_summary.get("_per_lineage_records", []), target_lineage,
        target, indication, lineage_summary, out_dir, TARGET_CONTRACTS,
    )
    c2cli.emit_lineage_strip(
        merged_data, target_lineage, target, indication, out_dir, TARGET_CONTRACTS,
    )
    c2cli.emit_manifest(target, indication, "26q1", lineage_summary,
                         chronos_by_model, out_dir, [])

    figures = [
        {"id": "forest_plot", "path": "figure_forest_plot.svg", "type": "lineage_forest_plot", "primary": True},
        {"id": "lineage_strip", "path": "figure_lineage_strip.svg", "type": "lineage_strip_plot", "primary": False},
    ]
    # Interactive twin — per-lineage forest from the SAME _per_lineage_records the SVG used (no drift).
    figures += _plotly_from(c2cli, "emit_plotly_specs",
                            lineage_summary.get("_per_lineage_records", []), target_lineage,
                            target, indication, lineage_summary, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_card4_expression_dependency_correlation(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Re-runs Card 4's method internals to emit scatter + lineage-stratified SVGs.

    Strategy mirrors Card 1+2: invoke methods.depmap_expression_dependency.cli's
    public helpers (load_depmap_files_for_card4 → compute_correlation_summary →
    build_merged_data → emit_scatter_regression_plot + emit_lineage_stratified_scatter
    + emit_plot_data + emit_manifest)."""
    if _has_live_read_error(summary):
        return []

    _ensure_methods_path()
    from methods.depmap_expression_dependency import cli as c4cli

    out_dir.mkdir(parents=True, exist_ok=True)
    chronos_by_model, tpm_by_model, model_metadata, load_errors = (
        c4cli.load_depmap_files_for_card4(release_pin="26q1", target_symbol=target)
    )
    if load_errors:
        return []
    if not chronos_by_model or not tpm_by_model:
        return []

    recomputed_summary = c4cli.compute_correlation_summary(
        chronos_by_model, tpm_by_model, model_metadata, indication=indication,
    )
    target_lineage = recomputed_summary.get("_target_lineage", "")
    merged = c4cli.build_merged_data(
        chronos_by_model, tpm_by_model, model_metadata, target_lineage,
    )

    c4cli.emit_plot_data(merged, out_dir)
    c4cli.emit_scatter_regression_plot(
        merged, target, indication, recomputed_summary, out_dir, TARGET_CONTRACTS,
    )
    c4cli.emit_lineage_stratified_scatter(
        merged, target, indication, recomputed_summary, out_dir, TARGET_CONTRACTS,
    )
    c4cli.emit_manifest(target, indication, "26q1", recomputed_summary, {}, out_dir, [])

    return [
        {"id": "scatter_with_regression", "path": "figure_scatter_with_regression.svg",
         "type": "expression_chronos_scatter", "primary": True},
        {"id": "lineage_stratified_scatter", "path": "figure_lineage_stratified_scatter.svg",
         "type": "lineage_stratified_scatter", "primary": False},
    ]


def _emit_card1b_pan_cancer_rnai_dependency_distribution(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Re-runs Card 1b's method internals to emit RNAi waterfall + histogram_kde SVGs."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.depmap_demeter_distribution import cli as c1bcli

    out_dir.mkdir(parents=True, exist_ok=True)
    demeter_by_model, model_metadata, load_errors = c1bcli.load_rnai_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors or not demeter_by_model:
        return []

    recomputed_summary = c1bcli.compute_summary_stats(
        demeter_by_model, model_metadata,
        strong_threshold=-0.5, moderate_threshold=-0.25,
    )
    c1bcli.emit_waterfall_plot(
        demeter_by_model, model_metadata, target,
        recomputed_summary, out_dir, TARGET_CONTRACTS,
    )
    c1bcli.emit_histogram_kde_plot(
        demeter_by_model, target, recomputed_summary, out_dir, TARGET_CONTRACTS,
    )
    c1bcli.emit_plot_data(demeter_by_model, model_metadata, -0.5, out_dir)
    c1bcli.emit_manifest(target, "26q1", recomputed_summary, demeter_by_model, out_dir, [])

    figures = [
        {"id": "waterfall_rnai", "path": "figure_waterfall_rnai.svg",
         "type": "ranked_waterfall_rnai", "primary": True},
        {"id": "histogram_kde_rnai", "path": "figure_histogram_kde_rnai.svg",
         "type": "density_histogram_with_kde_rnai", "primary": False},
    ]
    # Interactive twins — from the SAME demeter_by_model + recomputed_summary the SVGs used (no drift).
    figures += _plotly_from(c1bcli, "emit_plotly_specs", demeter_by_model, model_metadata,
                            target, recomputed_summary, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_expression_distribution(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Re-runs E3.a method internals to emit waterfall + per-lineage strip SVGs."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.depmap_expression_distribution import cli as e3acli

    out_dir.mkdir(parents=True, exist_ok=True)
    tpm_by_model, model_metadata, load_errors = e3acli.load_expression_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors or not tpm_by_model:
        return []
    recomputed = e3acli.compute_summary_stats(tpm_by_model, model_metadata)
    e3acli.emit_density_plot(tpm_by_model, target, recomputed, out_dir, TARGET_CONTRACTS)
    e3acli.emit_waterfall_plot(tpm_by_model, model_metadata, target, recomputed, out_dir, TARGET_CONTRACTS)
    e3acli.emit_lineage_strip(tpm_by_model, model_metadata, target, recomputed, out_dir, TARGET_CONTRACTS)
    e3acli.emit_plot_data(tpm_by_model, model_metadata, 1.0, out_dir)
    e3acli.emit_manifest(target, "26q1", recomputed, out_dir, [])
    figures = [
        {"id": "density_expression", "path": "figure_density_expression.svg",
         "type": "density_histogram_with_kde_expression", "primary": True},
        {"id": "lineage_strip_expression", "path": "figure_lineage_strip_expression.svg",
         "type": "per_lineage_strip_expression", "primary": False},
        {"id": "waterfall_expression", "path": "figure_waterfall_expression.svg",
         "type": "ranked_waterfall_expression", "primary": False},
    ]
    figures += _plotly_from(e3acli, "emit_plotly_specs", tpm_by_model, model_metadata,
                            target, recomputed, out_dir, TARGET_CONTRACTS, indication)
    return figures


def _emit_mutation_type_counts(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Re-runs E4 mutation-type-counts method to emit class bar (primary) + lineage bar."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.depmap_mutation_type_counts import cli as e4cli

    out_dir.mkdir(parents=True, exist_ok=True)
    target_rows, model_meta, n_total, load_errors = e4cli.load_mutation_data("26q1", target)
    if load_errors:
        return []
    recomputed = e4cli.compute_summary_stats(target_rows, model_meta, n_total)
    e4cli.emit_mutation_class_bar(recomputed, target, out_dir, TARGET_CONTRACTS)
    e4cli.emit_lineage_class_bar(recomputed, target, out_dir, TARGET_CONTRACTS)
    e4cli.emit_plot_data(target_rows, model_meta, out_dir)
    e4cli.emit_manifest(target, "26q1", recomputed, out_dir, [])
    return [
        {"id": "mutation_class_bar", "path": "figure_mutation_class_bar.svg",
         "type": "stacked_bar_mutation_class", "primary": True},
        {"id": "mutation_lineage_bar", "path": "figure_mutation_lineage_bar.svg",
         "type": "per_lineage_stacked_bar_mutation", "primary": False},
    ]


def _emit_cn_distribution(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Re-runs E3.b CN method to emit density (primary) + lineage_strip + waterfall."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.depmap_cn_distribution import cli as e3bcli

    out_dir.mkdir(parents=True, exist_ok=True)
    cn_by, model_metadata, assay_used, load_errors = e3bcli.load_cn_files("26q1", target)
    if load_errors or not cn_by:
        return []
    recomputed = e3bcli.compute_summary_stats(cn_by, model_metadata, assay_used=assay_used)
    e3bcli.emit_density_plot(cn_by, target, recomputed, out_dir, TARGET_CONTRACTS)
    e3bcli.emit_lineage_strip(cn_by, model_metadata, target, recomputed, out_dir, TARGET_CONTRACTS)
    e3bcli.emit_waterfall_plot(cn_by, model_metadata, target, recomputed, out_dir, TARGET_CONTRACTS)
    e3bcli.emit_plot_data(cn_by, model_metadata, out_dir)
    e3bcli.emit_manifest(target, "26q1", recomputed, out_dir, [])
    return [
        {"id": "density_cn", "path": "figure_density_cn.svg",
         "type": "density_histogram_with_kde_cn", "primary": True},
        {"id": "lineage_strip_cn", "path": "figure_lineage_strip_cn.svg",
         "type": "per_lineage_strip_cn", "primary": False},
        {"id": "waterfall_cn", "path": "figure_waterfall_cn.svg",
         "type": "ranked_waterfall_cn", "primary": False},
    ]


def _emit_card1c_crispr_rnai_concordance(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Re-runs Card 1c (derived concordance) to emit scatter + partition-bar SVGs."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.depmap_crispr_rnai_concordance import cli as c1ccli

    out_dir.mkdir(parents=True, exist_ok=True)
    chronos_by, demeter_by, model_meta, load_errors = c1ccli.load_concordance_inputs(target, "26q1")
    if load_errors:
        return []
    recomputed = c1ccli.compute_concordance(chronos_by, demeter_by, model_meta)
    c1ccli.emit_concordance_overlay_density(recomputed["per_line_concordance"], target, out_dir, TARGET_CONTRACTS)
    c1ccli.emit_concordance_scatter(recomputed["per_line_concordance"], target, out_dir, TARGET_CONTRACTS)
    c1ccli.emit_partition_bar(recomputed, target, out_dir, TARGET_CONTRACTS)
    c1ccli.emit_plot_data(recomputed["per_line_concordance"], out_dir)
    c1ccli.emit_manifest(target, "26q1", recomputed, out_dir, [])
    figures = [
        {"id": "concordance_overlay_density", "path": "figure_concordance_overlay_density.svg",
         "type": "overlay_kde_with_rug", "primary": True},
        {"id": "concordance_partition_bar", "path": "figure_concordance_partition_bar.svg",
         "type": "stacked_bar", "primary": False},
        {"id": "concordance_scatter", "path": "figure_concordance_scatter.svg",
         "type": "scatter_with_quadrants", "primary": False},
    ]
    # Interactive twin — the CRISPR-vs-RNAi scatter from the SAME per_line_concordance (no drift).
    figures += _plotly_from(c1ccli, "emit_plotly_specs", recomputed["per_line_concordance"],
                            target, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_card3_mutation_stratified_dependency(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Re-runs Card 3 method internals to emit mut-vs-WT + per-hotspot figures."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.depmap_mutation_dependency import cli as c3cli
    from methods.depmap_chronos_distribution import cli as c1cli

    out_dir.mkdir(parents=True, exist_ok=True)
    chronos_by_model, model_metadata, load_errors = c1cli.load_depmap_files(
        release_pin="26q1", target_symbol=target
    )
    if load_errors or not chronos_by_model:
        return []
    hot, dam, mut_errs = c3cli.load_mutation_data("26q1", target)
    if mut_errs:
        return []

    recomputed = c3cli.compute_mutation_stratification(chronos_by_model, hot, dam)
    c3cli.emit_plot_data(chronos_by_model, hot, dam, model_metadata, out_dir)
    c3cli.emit_mut_vs_wt_strip_plot(chronos_by_model, hot, dam,
                                      target, recomputed, out_dir, TARGET_CONTRACTS)
    c3cli.emit_per_hotspot_chronos_plot(chronos_by_model, recomputed.get("per_hotspot_stats", []),
                                          target, out_dir, TARGET_CONTRACTS)
    c3cli.emit_manifest(target, indication, "26q1", recomputed, out_dir, [])
    # Interactive twin — mut-vs-WT box+strip from the SAME chronos + hotspot/damaging membership (no drift).
    plotly_figs = _plotly_from(c3cli, "emit_plotly_specs", chronos_by_model, hot, dam,
                               target, recomputed, out_dir, TARGET_CONTRACTS)
    return plotly_figs + [
        {"id": "mut_vs_wt_strip", "path": "figure_mut_vs_wt_strip.svg",
         "type": "mutation_stratified_strip", "primary": True},
        {"id": "per_hotspot_chronos", "path": "figure_per_hotspot_chronos.svg",
         "type": "per_hotspot_chronos_strip", "primary": False},
    ]


def _emit_dependency_predictability(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit E5 dependency-predictability figures (v2).

    Two panels:
      1. feature_importance_bar (primary): top-10 SHAP-ranked features colored
         by feature_class. Title carries r² + bootstrap CI + class label + any
         RF↔XGB divergence caveat.
      2. lineage_predictability: per-lineage r² horizontal bar with within-
         lineage top feature. DepMap high-confidence floor (r²=0.16) marked.

    Unlike E1-E4 emitters, this one does NOT reload data — E5 is a THIN LOOKUP
    card and the summary dict already carries the per-target row from the
    v2 derived parquet. We call the method's emit helpers directly.

    On _live_read_error / data_unavailable, the emit helpers produce placeholder
    SVGs explaining the gap; we still return figure descriptors so the dashboard
    shows an explanatory cell instead of nothing.
    """
    _ensure_methods_path()
    from methods.depmap_predictability import cli as e5cli

    out_dir.mkdir(parents=True, exist_ok=True)
    e5cli.emit_feature_importance_bar(summary, target, out_dir, TARGET_CONTRACTS)
    e5cli.emit_lineage_conditional_panel(summary, target, out_dir, TARGET_CONTRACTS)
    parquet_uri = e5cli.RELEASE_PIN_TO_PARQUET.get("26q1-v2", "<unset>")
    e5cli.emit_manifest(target, "26q1-v2", summary, out_dir, parquet_uri)
    figures = [
        {"id": "feature_importance_bar", "path": "figure_feature_importance_bar.svg",
         "type": "horizontal_bar_feature_importance", "primary": True},
        {"id": "lineage_predictability", "path": "figure_lineage_predictability.svg",
         "type": "horizontal_bar_lineage_predictability", "primary": False},
    ]
    # Interactive twin — top-10 SHAP feature-importance bar from the SAME summary (no drift).
    figures += _plotly_from(e5cli, "emit_plotly_specs", summary, target, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_prism_compound_activity(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit E6 PRISM compound-activity figures (v2).

    Three panels:
      1. top_compounds_bar (primary): horizontal bar of top-K PRISM compounds
         by activity, colored by clinical status.
      2. lineage_activity_bar: per-lineage median LFC bar with best-responder
         annotations (surfaces the median-vs-tail divergence for oncogene-
         addiction drugs). Placeholder on no per_lineage_activity data.
      3. activity_vocab_panel: text card with class + granular fields + v2
         lineage-selectivity vocabulary.

    Thin-lookup pattern (same as E5): does NOT reload data — the summary dict
    already carries the per-target row from the depmap-prism-activity-v3 parquet.
    """
    _ensure_methods_path()
    from methods.depmap_prism_activity import cli as e6cli

    out_dir.mkdir(parents=True, exist_ok=True)
    e6cli.emit_top_compounds_bar(summary, target, out_dir, TARGET_CONTRACTS)
    e6cli.emit_lineage_activity_bar(summary, target, out_dir, TARGET_CONTRACTS)
    e6cli.emit_activity_vocabulary_panel(summary, target, out_dir, TARGET_CONTRACTS)
    parquet_uri = e6cli.RELEASE_PIN_TO_PARQUET.get("prism-activity-v4", "<unset>")
    e6cli.emit_manifest(target, "prism-activity-v4", summary, out_dir, parquet_uri)
    return [
        {"id": "top_compounds_bar", "path": "figure_top_compounds_bar.svg",
         "type": "horizontal_bar_top_compounds", "primary": True},
        {"id": "lineage_activity_bar", "path": "figure_lineage_activity_bar.svg",
         "type": "horizontal_bar_per_lineage", "primary": False},
        {"id": "activity_vocab_panel", "path": "figure_activity_vocab_panel.svg",
         "type": "text_summary_panel", "primary": False},
    ]


def _emit_prism_crispr_concordance(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit E7 CRISPR × RNAi × PRISM concordance figures.

    Three panels:
      1. concordance_scatter (primary): 2D scatter of rho_crispr vs rho_rnai
         per compound; quadrant-colored + threshold reference lines.
      2. dual_responders_bar: paired horizontal bars showing CRISPR-dep and
         best-compound-LFC magnitudes for dual-validated cell lines.
      3. concordance_vocab_panel: text card with class + best rhos + top-3
         dual responders.

    Thin-lookup pattern: reads summary dict from the shared v4 parquet.
    Placeholders when concordance is thin_evidence / data_unavailable.
    """
    _ensure_methods_path()
    from methods.depmap_prism_crispr_concordance import cli as e7cli

    out_dir.mkdir(parents=True, exist_ok=True)
    e7cli.emit_concordance_scatter(summary, target, out_dir, TARGET_CONTRACTS)
    e7cli.emit_dual_responders_bar(summary, target, out_dir, TARGET_CONTRACTS)
    e7cli.emit_concordance_vocabulary_panel(summary, target, out_dir, TARGET_CONTRACTS)
    parquet_uri = e7cli.RELEASE_PIN_TO_PARQUET.get("prism-activity-v4", "<unset>")
    e7cli.emit_manifest(target, "prism-activity-v4", summary, out_dir, parquet_uri)
    figures = [
        {"id": "concordance_scatter", "path": "figure_concordance_scatter.svg",
         "type": "two_d_scatter_correlation", "primary": True},
        {"id": "dual_responders_bar", "path": "figure_dual_responders_bar.svg",
         "type": "horizontal_bar_paired_dual_responders", "primary": False},
        {"id": "concordance_vocab_panel", "path": "figure_concordance_vocab_panel.svg",
         "type": "text_summary_panel", "primary": False},
    ]
    # Interactive twin — per-compound ρ-CRISPR vs ρ-RNAi scatter from the SAME summary (no drift).
    figures += _plotly_from(e7cli, "emit_plotly_specs", summary, target, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_gnomad_lof_constraint(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the gnomad-lof-constraint gauge panel (pLI + LOEUF vs constraint bands).

    Summary-driven (thin lookup — the summary already carries pli/loeuf/class). On
    _live_read_error, no data to plot → []. On indeterminate (no scores) the method
    helper renders an informative placeholder panel, so we still return a descriptor.
    """
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.gnomad_constraint import cli as gccli
    out_dir.mkdir(parents=True, exist_ok=True)
    gccli.emit_constraint_gauge(summary, target, out_dir, TARGET_CONTRACTS)
    return [
        {"id": "constraint_scores_gauge_panel",
         "path": "figure_constraint_scores_gauge_panel.svg",
         "type": "constraint_scores_gauge_panel", "primary": True},
    ]


def _emit_normal_tissue_liability(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the normal-tissue-liability figure (per-tissue IHC intensity bar,
    essential tissues in red). Summary-driven. On _live_read_error → []. On a broad
    gene / not-detected (empty specific-tissue list) the helper renders an
    informative breadth panel, so a descriptor is still returned."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.hpa_normal_tissue_liability import cli as ntcli
    out_dir.mkdir(parents=True, exist_ok=True)
    ntcli.emit_normal_tissue_bar(summary, target, out_dir, TARGET_CONTRACTS)
    return [
        {"id": "normal_tissue_expression_heatmap",
         "path": "figure_normal_tissue_expression_heatmap.svg",
         "type": "normal_tissue_expression_heatmap", "primary": True},
    ]


def _emit_protein_abundance_celline(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the Gygi cell-line protein-abundance figures (density + lineage-strip SVG + plot_data +
    interactive plotly). Re-runs the method load path (the summary doesn't preserve the raw
    abundance_by_model / lineage_by_model the plots need) — mirrors _emit_expression_distribution.
    On _live_read_error or no MS detection → []."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.depmap_protein_abundance import cli as pac
    out_dir.mkdir(parents=True, exist_ok=True)
    acc = pac.resolve_accession(target)
    if acc is None:
        return []
    abundance_by_model, _panel = pac.load_abundance_column(acc)
    if not abundance_by_model:
        return []
    lineage_by_model = pac.load_model_lineage()
    recomputed = pac.compute_summary(target, abundance_by_model, lineage_by_model, n_panel=_panel)
    pac.emit_density_protein(abundance_by_model, target, recomputed, out_dir, TARGET_CONTRACTS)
    pac.emit_lineage_strip_protein(abundance_by_model, lineage_by_model, target, recomputed,
                                   out_dir, TARGET_CONTRACTS)
    pac.emit_plot_data_protein(abundance_by_model, lineage_by_model, out_dir)
    figures = [
        {"id": "density_protein_abundance", "path": "figure_density_protein_abundance.svg",
         "type": "density_histogram_with_kde", "primary": True},
        {"id": "lineage_strip_protein", "path": "figure_lineage_strip_protein.svg",
         "type": "per_lineage_strip_plot", "primary": False},
    ]
    figures += _plotly_from(pac, "emit_plotly_specs", abundance_by_model, lineage_by_model,
                            target, recomputed, out_dir, TARGET_CONTRACTS, indication)
    return figures


def _emit_protein_presence_cptac(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the CPTAC per-cohort tumor-vs-normal protein DISTRIBUTION boxplot + plot_data + plotly.
    Reads the per-SAMPLE product (cptac-protein-tumor-vs-normal-per-sample-v1) so the figure shows
    the true tumor + normal per-aliquot distributions per cohort, with per-cohort Welch/Mann-Whitney
    significance recomputed from those samples (indication-agnostic — the panel shows ALL cohorts the
    target was quantified in). On _live_read_error or no cohort hit → []."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.cptac_protein_deg import read as cptac
    out_dir.mkdir(parents=True, exist_ok=True)
    if not cptac.per_cohort_distribution_stats(target):
        return []                                   # target absent from every CPTAC cohort
    cptac.emit_per_cohort_panel(target, out_dir, TARGET_CONTRACTS)
    cptac.emit_plot_data(target, out_dir)
    figures = [
        {"id": "protein_per_cohort_tumor_vs_normal",
         "path": "figure_protein_per_cohort_tumor_vs_normal.svg",
         "type": "per_cohort_distribution_tumor_vs_normal", "primary": True},
    ]
    figures += _plotly_from(cptac, "emit_plotly_specs", target, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_tumor_elevation_breadth(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the pan-cancer by-tissue tumor-vs-normal TPM DISTRIBUTION for the tumor-elevation-breadth
    card. TCGA tumor (per study) + GTEx normal (per tissue) co-plotted on ONE log2(TPM+1) axis, read
    from the precomputed quantile product (tcga-gtex-tpm-tissue-quantiles-v1) — the target-grain
    RNA companion to the breadth K-of-N roll-up. Indication-agnostic (pan-cancer). On no gene hit
    (target absent from the quantile product) → [].

    NB this is the RNA-distribution figure; it is NOT gated on the CPTAC-protein summary, so it fires
    for a target-only query even when protein breadth is data_unavailable — which is exactly the
    degenerate target-only case the breadth card exists to rescue."""
    _ensure_methods_path()
    from methods.tcga_gtex_tpm_quantiles import read as tpmq
    out_dir.mkdir(parents=True, exist_ok=True)
    if tpmq.read_pan_cancer_by_tissue(target).empty:
        return []                                   # target absent from the quantile product
    tpmq.emit_by_tissue_distribution(target, out_dir, TARGET_CONTRACTS)
    tpmq.emit_plot_data(target, out_dir)
    figures = [
        {"id": "pan_cancer_by_tissue_distribution",
         "path": "figure_pan_cancer_by_tissue_distribution.svg",
         "type": "pan_cancer_by_tissue_tumor_vs_normal_distribution", "primary": True},
    ]
    figures += _plotly_from(tpmq, "emit_plotly_specs", target, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_tumor_expression_distribution(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the Q1 per-sample tumor RNA distribution figure (tumor-expression-distribution card):
    tumor (TCGA) vs matched-normal (GTEx) per-sample log2(TPM+1) box+strip with the normal-p95 line
    + fraction-above annotation, from the two long products via tcga_gtex_expression_distribution.
    Indication-scoped. On _live_read_error or no tumor samples → []."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.tcga_gtex_expression_distribution import cli as exprdist
    out_dir.mkdir(parents=True, exist_ok=True)
    if not summary or summary.get("tumor_expression_class") == "data_unavailable":
        return []                                   # target absent from TCGA long product here
    exprdist.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    exprdist.emit_plot_data(target, indication, out_dir)
    figures = [
        {"id": "expression_distribution_per_sample",
         "path": "figure_expression_distribution.svg",
         "type": "per_sample_tumor_normal_distribution", "primary": True},
    ]
    figures += _plotly_from(exprdist, "emit_plotly_specs", target, indication, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_tumor_expression_distribution_subtype(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the subtype panel (tumor-expression-distribution-subtype card): one box+strip row per
    molecular subtype, ordered by median, colored by subtype_signal, pooled-median reference line.
    Gated on subtype_axis_available (no landed shard for the indication → []). The method emitters
    re-read the shared value substrate (no drift). On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or not summary.get("subtype_axis_available"):
        return []                                   # no landed shard for this indication (honest)
    _ensure_methods_path()
    from methods.tcga_gtex_expression_distribution import cli as exprdist
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = exprdist.emit_subtype_svg(target, indication, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []                                   # axis available but no measured strata
    figures = [
        {"id": "expression_distribution_subtype_panel",
         "path": "figure_expression_distribution_subtype.svg",
         "type": "per_subtype_distribution_panel", "primary": True},
    ]
    figures += _plotly_from(exprdist, "emit_subtype_plotly_specs", target, indication,
                            out_dir, TARGET_CONTRACTS)
    return figures


def _emit_tumor_vs_normal_percentile_crossing(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the Q2 selectivity figure (tumor-vs-normal-percentile-crossing card): reuses the
    tumor-vs-matched-normal box+strip with the normal-p95 line + fraction-above annotation — the
    same view the crossing metric summarizes. On _live_read_error / data_unavailable → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("selectivity_class") == "data_unavailable":
        return []
    _ensure_methods_path()
    from methods.tcga_gtex_expression_distribution import cli as exprdist
    out_dir.mkdir(parents=True, exist_ok=True)
    # emit_svg reads its own tumor/normal vectors; pass the summary through for the p95 annotation.
    exprdist.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    figures = [
        {"id": "expression_distribution_per_sample",
         "path": "figure_expression_distribution.svg",
         "type": "per_sample_tumor_normal_distribution", "primary": True},
    ]
    figures += _plotly_from(exprdist, "emit_plotly_specs", target, indication, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_normal_tissue_liability_gtex(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the Q3 normal-tissue liability atlas (normal-tissue-liability-gtex card): per-GTEx-tissue
    median bar, critical organs red, HIGH cutoff line. target-grain (indication ignored by the
    method). On _live_read_error / data_unavailable / target-absent → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("liability_class") == "data_unavailable":
        return []
    _ensure_methods_path()
    from methods.tcga_gtex_expression_distribution import cli as exprdist
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = exprdist.emit_liability_svg(target, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    figures = [
        {"id": "normal_tissue_liability_atlas",
         "path": "figure_normal_tissue_liability.svg",
         "type": "normal_tissue_atlas_bar", "primary": True},
    ]
    figures += _plotly_from(exprdist, "emit_liability_plotly_specs", target, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_recommended_models(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the Q4 patient↔model correspondence scatter (recommended-models card): DepMap models on
    target TPM (x) vs Chronos (y), screen roles colored, patient tumor IQR shaded, lineage emphasized.
    Gated on correspondence_class. On _live_read_error / data_unavailable → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("correspondence_class") == "data_unavailable":
        return []
    _ensure_methods_path()
    from methods.patient_model_expression_correspondence import cli as pmc
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = pmc.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    figures = [
        {"id": "recommended_models_scatter",
         "path": "figure_recommended_models.svg",
         "type": "patient_model_correspondence_scatter", "primary": True},
    ]
    figures += _plotly_from(pmc, "emit_plotly_specs", target, indication, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_rna_protein_concordance(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the Q5 RNA↔protein concordance scatter (rna-protein-concordance card): per-model target
    RNA (x) vs protein (y) with fitted trend + r. Gated on rna_as_biomarker (data_unavailable /
    insufficient → no figure). On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("rna_as_biomarker") in (None, "data_unavailable",
                                                          "insufficient_paired_models"):
        return []
    _ensure_methods_path()
    from methods.depmap_rna_protein_concordance import cli as rpc
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = rpc.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    figures = [
        {"id": "rna_protein_concordance_scatter",
         "path": "figure_rna_protein_concordance.svg",
         "type": "rna_protein_concordance_scatter", "primary": True},
    ]
    figures += _plotly_from(rpc, "emit_plotly_specs", target, indication, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_rna_protein_concordance_tumor(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the Q5 TUMOR RNA↔protein concordance scatter (rna-protein-concordance-tumor card):
    per-tumor RNA (x) vs protein (y) from the matched CPTAC product. Gated on rna_as_biomarker
    (data_unavailable / insufficient_paired_tumors → no figure). On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("rna_as_biomarker") in (None, "data_unavailable",
                                                          "insufficient_paired_tumors"):
        return []
    _ensure_methods_path()
    from methods.depmap_rna_protein_concordance import cli as rpc
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = rpc.emit_tumor_svg(target, indication, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    figures = [
        {"id": "rna_protein_concordance_tumor_scatter",
         "path": "figure_rna_protein_concordance_tumor.svg",
         "type": "rna_protein_concordance_tumor_scatter", "primary": True},
    ]
    figures += _plotly_from(rpc, "emit_tumor_plotly_specs", target, indication, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_alteration_role(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the alteration-role evidence card (typed driver classification): the role call +
    the OncoKB/IntOGen evidence it rests on. Gated on alteration_role (data_unavailable → []).
    On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("alteration_role") in (None, "data_unavailable"):
        return []
    _ensure_methods_path()
    from methods.driver_role_overlay import cli as dro
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = dro.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {"id": "alteration_role_evidence_card",
         "path": "figure_alteration_role.svg",
         "type": "alteration_role_evidence_card", "primary": True},
    ]


def _emit_functional_gene_state(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the functional-gene-state figure (M6): per-arm STACKED composition of the two-hit
    states (patient vs model — wt / monoallelic / biallelic-genetic / uncertain). Gated on the
    presence of at least one arm's state distribution (both data_unavailable → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    # both arms must be structured-absent for the figure to be skipped; else there is a bar to draw.
    patient = summary.get("patient") or {}
    model = summary.get("model") or {}
    if not (patient.get("state_counts") or model.get("state_counts")):
        return []
    _ensure_methods_path()
    from methods.functional_gene_state import cli as fgs
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = fgs.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {"id": "functional_gene_state_stacked_bar",
         "path": "figure_functional_gene_state.svg",
         "type": "functional_gene_state_stacked_bar", "primary": True},
    ]


def _emit_genomic_event_model_match(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the genomic-event-model-match figure (M11): the tumor event being matched + the
    correspondence class + top genotype-matched models. Gated on having matched models with a real
    correspondence class (data_unavailable / no_target_event with no models → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("event_correspondence_class")
    matched = summary.get("matched_models") or []
    if cls in (None, "data_unavailable", "no_target_event") and not matched:
        return []
    _ensure_methods_path()
    from methods.genomic_event_model_match import cli as gemm
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = gemm.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {"id": "genomic_event_model_match_card",
         "path": "figure_genomic_event_model_match.svg",
         "type": "genomic_event_model_match_card", "primary": True},
    ]


def _emit_abundance_dependency(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the abundance-dependency figure (Q7): protein-abundance→dependency class + correlation
    stats. Gated on a computed correlation (data_unavailable / insufficient / no-r → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("abundance_dependency_class")
    if cls in (None, "data_unavailable", "insufficient_paired_models") \
            or summary.get("protein_dependency_pearson_r") is None:
        return []
    _ensure_methods_path()
    from methods.abundance_dependency import cli as ad
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = ad.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {"id": "abundance_dependency_card",
         "path": "figure_abundance_dependency.svg",
         "type": "abundance_dependency_card", "primary": True},
    ]


CARD_FIGURE_EMITTERS: dict[str, Callable[[dict, Path, str, str], list[dict]]] = {
    "tumor-expression-distribution": _emit_tumor_expression_distribution,
    "alteration-role": _emit_alteration_role,
    "functional-gene-state": _emit_functional_gene_state,
    "genomic-event-model-match": _emit_genomic_event_model_match,
    "abundance-dependency": _emit_abundance_dependency,
    "tumor-vs-normal-percentile-crossing": _emit_tumor_vs_normal_percentile_crossing,
    "normal-tissue-liability-gtex": _emit_normal_tissue_liability_gtex,
    "rna-protein-concordance-tumor": _emit_rna_protein_concordance_tumor,
    "recommended-models": _emit_recommended_models,
    "rna-protein-concordance": _emit_rna_protein_concordance,
    "tumor-expression-distribution-subtype": _emit_tumor_expression_distribution_subtype,
    "pan-cancer-crispr-dependency-distribution": _emit_card1_pan_cancer_dependency_distribution,
    "pan-cancer-rnai-dependency-distribution": _emit_card1b_pan_cancer_rnai_dependency_distribution,
    "crispr-rnai-dependency-concordance": _emit_card1c_crispr_rnai_concordance,
    "expression-distribution": _emit_expression_distribution,
    "copy-number-distribution": _emit_cn_distribution,
    "mutation-type-counts": _emit_mutation_type_counts,
    "dependency-lineage-selectivity": _emit_card2_dependency_lineage_selectivity,
    "expression-dependency-correlation": _emit_card4_expression_dependency_correlation,
    "mutation-stratified-dependency": _emit_card3_mutation_stratified_dependency,
    "dependency-predictability": _emit_dependency_predictability,
    "prism-compound-activity": _emit_prism_compound_activity,
    "prism-crispr-concordance": _emit_prism_crispr_concordance,
    "expression-tumor-vs-adjacent": _emit_expression_tumor_vs_adjacent,
    "tumor-vs-normal-selectivity": _emit_tumor_vs_normal_selectivity,
    # SAFETY tier (viz-debt backfill 2026-07-20):
    "gnomad-lof-constraint": _emit_gnomad_lof_constraint,
    "normal-tissue-liability": _emit_normal_tissue_liability,
    # PROTEIN tier (viz-debt backfill 2026-07-21, Slice 7 — Gygi + CPTAC):
    "protein-abundance-celline": _emit_protein_abundance_celline,
    "protein-presence-cptac": _emit_protein_presence_cptac,
    # TARGET-GRAIN breadth (2026-07-22): pan-cancer by-tissue TPM distribution (TCGA tumor + GTEx
    # normal, one axis) from the quantile product — the RNA companion to the breadth K-of-N roll-up.
    "tumor-elevation-breadth": _emit_tumor_elevation_breadth,
}


def emit_figures_for_card(
    card_id: str, summary: dict, out_root: Path, target: str, indication: str,
) -> list[dict]:
    """Phase-2 helper. For card_id, write figures to out_root/cards/<card_id>/
    and return the list of figure descriptors to attach to the card_output.

    Returns empty list if:
      - no emitter is registered for card_id
      - summary contains _live_read_error (no data to plot)
      - underlying method's data load failed

    Never raises — figure emission is best-effort augmentation, not a critical
    path. A returned [] is the graceful no-op.
    """
    emitter = CARD_FIGURE_EMITTERS.get(card_id)
    if emitter is None:
        return []
    try:
        card_dir = out_root / "cards" / card_id
        figures = emitter(summary, card_dir, target, indication)
        relpath_root = Path("cards") / card_id
        return [
            {**f, "path": str(relpath_root / f["path"])}
            for f in figures
        ]
    except Exception as e:
        import sys as _sys
        print(f"[compose-dashboard:figures] emit failed for {card_id}: {type(e).__name__}: {e}",
              file=_sys.stderr)
        return []
