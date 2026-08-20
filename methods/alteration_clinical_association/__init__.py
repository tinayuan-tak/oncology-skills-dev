"""alteration_clinical_association — does target ALTERATION status stratify survival? (Q11-alteration)

The alteration analog of expression_clinical_association: for a (target, indication), split the
indication's MC3-profiled TCGA patients by whether they carry a somatic {target} mutation vs
wild-type and log-rank overall survival. HYPOTHESIS-GENERATING prognostic association (biomarker-
definability facet), NOT a clinical claim. Reuses the TCGA-CDR OS substrate + self-contained
log-rank engine from expression_clinical_association; cohort/altered from tcga-mc3-per-sample-maf-v1.

Modules:
    read — read_alteration_clinical_association(target, indication) + classify_alteration_survival_association.
"""
from __future__ import annotations

from .read import read_alteration_clinical_association, classify_alteration_survival_association

METHOD_VERSION = "0.1.0"

__all__ = ["read_alteration_clinical_association", "classify_alteration_survival_association",
           "METHOD_VERSION"]
