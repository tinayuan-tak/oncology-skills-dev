"""cptac_protein_deg — CPTAC protein tumor-vs-normal DEG wrapper.

Runs limma-voom-style per-gene tumor-vs-normal protein-expression differential
against CPTAC-PDC mass-spec data (10 cohorts, 1,313 files, 14.27 GB). Emits a
per-(cohort, gene) tumor-vs-normal effect size + q-value + median-log2-abundance.

Companion:
    data-catalog:manifests/derived/cptac-protein-tumor-vs-normal-per-cohort-v1.yaml

Consumer: tumor-protein-abundance-cptac + surface-abundance-density cards (Phase A, F)
via tumor-presence + tractability-and-modality skills.
"""

METHOD_VERSION = "0.1.0"

from .read import read_target_summary  # noqa: F401,E402

# Slice B1: re-export the pan-cancer breadth reader so compose-dashboard's
# _import_method (which imports the PACKAGE, then getattr's the fn) resolves it.
from .read import read_tumor_elevation_breadth  # noqa: F401,E402

# Tier 1.2 (2026-07-23): surface-abundance-density card dispatcher
# (_dispatch_surface_abundance_density) getattr's this off the package.
from .read import read_abundance_density_summary  # noqa: F401,E402
