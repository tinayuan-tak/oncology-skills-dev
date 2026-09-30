"""tcga_patient_cn_per_sample — per-(gene, patient) TCGA GISTIC copy-number LONG product.

The per-SAMPLE complement to tcga_patient_cn (which rolls GISTIC up to per-(gene, indication)
prevalence classes). This preserves each patient's discrete GISTIC call so that patient
CN can be JOINED to patient expression / methylation at the case-barcode grain — the
substrate the cis-feature-coherence S4 patient arm needs.

WHY A SEPARATE PRODUCT (not tcga_patient_cn):
  tcga_patient_cn aggregates away per-patient identity (emits recurrence fractions per
  indication). A cis join (patient CN <-> patient expression) needs the per-patient calls
  retained. Materializing them gene-sorted gives predicate-pushdown per-gene reads
  (mirrors tcga-tumor-tpm-recount3-long-v1) instead of re-scanning the 589 MB GISTIC TSV
  per gene (what tcga_patient_cn.read._read_gistic_gene does today).

GRAIN NOTE (critical): GISTIC columns are DNA aliquot barcodes (…-11D-…). Patient
expression comes from RNA aliquots (…-01A-…R-…). The SAME patient carries DIFFERENT
aliquot barcodes per analyte, so CN<->expression joins MUST be at the 3-segment CASE
barcode — never the aliquot. This product therefore emits case_barcode (the join key)
alongside the original GISTIC aliquot barcode (provenance).

Source: gdc-pancanatlas 2018 all_thresholded.by_genes_whitelisted.tsv (GISTIC2 discrete
calls in {-2,-1,0,1,2}). Manifest: tcga-patient-cn-per-sample-v1 (data-catalog).
"""
