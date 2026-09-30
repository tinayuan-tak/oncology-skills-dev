"""depmap_rna_protein_concordance — Q5 RNA↔protein concordance (cell-line).

Does RNA predict PROTEIN for this target? The `rna_as_biomarker` question: across DepMap cell
lines, how tightly does per-model target RNA (OmicsExpression log2(TPM+1)) track per-model target
protein (Gygi TMT MS log2-abundance)? A high correlation means RNA is an adequate proxy for protein
(RNA-based biomarkers + RNA-inferred presence are trustworthy); a low correlation means the target
is post-transcriptionally decoupled and protein must be measured directly — a caution flag that
matters acutely for ADC / protein-modality targets and for any RNA patient-selection biomarker.

SCOPE (2026-07-22): CELL-LINE concordance only. The TUMOR (CPTAC) RNA↔protein concordance is
NOT built — CPTAC per-sample protein is landed but there is NO matched per-sample RNA product in the
catalog (CPTAC RNA-seq exists upstream, un-ingested). Named-deferred pending that ingestion (this is
an extraction plan, not an ingestion one). The cell-line concordance is the landed-substrate half.

Substrate (both LANDED, per-ModelID, joinable): RNA = DepMap OmicsExpressionTPMLogp1 (via
depmap_expression_dependency.cli.load_depmap_files_for_card4 — the S3 real-matrix reader); protein =
DepMap Gygi harmonized MS (via depmap_protein_abundance.cli.resolve_accession + load_abundance_column).
"""
