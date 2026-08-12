"""sc_surface_concordance — per-gene single-cell RNA <-> surface-protein (CITE-seq ADT) concordance.

The SURFACE-level, cell-type-resolution arm of the `rna_protein_concordance` measurement_type,
alongside the cell-line arm (depmap_rna_protein_concordance) and the tumor arm (CPTAC). Reads the
catalog product `sc-cite-rna-protein-concordance-v1` (per-gene rna_as_biomarker precomputed from
Hao 2021 PBMC CITE-seq) and returns the concordance summary for a target. answers: "does single-cell
RNA detection predict this antigen's SURFACE presence?" — a poor_proxy is decision-relevant for
ADC/TCE/mAb work (RNA cannot stand in for a surface antigen that is post-transcriptionally decoupled).
"""
