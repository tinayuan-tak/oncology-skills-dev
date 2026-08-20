"""subtype_survival_association — does OS differ across an indication's molecular subtypes? (Q2-subtype)

The SUBTYPE arm of the differentiation prognostic question: omnibus (k-group) OS log-rank across the
strata of a TCGA-side subgroup-assignment shard. INDICATION-level (target-independent), HYPOTHESIS-
GENERATING. Reuses the TCGA-CDR OS substrate from expression_clinical_association + subgroup_common.

Modules:
    read — read_subtype_survival_association(indication, subgroup_assignments_manifest)
           + classify_subtype_survival_association + multivariate_logrank.
"""
from __future__ import annotations

from .read import (
    read_subtype_survival_association,
    classify_subtype_survival_association,
    multivariate_logrank,
)

METHOD_VERSION = "0.1.0"

__all__ = ["read_subtype_survival_association", "classify_subtype_survival_association",
           "multivariate_logrank", "METHOD_VERSION"]
