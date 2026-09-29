"""gdc_somatic_hotspot — Somatic-mutation hotspot frequency analysis from GDC pancohort MAFs.

Produces (cli.py) and consumes (read.py) hotspot-frequency aggregates over per-aliquot
GDC ensemble-masked MAF files. The aggregator walks an indication's MAF set, counts
mutated samples per gene + per protein-change hotspot, and emits a Parquet keyed by
(indication, gene_symbol, hotspot, n_samples_mutated, n_samples_total).

Consumers (skills, notebooks, AgenticBoost) query the aggregate via read.py for
specific (gene, indication) pairs. Per the framework's layer-distinction discipline,
this is compute-only — no orchestration logic.
"""

__version__ = "0.1.0"

from .read import (
    build_mutation_frequency_panorama,
    read_hotspot_summary,
    read_stratified_mutation_frequency,
)

__all__ = [
    "read_hotspot_summary",
    # Subgroup-panorama surface (descriptive): re-exported so the skills
    # dispatcher can reach the builder via _import_method("gdc_somatic_hotspot").
    "read_stratified_mutation_frequency",
    "build_mutation_frequency_panorama",
]
