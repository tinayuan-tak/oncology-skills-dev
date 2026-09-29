"""depmap_isoform_expression — per-gene MODEL-side isoform-expression summary from DepMap.

The isoform/splice-EXPRESSION axis (roadmap #2), model arm. DepMap 26q3 ships per-transcript TPM
(OmicsExpressionTranscriptTPMLogp1HumanAllGenes.csv, models × ENST) — landed but UNCONSUMED. This
summarizes, per gene, how DOMINATED its expression is by a single isoform across the cell-line panel:

  dominant_isoform_fraction  — median across models of (top-isoform TPM / gene-total TPM). Near 1.0 =
                               one isoform carries essentially all expression (a clean single-isoform
                               target); low = isoform-diverse (alternative splicing — VEGFA, FGFR2).
  n_expressed_isoforms       — median count of isoforms with non-trivial TPM per model.
  isoform_expression_class   — single_isoform_dominant / isoform_diverse / balanced / data_unavailable.

WHY this matters: a target whose expression is one dominant isoform is a cleaner modality/epitope
target (an antibody/ADC/oligo hits a defined transcript); an isoform-diverse target flags that the
functional/druggable isoform must be specified (ties the isoform_selective_targets guardrail +
roadmap #3 domain-modality). CELL-LINE arm — patient-tumour isoform expression (TCGA SpliceSeq) is a
separate, deferred ingestion (see project_roadmap_ideas_backlog #2).

ENST→gene via GENCODE v26 GTF (gencode-v26-primary-assembly), version-stripped join (~83% of DepMap
transcript columns map — DepMap uses a newer GENCODE build; the per-gene FRACTION normalizes over the
matched isoforms). Additive / verdict-inert DISPLAY facet.

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import (  # noqa: E402,F401
    build_isoform_table,
    isoform_summary_for_gene,
)
