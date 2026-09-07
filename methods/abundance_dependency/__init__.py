"""abundance_dependency — does target PROTEIN abundance predict its own DEPENDENCY? (expression Q7)

The "expression-as-biomarker-of-dependency" question, PROTEIN arm. The existing
expression-dependency-correlation card carries the RNA→dependency arm (DepMap TPM vs Chronos); this
method adds the PROTEIN→dependency arm (DepMap Gygi-MS abundance vs Chronos) — often the sharper
predictor, because dependency is a protein-level phenomenon and RNA is an imperfect proxy (see Q5
rna_as_biomarker). The COMPARISON of the two arms is itself the signal: protein→dep strong while
RNA→dep weak ⇒ protein is the biomarker to use for patient selection.

ZERO new ingestion — reuses two landed loaders:
  - depmap_protein_abundance: resolve_accession(target) + load_abundance_column(ac) →
    {ModelID: log2_protein_abundance} (Gygi TMT MS, ~12.5k proteins).
  - depmap_expression_dependency: load_depmap_files_for_card4 → {ModelID: Chronos} + lineage meta.

Emits abundance_dependency_class ∈ {protein_predicts_dependency, weak_protein_dependency_link,
no_protein_dependency_link, insufficient_paired_models, data_unavailable} + the correlation stats.

ROUTES (master-sequencing Part 3): Required (C, abundance→dependency chain) + biomarker synthesis
(preferred_assay: protein when protein→dep beats RNA→dep). Biology axis; no modality-gate facet.

Modules:
    read — read_abundance_dependency(target, indication): the protein→Chronos correlation + class.
"""

from __future__ import annotations

from .read import read_abundance_dependency

METHOD_VERSION = "0.1.0"

__all__ = ["read_abundance_dependency", "METHOD_VERSION"]
