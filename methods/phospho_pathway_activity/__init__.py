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
  - not_phosphoprotein        → the gene has no phosphosites in the CPTAC panel (not a phosphoprotein,
                                or not captured) — an honest "this axis doesn't apply".
  - data_unavailable          → no CPTAC cohort for the indication, or read failure.

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

from .read import read_phospho_pathway_activity, classify_phospho_activity

METHOD_VERSION = "0.1.0"

__all__ = ["read_phospho_pathway_activity", "classify_phospho_activity", "METHOD_VERSION"]
