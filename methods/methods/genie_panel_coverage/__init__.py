"""genie_panel_coverage — GENIE panel-coverage primitive.

GENIE is targeted-panel sequencing: its ~271k samples are assayed on one of 166
gene panels with heterogeneous gene coverage. A sample with no mutation row for
gene G could be (a) G wild-type, or (b) sequenced on a panel that does NOT cover
G. Counting (b) in a mutation-frequency denominator conflates "not mutated" with
"not sequenced" — the exact artifact the co-occurrence card's panel-intersect
guard was built to avoid.

This module is the SHARED coverage primitive that makes GENIE mutation frequency
honest: `covered(sample, gene) = gene ∈ panel_genes[panel_of[sample]]`. The
denominator for gene G over a sample set S is `|{s ∈ S : covered(s, G)}|`, NOT `|S|`.

Two resident tables (both small — 166 panels, 271k samples):
  - sample→panel   : data_gene_matrix.txt `mutations` column (the panel that assayed SNVs)
  - panel→gene-set : the 166 data_gene_panel_<ID>.txt files (reuses the parse helpers
                     from cooccurrence_fisher_pancohort/steps/01_panel_intersect.py)

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import (  # noqa: E402,F401
    covered,
    load_panel_gene_sets,
    load_sample_panel_map,
    load_sv_sample_panel_map,
    n_covered_samples,
    panel_coverage_denominator,
)
