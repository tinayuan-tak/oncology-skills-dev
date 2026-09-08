"""tcga_patient_cn — per-(gene, indication) PATIENT copy-number prevalence from TCGA GISTIC.

The patient-tumour complement to depmap_cn_distribution (which drives copy_number_class from DepMap
CELL LINES). This reads the raw PanCanAtlas GISTIC discrete calls (all_thresholded.by_genes) — the
proper per-gene amplification AND deletion signal — and summarizes the cohort's amp/del prevalence.

WHY A SEPARATE SOURCE (not the two-hit product): pancan-genomic-two-hit-per-gene-v1's cn_class is
"min value wins" (LoF-biased for two-hit detection), which SYSTEMATICALLY undercounts amplification —
ERBB2 reads deletion-dominant there. The raw GISTIC thresholded file gives honest amp (+1/+2) and
del (-1/-2) per aliquot: ERBB2 BRCA = 31% amplified (11% high-level +2), the true HER2+ rate.

ADDITIVE / verdict-inert DISPLAY facet: emits patient_copy_number_class as a CROSS-CHECK to the
cell-line copy_number_class — it fires NO resolver rung (the CN verdict still rests on the DepMap
cell-line call; rewiring the verdict to prefer patient CN is a separate, explicit decision).

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import (  # noqa: E402,F401
    build_patient_cn_table,
    patient_cn_summary_for_gene,
)
