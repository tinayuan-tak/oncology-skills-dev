"""RNA / copy-number / presence / selectivity / survival figure emitters.

Part of the _skills_common figure-emitter package (rehomed off the retired compose-dashboard, #654) (Stage-4 split of the monolith).
"""

from __future__ import annotations

from pathlib import Path  # noqa: F401 — type hints (stringized by future-annotations)
from ._common import (  # shared emitter helpers/constants
    _ensure_methods_path, _has_live_read_error, _plotly_from, _dge_cell_contrasts,
    _DGE_SENSITIVITY_CELLS, TARGET_CONTRACTS, METHODS_REPO,
)




def _emit_expression_distribution(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit E3.a figures. Prefer the OFFLINE render seam — if card resolution persisted
    plot_data here (run with plot_data_root), render from it via the method's render_from_plot_data
    (no live re-read, deterministic, byte-identical to a live run, cannot diverge from the verdict).
    Falls back to the legacy live re-execution when no persisted plot_data is present, so every
    consumer (subskill --figures, compose phase-2, gallery) keeps working during the migration."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data_expression.parquet"
    if pd_path.exists():
        from methods.depmap_expression_distribution.figures import render_from_plot_data
        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.depmap_expression_distribution import cli as e3acli
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
         "type": "density_histogram_with_kde", "primary": True},
        {"id": "lineage_strip_expression", "path": "figure_lineage_strip_expression.svg",
         "type": "per_lineage_strip_plot", "primary": False},
        {"id": "waterfall_expression", "path": "figure_waterfall_expression.svg",
         "type": "ranked_waterfall", "primary": False},
    ]
    figures += _plotly_from(e3acli, "emit_plotly_specs", tpm_by_model, model_metadata,
                            target, recomputed, out_dir, TARGET_CONTRACTS, indication)
    return figures



