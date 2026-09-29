"""impc_mouse_ko_phenotype — IMPC-DIRECT mouse-KO normal-physiology safety (corroboration leg).

The verdict-facing mouse-KO leg reads OT-packaged MGI (opentargets_mouse_phenotype). This leg reads
the IMPC-direct rollup (impc-ko-phenotype-per-gene-v1) and re-derives ko_phenotype_class through the
SAME shared classifier, adding the IMPC preweaning-viability + organ-system signal as corroboration
at finer developmental resolution. Coverage is PARTIAL (IMPC ~9k genes); absence = coverage gap.

METHOD_VERSION 0.1.0.
"""

from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import read_impc_mouse_ko_phenotype  # noqa: E402,F401
