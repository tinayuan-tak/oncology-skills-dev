"""CRISPR/RNAi/chemical-genetic dependency figure emitters.

Part of the _skills_common figure-emitter package (rehomed off the retired compose-dashboard, #654) (Stage-4 split of the monolith).
"""

from __future__ import annotations

from pathlib import Path  # noqa: F401 — type hints (stringized by future-annotations)

from ._common import (  # shared emitter helpers/constants
    TARGET_CONTRACTS,
    _ensure_methods_path,
    _has_live_read_error,
    _plotly_from,
)


def _emit_card1_pan_cancer_dependency_distribution(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit Card 1 (chronos) figures. Prefer the OFFLINE render seam — if card resolution persisted
    plot_data here (run with plot_data_root), render from it via the method's render_from_plot_data
    (no live re-read, deterministic, byte-identical to a live run, cannot diverge from the verdict).
    Falls back to the legacy live re-execution when no persisted plot_data is present, so every
    consumer (subskill --figures, compose phase-2, gallery) keeps working during the migration."""
    if _has_live_read_error(summary):
        return []

    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data.parquet"
    if pd_path.exists():
        from onc_methods.depmap_chronos_distribution.figures import render_from_plot_data

        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from onc_methods.depmap_chronos_distribution import cli as c1cli

    chronos_by_model, model_metadata, load_errors = c1cli.load_depmap_files(release_pin="26q1", target_symbol=target)
    if load_errors:
        return []

    recomputed_summary = c1cli.compute_summary_stats(
        chronos_by_model,
        model_metadata,
        strong_threshold=-1.0,
        moderate_threshold=-0.5,
    )
    c1cli.emit_waterfall_plot(
        chronos_by_model,
        model_metadata,
        target,
        recomputed_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    c1cli.emit_histogram_kde_plot(
        chronos_by_model,
        target,
        recomputed_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    c1cli.emit_plot_data(chronos_by_model, model_metadata, -1.0, out_dir)
    c1cli.emit_manifest(target, "26q1", recomputed_summary, chronos_by_model, out_dir, [])

    figures = [
        {"id": "waterfall", "path": "figure_waterfall.svg", "type": "ranked_waterfall", "primary": True},
        {
            "id": "histogram_kde",
            "path": "figure_histogram_kde.svg",
            "type": "density_histogram_with_kde",
            "primary": False,
        },
    ]
    figures += _plotly_from(
        c1cli,
        "emit_plotly_specs",
        chronos_by_model,
        model_metadata,
        target,
        recomputed_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    return figures


def _emit_card2_dependency_lineage_selectivity(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit Card 2 (dependency-lineage-selectivity) figures. Prefer the OFFLINE render seam (persisted
    plot_data → method render_from_plot_data, no live re-read, cannot diverge from the verdict); fall
    back to legacy live re-execution when no persisted plot_data is present (migration-safe)."""
    if _has_live_read_error(summary):
        return []

    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data.parquet"
    if pd_path.exists():
        from onc_methods.depmap_chronos.figures import render_from_plot_data

        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from onc_methods.depmap_chronos import cli as c2cli

    chronos_by_model, model_metadata, load_errors = c2cli.load_depmap_files(release_pin="26q1", target_symbol=target)
    if load_errors:
        return []

    lineage_summary = c2cli.compute_lineage_summary(
        chronos_by_model,
        model_metadata,
        indication=indication,
    )
    # Card 2 v3.0.0 is indication-decoupled. The method output no longer carries
    # `lineage_label`; figure emitter resolves the target lineage from the indication
    # → lineage map (shared INDICATION_LINEAGE constant in the method module). This
    # is the synthesis-layer responsibility.
    target_lineage = c2cli.INDICATION_LINEAGE.get(indication, "")
    merged_data = c2cli.emit_plot_data(
        chronos_by_model,
        model_metadata,
        target_lineage,
        strong_threshold=-1.0,
        out_path=out_dir,
    )
    c2cli.emit_forest_plot(
        lineage_summary.get("_per_lineage_records", []),
        target_lineage,
        target,
        indication,
        lineage_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    c2cli.emit_lineage_strip(
        merged_data,
        target_lineage,
        target,
        indication,
        out_dir,
        TARGET_CONTRACTS,
    )
    c2cli.emit_manifest(target, indication, "26q1", lineage_summary, chronos_by_model, out_dir, [])

    figures = [
        {"id": "forest_plot", "path": "figure_forest_plot.svg", "type": "lineage_forest_plot", "primary": True},
        {"id": "lineage_strip", "path": "figure_lineage_strip.svg", "type": "lineage_strip_plot", "primary": False},
    ]
    # Interactive twin — per-lineage forest from the SAME _per_lineage_records the SVG used (no drift).
    figures += _plotly_from(
        c2cli,
        "emit_plotly_specs",
        lineage_summary.get("_per_lineage_records", []),
        target_lineage,
        target,
        indication,
        lineage_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    return figures


def _emit_card4_expression_dependency_correlation(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit Card 4 (expression-dependency-correlation) figures. Prefer the OFFLINE render seam
    (persisted plot_data → method render_from_plot_data, no live re-read); fall back to legacy live
    re-execution when no persisted plot_data is present (migration-safe)."""
    if _has_live_read_error(summary):
        return []

    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data.parquet"
    if pd_path.exists():
        from onc_methods.depmap_expression_dependency.figures import render_from_plot_data

        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from onc_methods.depmap_expression_dependency import cli as c4cli

    out_dir.mkdir(parents=True, exist_ok=True)
    chronos_by_model, tpm_by_model, model_metadata, load_errors = c4cli.load_depmap_files_for_card4(
        release_pin="26q1", target_symbol=target
    )
    if load_errors:
        return []
    if not chronos_by_model or not tpm_by_model:
        return []

    recomputed_summary = c4cli.compute_correlation_summary(
        chronos_by_model,
        tpm_by_model,
        model_metadata,
        indication=indication,
    )
    target_lineage = recomputed_summary.get("_target_lineage", "")
    merged = c4cli.build_merged_data(
        chronos_by_model,
        tpm_by_model,
        model_metadata,
        target_lineage,
    )

    c4cli.emit_plot_data(merged, out_dir)
    c4cli.emit_scatter_regression_plot(
        merged,
        target,
        indication,
        recomputed_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    c4cli.emit_lineage_stratified_scatter(
        merged,
        target,
        indication,
        recomputed_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    c4cli.emit_manifest(target, indication, "26q1", recomputed_summary, {}, out_dir, [])

    return [
        {
            "id": "scatter_with_regression",
            "path": "figure_scatter_with_regression.svg",
            "type": "expression_chronos_scatter",
            "primary": True,
        },
        {
            "id": "lineage_stratified_scatter",
            "path": "figure_lineage_stratified_scatter.svg",
            "type": "lineage_stratified_scatter",
            "primary": False,
        },
    ]


def _emit_cis_feature_expression_coherence(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit the cis-feature-expression-coherence cn_expression_scatter. Prefer the OFFLINE render seam
    (persisted plot_data → figures.render_from_plot_data, no live re-read); fall back to legacy live
    re-execution when no persisted plot_data is present (migration-safe)."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data.parquet"
    if pd_path.exists():
        from onc_methods.depmap_cis_dosage.figures import render_from_plot_data

        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from onc_methods.depmap_cis_dosage import figures as F
    from onc_methods.depmap_cis_dosage.cli import compute_cis_dosage

    cn_by_model, tpm_by_model, model_metadata, load_errors = F.load_cn_tpm_model(target, release_pin="26q1")
    if load_errors or not cn_by_model or not tpm_by_model:
        return []
    recomputed = compute_cis_dosage(cn_by_model, tpm_by_model)
    merged = F.build_merged_data(cn_by_model, tpm_by_model, model_metadata)
    F.emit_plot_data(merged, out_dir)
    F.emit_cn_expression_scatter(merged, target, indication, recomputed, out_dir, TARGET_CONTRACTS)
    return [
        {
            "id": "cn_vs_expression_scatter",
            "path": "figure_cn_expression_scatter.svg",
            "type": "cn_expression_scatter",
            "primary": True,
        },
    ]


def _emit_card1b_pan_cancer_rnai_dependency_distribution(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit Card 1b (RNAi) figures. Prefer the OFFLINE render seam (persisted plot_data → method
    render_from_plot_data, no live re-read, cannot diverge from the verdict); fall back to legacy live
    re-execution when no persisted plot_data is present (migration-safe for every consumer)."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data_rnai.parquet"
    if pd_path.exists():
        from onc_methods.depmap_demeter_distribution.figures import render_from_plot_data

        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from onc_methods.depmap_demeter_distribution import cli as c1bcli

    demeter_by_model, model_metadata, load_errors = c1bcli.load_rnai_files(release_pin="26q1", target_symbol=target)
    if load_errors or not demeter_by_model:
        return []

    recomputed_summary = c1bcli.compute_summary_stats(
        demeter_by_model,
        model_metadata,
        strong_threshold=-0.5,
        moderate_threshold=-0.25,
    )
    c1bcli.emit_waterfall_plot(
        demeter_by_model,
        model_metadata,
        target,
        recomputed_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    c1bcli.emit_histogram_kde_plot(
        demeter_by_model,
        target,
        recomputed_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    c1bcli.emit_plot_data(demeter_by_model, model_metadata, -0.5, out_dir)
    c1bcli.emit_manifest(target, "26q1", recomputed_summary, demeter_by_model, out_dir, [])

    figures = [
        {"id": "waterfall_rnai", "path": "figure_waterfall_rnai.svg", "type": "ranked_waterfall", "primary": True},
        {
            "id": "histogram_kde_rnai",
            "path": "figure_histogram_kde_rnai.svg",
            "type": "density_histogram_with_kde",
            "primary": False,
        },
    ]
    # Interactive twins — from the SAME demeter_by_model + recomputed_summary the SVGs used (no drift).
    figures += _plotly_from(
        c1bcli,
        "emit_plotly_specs",
        demeter_by_model,
        model_metadata,
        target,
        recomputed_summary,
        out_dir,
        TARGET_CONTRACTS,
    )
    return figures


def _emit_card1c_crispr_rnai_concordance(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit Card 1c (crispr-rnai-concordance) figures. Prefer the OFFLINE render seam (persisted
    plot_data → method render_from_plot_data, no live re-read); fall back to legacy live re-execution
    when no persisted plot_data is present (migration-safe)."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data_concordance.parquet"
    if pd_path.exists():
        from onc_methods.depmap_crispr_rnai_concordance.figures import render_from_plot_data

        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from onc_methods.depmap_crispr_rnai_concordance import cli as c1ccli

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
        {
            "id": "concordance_overlay_density",
            "path": "figure_concordance_overlay_density.svg",
            "type": "overlay_kde_with_rug",
            "primary": True,
        },
        {
            "id": "concordance_partition_bar",
            "path": "figure_concordance_partition_bar.svg",
            "type": "stacked_bar",
            "primary": False,
        },
        {
            "id": "concordance_scatter",
            "path": "figure_concordance_scatter.svg",
            "type": "scatter_with_quadrants",
            "primary": False,
        },
    ]
    # Interactive twin — the CRISPR-vs-RNAi scatter from the SAME per_line_concordance (no drift).
    figures += _plotly_from(
        c1ccli, "emit_plotly_specs", recomputed["per_line_concordance"], target, out_dir, TARGET_CONTRACTS
    )
    return figures


def _emit_card3_mutation_stratified_dependency(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit Card 3 (mutation-stratified-dependency) figures. Prefer the OFFLINE render seam (persisted
    plot_data → method render_from_plot_data, no live re-read); fall back to legacy live re-execution
    when no persisted plot_data is present (migration-safe)."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data.parquet"
    if pd_path.exists():
        from onc_methods.depmap_mutation_dependency.figures import render_from_plot_data

        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from onc_methods.depmap_chronos_distribution import cli as c1cli
    from onc_methods.depmap_mutation_dependency import cli as c3cli

    chronos_by_model, model_metadata, load_errors = c1cli.load_depmap_files(release_pin="26q1", target_symbol=target)
    if load_errors or not chronos_by_model:
        return []
    hot, dam, mut_errs = c3cli.load_mutation_data("26q1", target)
    if mut_errs:
        return []

    recomputed = c3cli.compute_mutation_stratification(chronos_by_model, hot, dam)
    c3cli.emit_plot_data(chronos_by_model, hot, dam, model_metadata, out_dir)
    c3cli.emit_mut_vs_wt_strip_plot(chronos_by_model, hot, dam, target, recomputed, out_dir, TARGET_CONTRACTS)
    c3cli.emit_per_hotspot_chronos_plot(
        chronos_by_model, recomputed.get("per_hotspot_stats", []), target, out_dir, TARGET_CONTRACTS
    )
    c3cli.emit_manifest(target, indication, "26q1", recomputed, out_dir, [])
    # Interactive twin — mut-vs-WT box+strip from the SAME chronos + hotspot/damaging membership (no drift).
    plotly_figs = _plotly_from(
        c3cli, "emit_plotly_specs", chronos_by_model, hot, dam, target, recomputed, out_dir, TARGET_CONTRACTS
    )
    return plotly_figs + [
        {
            "id": "mut_vs_wt_strip",
            "path": "figure_mut_vs_wt_strip.svg",
            "type": "mutation_stratified_strip",
            "primary": True,
        },
        {
            "id": "per_hotspot_chronos",
            "path": "figure_per_hotspot_chronos.svg",
            "type": "per_hotspot_chronos_strip",
            "primary": False,
        },
    ]


def _emit_dependency_predictability(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
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
    from onc_methods.depmap_predictability import cli as e5cli
    from onc_methods.depmap_predictability import read as e5read

    out_dir.mkdir(parents=True, exist_ok=True)
    e5cli.emit_feature_importance_bar(summary, target, out_dir, TARGET_CONTRACTS)
    e5cli.emit_lineage_conditional_panel(summary, target, out_dir, TARGET_CONTRACTS)
    # Provenance follows the data: read the pin + resolved parquet the reader
    # (read_predictability) stamped onto the summary rather than hardcoding a
    # literal that silently drifts when the default pin moves. Fall back to the
    # reader's default (+ a re-resolve) only for an older summary that predates
    # the provenance stamp.
    release_pin = summary.get("_release_pin") or e5read.DEFAULT_RELEASE_PIN
    parquet_uri = summary.get("_derived_product_uri") or e5cli.RELEASE_PIN_TO_PARQUET.get(release_pin, "<unset>")
    e5cli.emit_manifest(target, release_pin, summary, out_dir, parquet_uri)
    figures = [
        {
            "id": "feature_importance_bar",
            "path": "figure_feature_importance_bar.svg",
            "type": "horizontal_bar_feature_importance",
            "primary": True,
        },
        {
            "id": "lineage_predictability",
            "path": "figure_lineage_predictability.svg",
            "type": "horizontal_bar_lineage_predictability",
            "primary": False,
        },
    ]
    # Interactive twin — top-10 SHAP feature-importance bar from the SAME summary (no drift).
    figures += _plotly_from(e5cli, "emit_plotly_specs", summary, target, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_prism_compound_activity(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
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
    from onc_methods.depmap_prism_activity import cli as e6cli

    out_dir.mkdir(parents=True, exist_ok=True)
    e6cli.emit_top_compounds_bar(summary, target, out_dir, TARGET_CONTRACTS)
    e6cli.emit_lineage_activity_bar(summary, target, out_dir, TARGET_CONTRACTS)
    e6cli.emit_activity_vocabulary_panel(summary, target, out_dir, TARGET_CONTRACTS)
    parquet_uri = e6cli.RELEASE_PIN_TO_PARQUET.get("prism-activity-v4", "<unset>")
    e6cli.emit_manifest(target, "prism-activity-v4", summary, out_dir, parquet_uri)
    return [
        {
            "id": "top_compounds_bar",
            "path": "figure_top_compounds_bar.svg",
            "type": "horizontal_bar_top_compounds",
            "primary": True,
        },
        {
            "id": "lineage_activity_bar",
            "path": "figure_lineage_activity_bar.svg",
            "type": "horizontal_bar_per_lineage",
            "primary": False,
        },
        {
            "id": "activity_vocab_panel",
            "path": "figure_activity_vocab_panel.svg",
            "type": "text_summary_panel",
            "primary": False,
        },
    ]


def _emit_prism_crispr_concordance(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
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
    from onc_methods.depmap_prism_crispr_concordance import cli as e7cli

    out_dir.mkdir(parents=True, exist_ok=True)
    e7cli.emit_concordance_scatter(summary, target, out_dir, TARGET_CONTRACTS)
    e7cli.emit_dual_responders_bar(summary, target, out_dir, TARGET_CONTRACTS)
    e7cli.emit_concordance_vocabulary_panel(summary, target, out_dir, TARGET_CONTRACTS)
    parquet_uri = e7cli.RELEASE_PIN_TO_PARQUET.get("prism-activity-v4", "<unset>")
    e7cli.emit_manifest(target, "prism-activity-v4", summary, out_dir, parquet_uri)
    figures = [
        {
            "id": "concordance_scatter",
            "path": "figure_concordance_scatter.svg",
            "type": "two_d_scatter_correlation",
            "primary": True,
        },
        {
            "id": "dual_responders_bar",
            "path": "figure_dual_responders_bar.svg",
            "type": "horizontal_bar_paired_dual_responders",
            "primary": False,
        },
        {
            "id": "concordance_vocab_panel",
            "path": "figure_concordance_vocab_panel.svg",
            "type": "text_summary_panel",
            "primary": False,
        },
    ]
    # Interactive twin — per-compound ρ-CRISPR vs ρ-RNAi scatter from the SAME summary (no drift).
    figures += _plotly_from(e7cli, "emit_plotly_specs", summary, target, out_dir, TARGET_CONTRACTS)
    return figures


def _emit_organoid_crispr_dependency(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Organoid CRISPR dependency figure: a horizontal bar of frac_dependent by ORGANOID LINEAGE
    (from the card's per_lineage_stats), with dependency-band reference lines (0.2 selective / 0.5
    broad / 0.9 pan-essential) and the indication-matched lineage highlighted. Self-contained (reads
    the summary the card already emitted — no method re-run). On _live_read_error / no per-lineage
    data → [] (the pan-organoid summary still renders numerically without a figure)."""
    if _has_live_read_error(summary):
        return []
    stats = (summary or {}).get("per_lineage_stats") or []
    if not stats:
        return []
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    try:
        style = TARGET_CONTRACTS / "plot_styles" / "takeda_oncology.mplstyle"
        if style.exists():
            plt.style.use(str(style))
    except Exception:  # noqa: BLE001 — style is cosmetic
        pass
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = sorted(stats, key=lambda r: r.get("frac_dependent") or 0.0)  # ascending → longest on top
    labels = [f"{r.get('lineage')} (n={r.get('n_models_screened')})" for r in rows]
    fracs = [float(r.get("frac_dependent") or 0.0) for r in rows]
    hi_lineage = summary.get("organoid_lineage")
    # Highlight the indication-matched lineage; others muted.
    colors = ["#cf2828" if r.get("lineage") == hi_lineage else "#1f4e79" for r in rows]

    fig, ax = plt.subplots(figsize=(6.0, max(2.0, 0.5 * len(rows) + 1.2)))
    ax.barh(range(len(rows)), fracs, color=colors, edgecolor="#0a2540", linewidth=0.5, zorder=3)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("fraction of organoids dependent (Chronos gene-effect < -0.5)")
    for cut, lab in [(0.2, "selective"), (0.5, "broad"), (0.9, "pan-ess.")]:
        ax.axvline(cut, color="#888", linestyle="--", linewidth=0.7, zorder=1)
        ax.text(cut, len(rows) - 0.4, lab, fontsize=6.5, color="#666", ha="center", va="bottom")
    pan = summary.get("frac_dependent")
    title = f"{target} — organoid CRISPR dependency by lineage"
    if pan is not None:
        title += f"  (pan-organoid {pan:.2f})"
    if hi_lineage:
        title += f"\nindication {indication} → {hi_lineage} (red)"
    ax.set_title(title, fontsize=10)
    ax.grid(axis="x", alpha=0.25, linewidth=0.4)
    fig.tight_layout()
    out_path = out_dir / "figure_organoid_lineage_dependency.svg"
    fig.savefig(out_path)
    plt.close(fig)
    return [
        {
            "id": "organoid_lineage_dependency",
            "path": "figure_organoid_lineage_dependency.svg",
            "type": "organoid_lineage_dependency_bar",
            "primary": True,
        }
    ]


def _emit_cn_stratified_dependency(
    summary: dict,
    out_dir: Path,
    target: str,
    indication: str,
) -> list[dict]:
    """Emit CN stratified dependency figures.

    Primary figure: strip plot showing Chronos scores stratified by 4 CN categories:
      - Focal amp (GISTIC ≥2)
      - Shallow gain (GISTIC 1-2)
      - Shallow del (GISTIC -2 to -1)
      - Deep del (GISTIC ≤-2)

    With indication-specific cell lines highlighted with black outlines and
    dual medians (pan-DepMap solid, indication dashed).
    """
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    from methods.depmap_chronos_distribution import cli as c1cli
    from methods.depmap_cn_dependency import cli as cncli
    from methods.depmap_cn_distribution import cli as cn_dist_cli

    chronos_by_model, model_metadata, load_errors = c1cli.load_depmap_files(release_pin="26q1", target_symbol=target)
    if load_errors or not chronos_by_model:
        return []

    cn_by_model, _, _, cn_errs = cn_dist_cli.load_cn_files("26q1", target)
    if cn_errs or not cn_by_model:
        return []

    figures_created = cncli.emit_cn_stratified_strip_plot(
        chronos_by_model,
        cn_by_model,
        target,
        summary,
        out_dir,
        TARGET_CONTRACTS,
        model_metadata=model_metadata,
        indication=indication,
    )

    result = []
    if "figure_cn_amplification_strip.svg" in figures_created:
        result.append({
            "id": "cn_amplification_strip",
            "path": "figure_cn_amplification_strip.svg",
            "type": "cn_amplification_dependency_strip",
            "primary": True,
        })
    if "figure_cn_deletion_strip.svg" in figures_created:
        result.append({
            "id": "cn_deletion_strip",
            "path": "figure_cn_deletion_strip.svg",
            "type": "cn_deletion_dependency_strip",
            "primary": False,
        })
    return result
