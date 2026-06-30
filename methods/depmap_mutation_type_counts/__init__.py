"""depmap_mutation_type_counts — cell-line mutation-type counts (MAF-based).

Consumes DepMap 26Q1 OmicsSomaticMutations.csv (raw MAF) and emits per-variant-class
mutation counts + landscape-class label for the mutation-type-counts card.

Public API for live-reader dispatcher:
    read_mutation_type_counts(target, indication=None) -> dict
"""

__version__ = "0.1.0"

from .read import read_mutation_type_counts

__all__ = ["read_mutation_type_counts"]
