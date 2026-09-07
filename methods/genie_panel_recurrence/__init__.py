"""genie_panel_recurrence — panel-coverage-correct GENIE mutation recurrence.

The GENIE (higher-N) sibling of gdc_somatic_hotspot's driver-recurrence percentile. GENIE has
~35x the TCGA-MC3 sample count for the framework indications, but it is TARGETED PANEL
sequencing — so per-gene frequency MUST use the panel-coverage denominator (samples whose panel
covers the gene), never the raw sample count. This module fuses the GENIE per-sample MAF
(genie-registry-per-sample-maf-v1) with the genie_panel_coverage primitive to produce
coverage-correct per-(indication, gene) frequency + an all-covered-gene recurrence percentile.

Emits, per (indication, gene): n_covered, n_mutated, genie_mutation_frequency (mutated/covered),
genie_driver_recurrence_percentile + _class (rank among covered genes in-indication), and a
coverage_gap flag (n_covered==0 → the gene is on NO panel this cohort was sequenced with →
data_unavailable, NOT frequency 0). Kept a DISTINCT display facet from MC3's driver_recurrence_*
so the whole-exome-breadth (MC3) and higher-N-panel (GENIE) comparators coexist.

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import (  # noqa: E402,F401
    genie_recurrence_for_gene,
    build_genie_recurrence_table,
)
