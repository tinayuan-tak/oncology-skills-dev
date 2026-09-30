"""patient_model_expression_correspondence — Q4 recommended_models (expression-similarity P3 slice).

The TARGET-FOCUSED patient↔model correspondence: for a (target, indication), which DepMap models
represent the patient tumor population *for that target*, and which are the positive / negative-
control / resistance models for a screen?

SCOPE (P3-Option-B, 2026-07-22): this is the EXPRESSION-SIMILARITY correspondence — it compares the
model's TARGET expression against the patient tumor TARGET distribution (both log2(TPM+1), directly
comparable: recount3/GENCODE-v26 patient TPM vs DepMap OmicsExpressionTPMLogp1). It deliberately does
NOT do:
  - full-transcriptome Celligner alignment (a separate, heavier build), or
  - the genomic "same functional event" join (canonical master-plan P3 / genomic M11) — that needs the
    unbuilt alteration-class harmonization layer the genomic-alteration plan owns.
Both are named-deferred, not silently skipped.

Substrate (both LANDED): patient = tcga-tumor-tpm-recount3-long-v1 (via
tcga_gtex_expression_distribution.read.read_tumor_samples); model = DepMap
OmicsExpressionTPMLogp1 + CRISPRGeneEffect + Model.csv (via
depmap_expression_dependency.cli.load_depmap_files_for_card4).
"""
