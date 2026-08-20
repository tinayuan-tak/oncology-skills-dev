"""compute_patient_cis_coherence — the PATIENT arm of cis-feature-expression-coherence.

The cell-line arm (depmap_cis_dosage) asks "across cancer cell lines, does copy-number track the
gene's own expression?" This asks the SAME question in patient tumours, PLUS an epigenetic leg:

  1. CN -> expression coupling: does patient copy-number track patient expression? Reuses the exact
     depmap_cis_dosage.compute_cis_dosage statistic (Spearman-driven cis_dosage_class), fed patient
     {case: gistic_call} and {case: log2_tpm} intersected on the case barcode. GISTIC discrete
     {-2..+2} is an ordinal CN; Spearman (rank) handles it. amplification_threshold=1 (GISTIC +1 =
     gain) for the descriptive amplified-vs-neutral contrast.

  2. Promoter-methylation -> expression silencing: do promoter-methylated patients express the gene
     LOWER than unmethylated patients? A negative delta (methylated lower) is epigenetic-silencing
     cis-coherence — the LoF analogue of amplification-driven cis-coherence.

VERDICT-INERT: this is an additive patient facet. It does not drive any resolver rung; the
cis_coherence verdict stays on the cell-line arm. Cell-line coherence is necessary-not-sufficient
for a patient cis-driver claim (skill Boundaries note); this arm supplies the patient corroboration.

Bridged entirely at the case barcode — the joinability tcga-sample-id-crosswalk-v1 guarantees.
"""
from __future__ import annotations

from methods.depmap_cis_dosage.cli import compute_cis_dosage
from methods.tcga_cis_coherence_patient import read as _read

# Methylation silencing thresholds.
SILENCING_DELTA_LOG2TPM = 1.0   # methylated cases express >= 1 log2 unit (~2x) LOWER = silencing
MIN_METHYLATED = 5              # need >= this many methylated AND unmethylated cases to call
# GISTIC +1 (any gain) is the "amplified" edge for the descriptive amp-vs-neutral expression contrast.
GISTIC_AMPLIFIED_THRESHOLD = 1.0


def _methylation_silencing(expr: dict[str, float], meth: dict[str, bool]) -> dict:
    """Contrast expression of promoter-methylated vs unmethylated cases (intersection on case)."""
    meth_vals = [expr[c] for c, m in meth.items() if m and c in expr]
    unmeth_vals = [expr[c] for c, m in meth.items() if (not m) and c in expr]
    n_m, n_u = len(meth_vals), len(unmeth_vals)
    out = {
        "n_methylated": n_m, "n_unmethylated": n_u,
        "mean_log2tpm_methylated": (sum(meth_vals) / n_m) if n_m else None,
        "mean_log2tpm_unmethylated": (sum(unmeth_vals) / n_u) if n_u else None,
        "delta_log2tpm_methylated_vs_unmethylated": None,
        "patient_methylation_silencing_class": "insufficient_methylation_data",
    }
    if n_m < MIN_METHYLATED or n_u < MIN_METHYLATED:
        return out
    delta = out["mean_log2tpm_methylated"] - out["mean_log2tpm_unmethylated"]
    out["delta_log2tpm_methylated_vs_unmethylated"] = float(delta)
    out["patient_methylation_silencing_class"] = (
        "epigenetic_silencing" if delta <= -SILENCING_DELTA_LOG2TPM else "no_silencing_signal")
    return out


def compute_patient_cis_coherence(target: str, indication: str) -> dict:
    """Patient CN->expression coupling + methylation->expression silencing for `target`/`indication`.

    Returns a self-contained dict: the CN cis-dosage leg (patient_cis_dosage_class + metrics, from
    compute_cis_dosage), the methylation-silencing leg, and join-coverage provenance. Empty modality
    dicts propagate honestly (compute_cis_dosage -> data_unavailable; methylation -> insufficient)."""
    expr = _read.read_patient_expression_by_case(target, indication)
    cn = _read.read_patient_cn_by_case(target, indication)
    meth = _read.read_patient_methylation_by_case(target, indication)

    # CN -> expression, intersected on the case barcode.
    cases = set(cn) & set(expr)
    cn_sub = {c: cn[c] for c in cases}
    expr_sub = {c: expr[c] for c in cases}
    cis = compute_cis_dosage(cn_sub, expr_sub, amplification_threshold=GISTIC_AMPLIFIED_THRESHOLD)

    silencing = _methylation_silencing(expr, meth)

    return {
        "target": target,
        "indication": indication,
        "evidence_scope": "patient_indication",
        # CN cis-dosage leg (same fields as the cell-line arm, "patient_" namespaced at the class).
        "patient_cis_dosage_class": cis["cis_dosage_class"],
        "cn_expr_spearman_r": cis["cn_expr_spearman_r"],
        "cn_expr_spearman_p": cis["cn_expr_spearman_p"],
        "delta_log2tpm_amplified_vs_neutral": cis["delta_log2tpm_amplified_vs_neutral"],
        "n_amplified": cis["n_amplified"],
        "n_patients_cn_expr": len(cases),
        # methylation-silencing leg.
        **{k: silencing[k] for k in (
            "patient_methylation_silencing_class",
            "delta_log2tpm_methylated_vs_unmethylated",
            "n_methylated", "n_unmethylated",
            "mean_log2tpm_methylated", "mean_log2tpm_unmethylated")},
        # join-coverage provenance (honest attrition surfacing).
        "n_cases_expression": len(expr),
        "n_cases_copy_number": len(cn),
        "n_cases_methylation": len(meth),
        "_cis_dosage_full": cis,
    }
