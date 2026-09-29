"""depmap_prism_crispr_concordance — thin lookup card (E7) for chemical-genetic
triangulated target engagement.

Reads one gene row from the frozen derived parquet
`s3://onc-compbio/data-catalog/derived/depmap-prism-activity-v4/prism_activity_per_gene.parquet`
via pyarrow predicate pushdown. SHARES the parquet with E6 (PRISM compound
activity); this card exposes the concordance-specific fields:
  - per_compound_concordance: list<struct> — Spearman(PRISM-activity, CRISPR-Chronos)
    AND Spearman(PRISM-activity, RNAi-DEMETER2) per annotated compound
  - crispr_prism_concordance_class: rollup vocabulary
  - dual_responders: cell lines dual-validated as CRISPR-dependent AND
    compound-responsive (natural biomarker-cohort intersection)

Answers the target-evaluation question: "Do the same cell lines that need the
gene by CRISPR-KO AND RNAi-KD ALSO die when hit by compounds annotated as
targeting it? If both genetic assays concord with the compound's kill pattern,
that's cross-modality cross-perturbation triangulated evidence for on-target
engagement."

Public API for the live-reader dispatcher:
    read_prism_crispr_concordance(target, indication=None, release_pin=...) -> dict
"""

__version__ = "0.1.0"

from .read import read_prism_crispr_concordance

__all__ = ["read_prism_crispr_concordance"]
