"""civic_variant_interpretation — per-variant functional interpretation from CIViC.

THE per-variant-interpretation gap the framework has carried: alteration-role calls
GoF/LoF/passenger at the GENE level (OncoKB geneType × IntOGen compendium), so "a
passenger mutation in a driver gene still reads as the gene's role", and recurrence
(mutation-hotspot-frequency) is FREQUENCY not FUNCTION. This method adds the missing
per-(gene, variant) axis by consuming CIViC (Clinical Interpretation of Variants in
Cancer, Griffith 2017) — curated, CC0, ingested-but-until-now-UNCONSUMED.

Two orthogonal per-variant axes, both aggregated to the gene grain (the target-eval unit):
  - variant_oncogenicity_class  {oncogenic / likely_oncogenic / vus / benign / data_unavailable}
      from AssertionSummaries AMP/ASCO/CAP significance (graded, authoritative) →
      ClinicalEvidence Oncogenic evidence-direction → Functional GoF/LoF/Dominant-Negative.
  - variant_resistance_class    {known_resistance / reduced_sensitivity / no_resistance_annotation}
      from ClinicalEvidence Predictive evidence with significance Resistance/Reduced Sensitivity,
      therapy-linked (EGFR T790M→osimertinib, BCR::ABL1→imatinib, …).

SCOPE BOUNDARY (documented, not a bug): only SINGLE-VARIANT molecular profiles are
attributed to a gene (VariantSummaries.single_variant_molecular_profile_id). Complex/
compound/fusion profiles ("BRAF V600E AND NF1 Loss", "BCR::ABL1 Fusion") are combination
biology — the differentiation-landscape co-mutation axis's concern, not a single gene's —
and are EXCLUDED to keep every per-variant attribution unambiguous.

Additive / verdict-inert DISPLAY facet — fires NO resolver rung.
METHOD_VERSION 0.1.0.

DEFERRED fast-follow (see caveat): the IntOGen 2D/3D driver-cluster residues
(Compendium_Cancer_Genes.tsv, CC0, in-hand) as a recall-extension leg for variants CIViC
has not curated — a variant at/near a HOTMAPS-significant residue is a positional driver signal.
"""
from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import (  # noqa: E402,F401
    civic_interpretation_for_gene,
    build_civic_interpretation_table,
)
