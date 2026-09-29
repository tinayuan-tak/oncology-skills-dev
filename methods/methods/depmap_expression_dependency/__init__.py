"""depmap_expression_dependency — Card 4: expression-vs-Chronos correlation.

Analyzes whether a target gene's mRNA expression correlates with its own Chronos
dependency across DepMap cell lines. A strong negative correlation supports the
'expression as biomarker' hypothesis (high-expressers are more dependent).

Public API for the live-reader dispatcher:
    read_expression_dependency(target, indication=None) -> dict
"""

__version__ = "0.1.0"

from .read import read_expression_dependency

__all__ = ["read_expression_dependency"]
