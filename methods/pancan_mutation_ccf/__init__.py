"""pancan_mutation_ccf — per-(gene, indication) mutation CLONALITY / truncality from TCGA.

Corrects each somatic mutation's VAF (TCGA-MC3) for tumor purity (PanCanAtlas ABSOLUTE per-sample
table) to a cancer-cell fraction (ccf), then aggregates per (gene, indication): what fraction of
mutant tumors carry the gene's alteration CLONALLY (truncally) vs subclonally. The durability axis
the framework lacked — a subclonal driver relapses; a truncal driver is a more durable target.

Invariant: ccf ordering reproduces known clonal architecture (truncal drivers rank above
subclonal-prone genes). A diploid approximation (local CN=2, multiplicity=1) suffices for the
clonal/subclonal CLASSIFICATION; local-CN + multiplicity refinement is not applied, so
evidence_tier is emitted as inferred_diploid.
"""

# Re-export the card read-entrypoint at package level so generic-dispatch resolution
# (compose-dashboard test_generic_dispatch_migrated: getattr(import_module(module), entrypoint))
# resolves `pancan_mutation_ccf.read_clonality` — the target-clonality card's declared method call.
# Mirrors the sibling convention (e.g. gdc_somatic_hotspot re-exports read_hotspot_summary).
from .read import read_clonality

__all__ = ["read_clonality"]
