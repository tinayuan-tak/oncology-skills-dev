"""expression_clinical_association — does target expression stratify patient survival? (expr Q11)

For a (target, indication): split the indication's TCGA tumors by target expression (high vs low,
median split) and test whether the two groups differ in overall survival (log-rank). Answers the
yardstick's Q11 "clinical/survival context" — a HYPOTHESIS-GENERATING association, NOT a clinical
claim.

  - expression_high_worse_survival → high target expression associates with WORSE OS (candidate
    poor-prognosis / more-aggressive-disease marker; supports targeting rationale + patient selection).
  - expression_high_better_survival → high expression associates with BETTER OS (a caution — the
    target may mark indolent disease; targeting rationale is weaker).
  - no_survival_association → expression does not stratify survival in this indication.

ZERO new ingestion — reuses:
  - tcga_gtex_expression_distribution.read_tumor_samples_with_case → per-sample [case, log2_tpm].
  - PanCanAtlas TCGA-CDR (Liu 2018): curated per-patient OS/OS.time (+ PFI/DSS/DFI), joined on
    bcr_patient_barcode. Same PanCanAtlas snapshot as the M6 / Q9 substrate.

Discipline: median-split OS with a log-rank p + hazard-direction, reported with explicit caveats
(univariate, unadjusted for stage/age, exploratory, multiple-testing-naive). This is a screening
signal for the biomarker/clinical facet, not a survival model.

ROUTES (master-sequencing Part 3): Patient-population / clinical-precedent context + biomarker facet
(prognostic stratification). Biology axis; no modality-gate facet.

Modules:
    read — read_expression_clinical_association(target, indication): the median-split OS log-rank + class.
"""

from __future__ import annotations

from .read import classify_survival_association, read_expression_clinical_association

METHOD_VERSION = "0.1.0"

__all__ = ["read_expression_clinical_association", "classify_survival_association", "METHOD_VERSION"]
