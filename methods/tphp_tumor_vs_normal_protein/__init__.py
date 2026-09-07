"""tphp_tumor_vs_normal_protein — TPHP tumor-vs-adjacent-normal PROTEIN DEG reader.

Consumer: the verdict-INERT `tumor-vs-normal-protein-abundance-tphp` corroboration card in the
tumor-selectivity skill — a protein-layer RNA→PROTEIN tumor-vs-normal corroboration facet PARALLEL to
`tumor-protein-abundance-cptac`, over the TPHP body+cancer DIA-MS proteome (Xu et al., Nature 2026;
open PRIDE PXD063370). Reads the derived per-cohort product `tphp-tumor-vs-normal-protein-per-cohort-v1`
(gene_symbol-sorted; per-gene pushdown), emitting CPTAC-ALIGNED tumor-vs-normal protein fields.

DISTINCT from methods/tphp_normal_protein (the NORMAL-tissue protein baseline, sample_context=normal,
verdict-BEARING). This reader is the TUMOR-vs-normal CONTRAST (sample_context=tumor), verdict-INERT.

Companion: data-catalog:manifests/derived/tphp-tumor-vs-normal-protein-per-cohort-v1.yaml
"""

METHOD_VERSION = "0.1.0"

# Re-export the public API so dispatchers using __import__(...) find read_target_summary at package
# level (the generic dispatcher imports the PACKAGE, then getattr's the entrypoint — mirrors
# tphp_normal_protein / cptac_protein_deg / collectri_tf_regulon).
from .read import read_target_summary  # noqa: F401,E402
from .read import read_all_cohorts  # noqa: F401,E402
