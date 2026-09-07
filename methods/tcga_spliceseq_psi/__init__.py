"""tcga_spliceseq_psi — per-(gene, indication) PATIENT alternative-splicing summary from TCGA SpliceSeq.

The PATIENT arm of the isoform/splice-EXPRESSION axis (roadmap #2). TCGA SpliceSeq (Ryan et al.,
NAR 2016) ships per-(gene, splice-event) PSI (Percent-Spliced-In, 0-1) across TCGA tumours for 7
event classes (AA/AD/ES/RI/AP/AT/ME), with matched-normal samples where available. This method
summarizes, per gene per indication, how splicing-dysregulated the gene is in patient tumours:

  splicing_dysregulation_class — tumor_shifted / highly_variable / stable / data_unavailable
  n_splice_events, max/median_event_psi_std, n_variable_events, n_tumor_shifted_events,
  dominant_event_splice_type, n_tumor_samples, n_normal_samples

WHY: the model arm (depmap_isoform_expression) says WHICH transcript a cell line expresses; this
says which SPLICE EVENTS vary or shift in patient TUMOURS — the tumour-native complement, with
matched normals enabling a tumour-vs-normal PSI shift. Ties the isoform_selective_targets guardrail
(p95HER2/AR-V7/METex14/EGFRvIII are splice/isoform events) with patient evidence. Additive /
verdict-inert DISPLAY facet.

Product-first reader over the gene-sorted tcga-spliceseq-psi-per-gene-v1 product; the builder
streams the 33 per-tissue SpliceSeq files once.

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import (  # noqa: E402,F401
    spliceseq_summary_for_gene,
    build_spliceseq_psi_table,
)
