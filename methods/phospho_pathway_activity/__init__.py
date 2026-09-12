"""phospho_pathway_activity — is the target's biology supported at the PHOSPHO level? (expr Q8)

For a (target, indication): from CPTAC phosphoproteomics, summarize the target's phosphorylation —
how many phosphosites are detected, and (the yardstick's key question) is the target PHOSPHORYLATED
beyond just being ABUNDANT? For kinases / signaling proteins, phosphorylation is a proxy for PATHWAY
ACTIVITY / activation state that TOTAL abundance (Q1/Q5) misses.

  - phospho_active            → phosphosites detected in a substantial fraction of tumors AND (where
                                total protein is available) the phospho signal is not merely tracking
                                abundance (phospho-high beyond protein-high) → active signaling.
  - phospho_present           → phosphosites detected, but at/below the abundance expectation (present,
                                not clearly hyper-activated).
  - phospho_low               → few/no phosphosites detected despite the gene being in the panel.
  - phospho_not_detected      → NO phosphosites for the gene in this cohort's panel, while its TOTAL
                                PROTEIN *is* detected in the same cohort — a MEASURED no-detection.
  - data_unavailable          → no CPTAC cohort for the indication, a read failure, or the gene's total
                                protein is not detected in this cohort either (axis UNINFORMATIVE).

TOKEN RETIREMENT (1.2.0, 2026-09-12): `not_phosphoprotein` claimed a biological state from a COVERAGE
FLOOR — the phospho panel covers ~4.7-6.1k genes per cohort vs ~7.4-11.5k for total protein, so ~48-55%
of protein-detected genes per cohort have zero phosphosites and ~1.7-2.3k of those DO carry sites in
another CPTAC cohort. ALK (0 sites in all 10 cohorts), CDK4, MET and KRAS all read "not a phosphoprotein"
somewhere. Replaced by phospho_not_detected + the total_protein_detected_in_cohort /
n_cohorts_with_phosphosites / phosphoprotein_detected_in_other_cohorts evidence fields.

ZERO new ingestion — reads the `cptac` PYTHON PACKAGE's harmonized `phosphoproteomics` [bcm]
dataframe (Patient_ID × (gene, site, peptide, ENSG) multiindex) + `proteomics` [bcm] for the
phospho-vs-total comparison. Same package + cohort map as the Q5 tumor arm.

ROUTES (master-sequencing Part 3): Presence (A, protein/pathway-level support) + Mechanism (D, is the
signaling pathway active). Biology axis; no modality-gate facet. For kinases/signaling targets this is
the sharpest presence signal (phospho-activity > total abundance).

Modules:
    read — read_phospho_pathway_activity(target, indication): the phospho-activity summary + class.
"""

from __future__ import annotations

from .read import classify_phospho_activity, read_phospho_pathway_activity

METHOD_VERSION = "0.1.0"

__all__ = ["read_phospho_pathway_activity", "classify_phospho_activity", "METHOD_VERSION"]
