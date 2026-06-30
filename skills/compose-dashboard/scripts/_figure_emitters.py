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

    return [
        {"id": "waterfall", "path": "figure_waterfall.svg", "type": "waterfall_plot", "primary": True},
        {"id": "histogram_kde", "path": "figure_histogram_kde.svg", "type": "histogram_kde", "primary": False},
    ]


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

    return [
        {"id": "forest_plot", "path": "figure_forest_plot.svg", "type": "lineage_forest_plot", "primary": True},
        {"id": "lineage_strip", "path": "figure_lineage_strip.svg", "type": "lineage_strip_plot", "primary": False},
    ]


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

    return [
        {"id": "waterfall_rnai", "path": "figure_waterfall_rnai.svg",
         "type": "ranked_waterfall_rnai", "primary": True},
        {"id": "histogram_kde_rnai", "path": "figure_histogram_kde_rnai.svg",
         "type": "density_histogram_with_kde_rnai", "primary": False},
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
    c1ccli.emit_concordance_scatter(recomputed["per_line_concordance"], target, out_dir, TARGET_CONTRACTS)
    c1ccli.emit_partition_bar(recomputed, target, out_dir, TARGET_CONTRACTS)
    c1ccli.emit_plot_data(recomputed["per_line_concordance"], out_dir)
    c1ccli.emit_manifest(target, "26q1", recomputed, out_dir, [])
    return [
        {"id": "concordance_scatter", "path": "figure_concordance_scatter.svg",
         "type": "scatter_with_quadrants", "primary": True},
        {"id": "concordance_partition_bar", "path": "figure_concordance_partition_bar.svg",
         "type": "stacked_bar", "primary": False},
    ]


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
    return [
        {"id": "mut_vs_wt_strip", "path": "figure_mut_vs_wt_strip.svg",
         "type": "mutation_stratified_strip", "primary": True},
        {"id": "per_hotspot_chronos", "path": "figure_per_hotspot_chronos.svg",
         "type": "per_hotspot_chronos_strip", "primary": False},
    ]


CARD_FIGURE_EMITTERS: dict[str, Callable[[dict, Path, str, str], list[dict]]] = {
    "pan-cancer-crispr-dependency-distribution": _emit_card1_pan_cancer_dependency_distribution,
    "pan-cancer-rnai-dependency-distribution": _emit_card1b_pan_cancer_rnai_dependency_distribution,
    "crispr-rnai-dependency-concordance": _emit_card1c_crispr_rnai_concordance,
    "dependency-lineage-selectivity": _emit_card2_dependency_lineage_selectivity,
    "expression-dependency-correlation": _emit_card4_expression_dependency_correlation,
    "mutation-stratified-dependency": _emit_card3_mutation_stratified_dependency,
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