def _emit_mutation_type_counts(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit E4 mutation-type-counts figures. SUMMARY-DRIVEN (Stage 6): the class + lineage bars are
    pure functions of the card summary (compute_summary_stats output the resolver already produced),
    so they draw straight from `summary` — NO live re-read of the DepMap MAF at figure time."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("mutation_landscape_class") == "data_unavailable":
        return []                                   # honest gap — nothing to plot
    _ensure_methods_path()
    from methods.depmap_mutation_type_counts import cli as e4cli

    out_dir.mkdir(parents=True, exist_ok=True)
    e4cli.emit_mutation_class_bar(summary, target, out_dir, TARGET_CONTRACTS)
    e4cli.emit_lineage_class_bar(summary, target, out_dir, TARGET_CONTRACTS)
    return [
        {"id": "mutation_class_bar", "path": "figure_mutation_class_bar.svg",
         "type": "stacked_bar_mutation_class", "primary": True},
        {"id": "mutation_lineage_bar", "path": "figure_mutation_lineage_bar.svg",
         "type": "per_lineage_stacked_bar_mutation", "primary": False},
    ]



def _emit_cn_distribution(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit E3.b copy-number figures. Prefer the OFFLINE render seam (persisted plot_data → method
    render_from_plot_data, no live re-read, cannot diverge from the verdict); fall back to legacy live
    re-execution when no persisted plot_data is present (migration-safe for every consumer)."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data_cn.parquet"
    if pd_path.exists():
        from methods.depmap_cn_distribution.figures import render_from_plot_data
        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.depmap_cn_distribution import cli as e3bcli
    cn_by, model_metadata, assay_used, load_errors = e3bcli.load_cn_files("26q1", target)
    if load_errors or not cn_by:
        return []
    recomputed = e3bcli.compute_summary_stats(cn_by, model_metadata, assay_used=assay_used)
    e3bcli.emit_density_plot(cn_by, target, recomputed, out_dir, TARGET_CONTRACTS)
    e3bcli.emit_lineage_strip(cn_by, model_metadata, target, recomputed, out_dir, TARGET_CONTRACTS)
    e3bcli.emit_waterfall_plot(cn_by, model_metadata, target, recomputed, out_dir, TARGET_CONTRACTS)
    e3bcli.emit_plot_data(cn_by, model_metadata, out_dir)
    e3bcli.emit_manifest(target, "26q1", recomputed, out_dir, [])
    figures = [
        {"id": "density_cn", "path": "figure_density_cn.svg",
         "type": "density_histogram_with_kde", "primary": True},
        {"id": "lineage_strip_cn", "path": "figure_lineage_strip_cn.svg",
         "type": "per_lineage_strip_plot", "primary": False},
        {"id": "waterfall_cn", "path": "figure_waterfall_cn.svg",
         "type": "ranked_waterfall", "primary": False},
    ]
    # Interactive twins — from the SAME cn_by + recomputed the SVGs used (no drift). cn gained a plotly
    # twin with the Stage-3 migration; keep the legacy fallback aligned with the offline render seam.
    figures += _plotly_from(e3bcli, "emit_plotly_specs", cn_by, model_metadata,
                            target, recomputed, out_dir, TARGET_CONTRACTS)
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
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted quantile rows when present (no S3 re-read).
    pd_path = out_dir / "plot_data_pan_cancer_by_tissue.parquet"
    if pd_path.exists():
        from methods.tcga_gtex_tpm_quantiles.figures import render_from_plot_data
        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-read the quantile product live (pre-migration behavior); persist for reuse.
    from methods.tcga_gtex_tpm_quantiles import read as tpmq
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
    """Emit the Q1 per-sample tumor RNA distribution figure (tumor-rna-distribution card):
    tumor (TCGA) vs matched-normal (GTEx) per-sample log2(TPM+1) box+strip with the normal-p95 line
    + fraction-above annotation, from the two long products via tcga_gtex_expression_distribution.
    Indication-scoped. On _live_read_error or no tumor samples → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("tumor_expression_class") == "data_unavailable":
        return []                                   # target absent from TCGA long product here
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted per-sample plot_data when present.
    pd_path = out_dir / "plot_data_expression_distribution.parquet"
    if pd_path.exists():
        from methods.tcga_gtex_expression_distribution.figures import render_from_plot_data
        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.tcga_gtex_expression_distribution import cli as exprdist
    exprdist.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    exprdist.emit_plot_data(target, indication, out_dir)
    figures = [
        {"id": "expression_distribution_per_sample",
         "path": "figure_expression_distribution.svg",
         "type": "per_sample_tumor_normal_distribution", "primary": True},
    ]
    figures += _plotly_from(exprdist, "emit_plotly_specs", target, indication, out_dir, TARGET_CONTRACTS)
    return figures



def _emit_sc_tumor_celltype_expression(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the single-cell per-compartment detection bar (tumor-scrna-celltype-expression card):
    cross-donor median detection_fraction per compartment, malignant highlighted. Summary-driven
    (the summary carries compartment_detection). On _live_read_error or data_unavailable → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("sc_expression_class") == "data_unavailable":
        return []                                   # no product / gene absent (honest gap)
    _ensure_methods_path()
    from methods.sc_tumor_expression_celltype import cli as sccli
    out_dir.mkdir(parents=True, exist_ok=True)
    sccli.emit_compartment_bar(summary, target, out_dir, TARGET_CONTRACTS)
    return [
        {"id": "sc_compartment_detection",
         "path": "figure_sc_compartment_detection.svg",
         "type": "per_compartment_detection_bar", "primary": True},
    ]



def _emit_tumor_expression_distribution_subtype(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the subtype panel (tumor-rna-distribution-by-subtype card): one box+strip row per
    molecular subtype, ordered by median, colored by subtype_signal, pooled-median reference line.
    Gated on subtype_axis_available (no landed shard for the indication → []). The method emitters
    re-read the shared value substrate (no drift). On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or not summary.get("subtype_axis_available"):
        return []                                   # no landed shard for this indication (honest)
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted per-stratum values when present.
    pd_path = out_dir / "plot_data_subtype.parquet"
    if pd_path.exists():
        from methods.tcga_gtex_expression_distribution.figures import render_subtype_from_plot_data
        return render_subtype_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.tcga_gtex_expression_distribution import cli as exprdist
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
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted per-sample plot_data when present (same per-sample
    # figure as Q1 — reuses tcga_gtex_expression_distribution.figures.render_from_plot_data).
    pd_path = out_dir / "plot_data_expression_distribution.parquet"
    if pd_path.exists():
        from methods.tcga_gtex_expression_distribution.figures import render_from_plot_data
        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.tcga_gtex_expression_distribution import cli as exprdist
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
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted atlas when present.
    pd_path = out_dir / "plot_data_normal_tissue_atlas.parquet"
    if pd_path.exists():
        from methods.tcga_gtex_expression_distribution.figures import render_liability_from_plot_data
        return render_liability_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.tcga_gtex_expression_distribution import cli as exprdist
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
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted full model rows when present.
    pd_path = out_dir / "plot_data_recommended_models.parquet"
    if pd_path.exists():
        from methods.patient_model_expression_correspondence.figures import render_from_plot_data
        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.patient_model_expression_correspondence import cli as pmc
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
    """Emit the Q5 RNA↔protein concordance scatter (cellline-rna-protein-concordance card): per-model target
    RNA (x) vs protein (y) with fitted trend + r. Gated on rna_as_biomarker (data_unavailable /
    insufficient → no figure). On _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary or summary.get("rna_as_biomarker") in (None, "data_unavailable",
                                                          "insufficient_paired_models"):
        return []
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted per-model scatter points when present.
    pd_path = out_dir / "plot_data_rna_protein.parquet"
    if pd_path.exists():
        from methods.depmap_rna_protein_concordance.figures import render_from_plot_data
        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.depmap_rna_protein_concordance import cli as rpc
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
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted per-tumor scatter points when present.
    pd_path = out_dir / "plot_data_rna_protein_tumor.parquet"
    if pd_path.exists():
        from methods.depmap_rna_protein_concordance.figures import render_tumor_from_plot_data
        return render_tumor_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.depmap_rna_protein_concordance import cli as rpc
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
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted 3-group per-sample when present (no recount3 re-stream).
    pd_path = out_dir / "plot_data_dge_per_sample.parquet"
    if pd_path.exists():
        from methods.dge_deseq2.figures import render_selectivity_from_plot_data
        return render_selectivity_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: stream per-sample from recount3 live; persist it for reuse (offline next time).
    from methods.dge_deseq2 import read as dge_read
    from methods.dge_deseq2 import emit as dge_emit

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
    dge_emit.emit_plot_data(per_sample, out_dir)
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
    """Emit the DEG figure showing tumor vs adjacent-normal AND tumor vs GTEx-normal.

    Prefers the 3-group panel from the 4-cell sensitivity product (adjacent = cell A, GTEx =
    cell C) via the shared emit_tumor_vs_normal_selectivity_4panel machinery, so the DEG card
    co-shows all three groups (tumor / TCGA-adjacent / GTEx-normal). Falls back to the legacy
    2-group tumor-vs-adjacent compound when no sensitivity product exists for the indication
    (e.g. a target absent from the product, or an indication whose product is not yet built).
    Per-sample log2(CPM+1) streams from recount3 at emit-time (~10-30s first call per
    (target, indication)); a missing recount3 mapping renders a placeholder.
    """
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    from methods.dge_deseq2 import read as dge_read
    from methods.dge_deseq2 import emit as dge_emit

    out_dir.mkdir(parents=True, exist_ok=True)

    # NB no offline seam here (unlike tumor-vs-normal-selectivity): this card's forest is drawn from
    # the separately-read sensitivity GENE-ROW (`sens`), NOT the card verdict `summary` — the card
    # summary does not carry the 4-cell log2fc fields — so an offline render keyed on `summary` would
    # diverge (empty forest). The selectivity sibling IS migrated because its forest already draws
    # off `summary`. Left live; figures.render_adjacent_from_plot_data exists for a future seam once
    # the sensitivity gene-row is persisted alongside per_sample.

    # Preferred: 3-group panel from the 4-cell sensitivity product (cell A = adjacent, cell C = GTEx).
    try:
        sens = dge_read.read_tumor_vs_normal_sensitivity_gene_row(target, indication)
    except Exception:  # noqa: BLE001
        sens = None
    if sens is not None:
        try:
            per_sample = dge_read.read_per_sample_expression_all_three_groups(
                target=target, indication=indication,
            )
        except Exception:  # noqa: BLE001
            per_sample = None
        dge_emit.emit_tumor_vs_normal_selectivity_4panel(
            sensitivity_summary=sens, per_sample_data=per_sample,
            target=target, indication=indication,
            out_dir=out_dir, target_contracts_dir=TARGET_CONTRACTS,
        )
        figures = [
            {"id": "tumor_vs_normal_3group",
             "path": "figure_tumor_vs_normal_selectivity_4panel.svg",
             "type": "box_forest_sensitivity_panel", "primary": True},
        ]
        figures += _plotly_from(dge_emit, "emit_plotly_specs", per_sample,
                                _dge_cell_contrasts(sens), target, indication,
                                out_dir, TARGET_CONTRACTS, "tumor_vs_normal")
        return figures

    # Fallback: legacy 2-group compound (adjacent only).
    try:
        per_sample = dge_read.read_per_sample_expression_tumor_vs_adjacent(
            target=target, indication=indication,
        )
    except Exception:  # noqa: BLE001
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
    contrasts = []
    if summary.get("log2_fc") is not None:
        contrasts = [{"label": "tumor vs adj-normal",
                      "log2_fc": summary["log2_fc"], "q_value": summary.get("q_value")}]
    figures += _plotly_from(dge_emit, "emit_plotly_specs", per_sample, contrasts,
                            target, indication, out_dir, TARGET_CONTRACTS,
                            "tumor_vs_adjacent")
    return figures



def _emit_expression_purity_confound(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the expression-purity-confound figure (Q9): confound class + expression↔purity
    correlation. Gated on a computed correlation (data_unavailable / insufficient / no-r → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("purity_confound_class")
    if cls in (None, "data_unavailable", "insufficient_paired_samples") \
            or summary.get("expression_purity_pearson_r") is None:
        return []
    _ensure_methods_path()
    from methods.expression_purity_confound import cli as epc
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = epc.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {"id": "expression_purity_confound_card",
         "path": "figure_expression_purity_confound.svg",
         "type": "expression_purity_confound_card", "primary": True},
    ]



def _emit_expression_clinical_association(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the expression-clinical-association figure (Q11): survival-association class + log-rank
    stats. Gated on a computed log-rank (data_unavailable / insufficient / no-p → []). On
    _live_read_error → []."""
    if _has_live_read_error(summary):
        return []
    if not summary:
        return []
    cls = summary.get("survival_association_class")
    if cls in (None, "data_unavailable", "insufficient_survival_data") \
            or summary.get("logrank_p") is None:
        return []
    _ensure_methods_path()
    from methods.expression_clinical_association import cli as eca
    out_dir.mkdir(parents=True, exist_ok=True)
    svg = eca.emit_svg(target, indication, summary, out_dir, TARGET_CONTRACTS)
    if svg is None:
        return []
    return [
        {"id": "expression_clinical_association_card",
         "path": "figure_expression_clinical_association.svg",
         "type": "expression_clinical_association_card", "primary": True},
    ]
