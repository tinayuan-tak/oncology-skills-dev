"""structure_features_static — PDB + AlphaFold static-feature extractor.

Joins PDB REST API responses + AlphaFold DB REST responses to a per-UniProt-AC
scalar summary emit consumed by the structure-features-static evidence card.
Emits categorical fields (pocket_adjacency_call, mutation_hotspot_in_druggable_pocket)
that the rules engine consumes, NOT interactive viewers.

Companion:
    data-catalog:manifests/derived/pdb-alphafold-structure-features-per-uniprot-v1.yaml

Consumer: structure-features-static evidence card (Phase F) via tractability-and-modality.
"""

METHOD_VERSION = "0.2.0"

from .read import read_target_summary  # noqa: F401,E402
