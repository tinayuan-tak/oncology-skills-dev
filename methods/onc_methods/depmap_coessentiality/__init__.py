"""depmap_coessentiality — genome-wide co-essentiality (co-dependency) network.

Pre-computes the pairwise Pearson correlation across all DepMap CRISPR gene-effect
profiles (Chronos-corrected), retains the top-K strongest co-essential partners per
gene, and stores them as a gene-sorted long-format parquet for fast per-gene lookup.

Two genes are co-essential when their CRISPR knockout profiles are correlated across
cell lines: both are essential in the same subset of lines. Positive r = co-essential
(shared pathway/complex membership); negative r = anti-correlated dependency (buffering
or synthetic-lethal candidate direction). This substrate feeds:
  - M8 (paralog co-essentiality context)
  - M9 (paralog-SL scoring)
  - M13 (on-target mechanism validation)
  - Mechanism gate (protein-complex / pathway coherence check)

Compute: standardize(Z) → Z.T @ Z / (n_cells-1) — a single dense BLAS matmul
producing the full 18,531² Pearson matrix in ~4.5 s. NaN imputed to gene mean
(post-centering). See compute.py for the algorithm; cli.py for the emit runner.

METHOD_VERSION: "0.1.0"
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import read_coessential_module_summary, read_coessential_partners  # noqa: F401
