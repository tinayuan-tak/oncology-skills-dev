"""Thin card_id -> emitter registry + the phase-2 dispatch helper.

This is the single source the cross-repo `validate_cards.py` figure-emission check scrapes
(regex over the CARD_FIGURE_EMITTERS literal). Adding a card's figure = write an emitter in the
right tier module + add one line here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ._dependency import (
    _emit_card1_pan_cancer_dependency_distribution,
    _emit_card1b_pan_cancer_rnai_dependency_distribution,
    _emit_card1c_crispr_rnai_concordance,
    _emit_card2_dependency_lineage_selectivity,
    _emit_card3_mutation_stratified_dependency,
    _emit_card4_expression_dependency_correlation,
    _emit_cis_feature_expression_coherence,
    _emit_dependency_predictability,
    _emit_organoid_crispr_dependency,
    _emit_prism_compound_activity,
    _emit_prism_crispr_concordance,
)
from ._expression import (
    _emit_cn_distribution,
    _emit_expression_clinical_association,
    _emit_expression_distribution,
    _emit_expression_purity_confound,
    _emit_expression_tumor_vs_adjacent,
    _emit_mutation_type_counts,
    _emit_normal_tissue_liability_gtex,
    _emit_recommended_models,
    _emit_rna_protein_concordance,
    _emit_rna_protein_concordance_tumor,
    _emit_sc_tumor_celltype_expression,
    _emit_tumor_elevation_breadth,
    _emit_tumor_expression_distribution,
    _emit_tumor_expression_distribution_subtype,
    _emit_tumor_vs_normal_percentile_crossing,
    _emit_tumor_vs_normal_selectivity,
)
from ._genomic import (
    _emit_abundance_dependency,
    _emit_alteration_role,
    _emit_functional_gene_state,
    _emit_genomic_event_model_match,
    _emit_phospho_pathway_activity,
)
from ._protein_safety import (
    _emit_gnomad_lof_constraint,
    _emit_normal_tissue_liability,
    _emit_protein_abundance_celline,
    _emit_protein_presence_cptac,
)

CARD_FIGURE_EMITTERS: dict[str, Callable[[dict, Path, str, str], list[dict]]] = {
    "tumor-rna-distribution": _emit_tumor_expression_distribution,
    "tumor-scrna-celltype-expression": _emit_sc_tumor_celltype_expression,
    "alteration-role": _emit_alteration_role,
    "functional-gene-state": _emit_functional_gene_state,
    "genomic-event-model-match": _emit_genomic_event_model_match,
    "abundance-dependency": _emit_abundance_dependency,
    "expression-purity-confound": _emit_expression_purity_confound,
    "expression-clinical-association": _emit_expression_clinical_association,
    "phospho-pathway-activity": _emit_phospho_pathway_activity,
    "tumor-vs-normal-percentile-crossing": _emit_tumor_vs_normal_percentile_crossing,
    "normal-tissue-liability-gtex": _emit_normal_tissue_liability_gtex,
    "rna-protein-concordance-tumor": _emit_rna_protein_concordance_tumor,
    "recommended-models": _emit_recommended_models,
    "cellline-rna-protein-concordance": _emit_rna_protein_concordance,
    "tumor-rna-distribution-by-subtype": _emit_tumor_expression_distribution_subtype,
    "pan-cancer-crispr-dependency-distribution": _emit_card1_pan_cancer_dependency_distribution,
    "pan-cancer-rnai-dependency-distribution": _emit_card1b_pan_cancer_rnai_dependency_distribution,
    "crispr-rnai-dependency-concordance": _emit_card1c_crispr_rnai_concordance,
    "cellline-rna-distribution": _emit_expression_distribution,
    "copy-number-distribution": _emit_cn_distribution,
    "mutation-type-counts": _emit_mutation_type_counts,
    "dependency-lineage-selectivity": _emit_card2_dependency_lineage_selectivity,
    "expression-dependency-correlation": _emit_card4_expression_dependency_correlation,
    "cis-feature-expression-coherence": _emit_cis_feature_expression_coherence,  # cis-dosage scatter (2026-08-20)
    "mutation-stratified-dependency": _emit_card3_mutation_stratified_dependency,
    "dependency-predictability": _emit_dependency_predictability,
    "prism-compound-activity": _emit_prism_compound_activity,
    "prism-crispr-concordance": _emit_prism_crispr_concordance,
    "tumor-rna-vs-adjacent": _emit_expression_tumor_vs_adjacent,
    "tumor-vs-normal-selectivity": _emit_tumor_vs_normal_selectivity,
    # SAFETY tier (2026-07-20):
    "gnomad-lof-constraint": _emit_gnomad_lof_constraint,
    "normal-tissue-liability": _emit_normal_tissue_liability,
    # PROTEIN tier (2026-07-21 — Gygi + CPTAC):
    "cellline-protein-abundance": _emit_protein_abundance_celline,
    "tumor-protein-abundance-cptac": _emit_protein_presence_cptac,
    # TARGET-GRAIN breadth (2026-07-22): pan-cancer by-tissue TPM distribution (TCGA tumor + GTEx
    # normal, one axis) from the quantile product — the RNA companion to the breadth K-of-N roll-up.
    "tumor-elevation-breadth": _emit_tumor_elevation_breadth,
    # ORGANOID tier (2026-08-19): per-lineage dependency bar from the organoid card's
    # per_lineage_stats (no method re-run — self-contained on the summary).
    "organoid-crispr-dependency": _emit_organoid_crispr_dependency,
}


def emit_figures_for_card(
    card_id: str,
    summary: dict,
    out_root: Path,
    target: str,
    indication: str,
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
        return [{**f, "path": str(relpath_root / f["path"])} for f in figures]
    except Exception as e:
        import sys as _sys

        print(f"[figures] emit failed for {card_id}: {type(e).__name__}: {e}", file=_sys.stderr)
        return []
