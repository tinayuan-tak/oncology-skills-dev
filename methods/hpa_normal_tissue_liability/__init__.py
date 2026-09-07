"""hpa_normal_tissue_liability — normal-tissue on-target-off-tumor safety method.

Wires the previously-data-blocked normal-tissue-liability card (target-contracts) to
the landed HPA master TSV (hpa-v25-1). Reads the IHC-derived protein-tissue fields
and emits normal_tissue_breadth_class ∈ {broad_normal_expression |
moderate_normal_expression | restricted_normal_expression | not_detected_in_normal |
data_unavailable} + essential-tissue flags. The dominant biologics on-target-off-
tumor safety signal (TROP2 / HER2 / CD44v6-class normal-tissue tox).

Modules:
    cli  — HPA TSV loader + breadth classifier + essential-tissue parser + CLI
    read — read_target_summary: the live-mode dispatcher entry
"""

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: E402,F401
