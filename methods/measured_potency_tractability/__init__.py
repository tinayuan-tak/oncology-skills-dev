"""measured_potency_tractability — per-target MEASURED small-molecule potency (ChEMBL + BindingDB fusion).

Tractability review T3.1: wires the previously-inert chembl-bioactivity + bindingdb-affinity products
into a measured_bioactivity_class — the missing "is there a POTENT (<=1 uM) chemical start point?"
dimension, orthogonal to PRISM cell-line killing, predicted pockets, and the presence-only DGIdb catalogue.
"""
from .read import measured_potency_for_gene, classify_measured_bioactivity

__all__ = ["measured_potency_for_gene", "classify_measured_bioactivity"]
