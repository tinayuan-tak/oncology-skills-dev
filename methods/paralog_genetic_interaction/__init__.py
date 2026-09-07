"""paralog_genetic_interaction — per-target combinatorial-KO genetic-interaction reader."""

from methods.paralog_genetic_interaction.read import (
    combinatorial_dependency_for_gene,
    lineage_breakdown_for_pair,
)

__all__ = ["combinatorial_dependency_for_gene", "lineage_breakdown_for_pair"]
