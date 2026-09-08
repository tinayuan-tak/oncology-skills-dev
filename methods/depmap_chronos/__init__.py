"""depmap_chronos — DepMap CRISPR Chronos gene-effect analysis methods.

Reads the DepMap Consortium release's CRISPRGeneEffect.csv (Chronos-corrected
gene-effect matrix) and Model.csv (cell-line lineage metadata), and computes
lineage-selectivity statistics for a target gene.

This is a deterministic analytical method per the framework's layer discipline:
no orchestration, no interpretation, no synthesis — just compute. Consumed by
skills (compose-dashboard) and any other client that needs Chronos selectivity.
"""

__version__ = "0.1.0"

from .read import (
    INDICATION_TO_DEPMAP_LINEAGE,
    build_dependency_panorama,
    read_lineage_selectivity,
    read_stratified_dependency,
)

__all__ = [
    "read_lineage_selectivity",
    "INDICATION_TO_DEPMAP_LINEAGE",
    # Subgroup-panorama surface (descriptive): re-exported so the skills
    # dispatcher can reach the builder via _import_method("depmap_chronos").
    "read_stratified_dependency",
    "build_dependency_panorama",
]
