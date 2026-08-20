"""Case-keyed patient readers for the patient cis-coherence arm.

All three modalities are read at the 3-segment TCGA CASE barcode grain — the shared key that
tcga-sample-id-crosswalk-v1 established as joinable across TCGA products (CN=DNA aliquots,
expression=RNA aliquots, methylation=case; only the case barcode is common). This module is a
thin composition layer over three EXISTING readers; it adds no new S3 product:

  - expression : tcga_gtex_expression_distribution.read_tumor_samples_with_case
                 (long TPM product; UUID sample_id -> case via the sidecar the crosswalk productionizes)
  - copy-number: tcga_patient_cn_per_sample.read.read_patient_cn_per_sample  (per-(gene,patient) GISTIC)
  - methylation: functional_gene_state.read._read_patient_methylation        (HM450 promoter, {case: bool})
"""
from __future__ import annotations


def read_patient_expression_by_case(target: str, indication: str) -> dict[str, float]:
    """{case_barcode: mean_log2_tpm} for `target` in `indication`. Where a case has >1 tumour
    aliquot, average (rare; keeps one value per patient for the cis correlation)."""
    from methods.tcga_gtex_expression_distribution.read import read_tumor_samples_with_case
    df = read_tumor_samples_with_case(target, indication)
    if df is None or df.empty:
        return {}
    grouped = df.groupby("case")["log2_tpm"].mean()
    return {str(c): float(v) for c, v in grouped.items()}


def read_patient_cn_by_case(target: str, indication: str) -> dict[str, int]:
    """{case_barcode: gistic_call} for `target` in `indication` (discrete GISTIC {-2..+2})."""
    from methods.tcga_patient_cn_per_sample.read import read_patient_cn_per_sample
    return read_patient_cn_per_sample(target, indication)


def read_patient_methylation_by_case(target: str, indication: str) -> dict[str, bool]:
    """{case_barcode: is_promoter_methylated (bool)} for `target` in `indication`."""
    from methods.functional_gene_state.read import _read_patient_methylation
    return _read_patient_methylation(target, indication)
