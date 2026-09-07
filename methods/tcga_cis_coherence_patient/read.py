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
    """{case_barcode: is_promoter_methylated (bool)} for `target`, SCOPED to `indication`.

    functional_gene_state._read_patient_methylation returns the PAN-COHORT dict by design (it filters
    downstream in _read_patient_arm via ind_patients). This wrapper is a DIRECT consumer with no such
    downstream filter, so it scopes here: map each methylated case -> TCGA cancer-type
    (_load_sample_cancer_types) and keep only the indication's cohorts (INDICATION_TO_TCGA). Without
    this, the caller's coverage provenance (n_cases_methylation) would report the pan-cohort count
    (~2422) while only the indication subset actually feeds the silencing contrast. The silencing
    contrast counts themselves are unchanged (they were already bounded by the expression
    intersection) — this makes the reported coverage honest.

    Degrades safely: unknown indication or a genuinely-absent annotation table -> unfiltered pan dict
    (the caller's expression intersection still bounds it). Transient/creds errors propagate (via
    _load_sample_cancer_types' own discipline) rather than silently zeroing the methylation leg."""
    from methods.functional_gene_state.read import _read_patient_methylation, _load_sample_cancer_types
    from methods.tcga_patient_cn_per_sample.read import INDICATION_TO_TCGA

    meth = _read_patient_methylation(target, indication)
    if not meth:
        return {}
    codes = INDICATION_TO_TCGA.get(indication)
    if not codes:
        return meth  # unknown indication: cannot scope (mirrors tcga_patient_cn_per_sample convention)
    cancer_types = _load_sample_cancer_types()  # {patient_barcode: TCGA cancer type}; {} only on genuine absence
    if not cancer_types:
        return meth  # annotation genuinely absent -> can't scope; leave pan (expr intersection bounds it)
    return {case: is_meth for case, is_meth in meth.items() if cancer_types.get(case) in codes}
