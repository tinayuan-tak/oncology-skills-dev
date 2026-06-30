"""depmap_expression_distribution — pan-cancer expression distribution analysis.

Consumes DepMap 26Q1 OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv + Model.csv,
emits the expression-distribution card output: panel-wide log2(TPM+1) stats, per-
lineage breakdown, descriptive expression_class.

Public API for live-reader dispatcher:
    read_expression_distribution(target, indication=None) -> dict
"""

__version__ = "0.1.0"

from .read import read_expression_distribution

__all__ = ["read_expression_distribution"]
