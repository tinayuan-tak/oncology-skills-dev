"""Protein-abundance (Gygi + CPTAC) and human-genetics safety figure emitters.

Part of the _skills_common figure-emitter package (rehomed off the retired compose-dashboard, #654) (Stage-4 split of the monolith).
"""

from __future__ import annotations

from pathlib import Path  # noqa: F401 — type hints (stringized by future-annotations)
from ._common import (  # shared emitter helpers/constants
    _ensure_methods_path, _has_live_read_error, _plotly_from, _dge_cell_contrasts,
    _DGE_SENSITIVITY_CELLS, TARGET_CONTRACTS, METHODS_REPO,
)




def _emit_protein_abundance_celline(
    summary: dict, out_dir: Path, target: str, indication: str,
) -> list[dict]:
    """Emit the Gygi cell-line protein-abundance figures. Prefer the OFFLINE render seam (persisted
    plot_data → method render_from_plot_data, no live re-read, cannot diverge from the verdict); fall
    back to legacy live re-execution when no persisted plot_data is present. Mirrors
    _emit_expression_distribution. On _live_read_error or no MS detection → []."""
    if _has_live_read_error(summary):
        return []
    _ensure_methods_path()
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted plot_data artifact when present.
    pd_path = out_dir / "plot_data_protein_abundance.parquet"
    if pd_path.exists():
        from methods.depmap_protein_abundance.figures import render_from_plot_data
        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: re-execute the method against live data (pre-migration behavior).
    from methods.depmap_protein_abundance import cli as pac
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
    out_dir.mkdir(parents=True, exist_ok=True)

    # OFFLINE path: render from the persisted per-cohort stats (incl. raw arrays) when present.
    pd_path = out_dir / "plot_data_protein_per_cohort.parquet"
    if pd_path.exists():
        from methods.cptac_protein_deg.figures import render_from_plot_data
        return render_from_plot_data(pd_path, summary, out_dir, target, indication)

    # LEGACY fallback: recompute from the per-sample product live (pre-migration behavior).
    from methods.cptac_protein_deg import read as cptac
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
