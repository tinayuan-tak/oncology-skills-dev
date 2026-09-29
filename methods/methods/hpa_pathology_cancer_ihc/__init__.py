"""hpa_pathology_cancer_ihc — HPA antibody IHC protein-presence-in-tumor reader.

Reads hpa-pathology-cancer-ihc-per-gene-v1 (per gene x HPA cancer type: staining counts +
fraction_detected + protein_presence_class). The MS-INDEPENDENT protein-presence-in-tumor leg for
the tumor-presence skill, orthogonal to the CPTAC/Gygi mass-spec cards and available where CPTAC is
data_unavailable. Maps the caller's OncoTree indication -> HPA's 20 broad cancer types (coarser than
OncoTree; documented granularity loss).
"""

from .read import METHOD_VERSION, read_target_summary  # noqa: F401
