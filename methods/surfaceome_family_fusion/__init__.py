"""surfaceome_family_fusion — surface-protein family taxonomy fusion.

Fuses four upstream sources into a single per-UniProt-AC surfaceome classification:
    SURFY 2018 (Bausch-Fluck): ML-scored surface residency + confidence
    HPA v25.1: subcellular_main_location + protein_class taxonomy
    UniProt Enzyme Nomenclature: EC-number-derived enzyme family
    IUPHAR/BPS Guide to PHARMACOLOGY: receptor / channel / transporter classes

The fusion is a coverage-aware rollup: each row records which source contributed
which fact + an overall `surface_protein_family` categorical that consumers of
the surfaceome-family-classification card can rely on. Robust to single-source
coverage gaps.

Companion:
    data-catalog:manifests/derived/surfaceome-family-classification-per-uniprot-v1.yaml

Consumer: surfaceome-family-classification evidence card (Phase F) via the
tractability-and-modality skill.
"""
METHOD_VERSION = "0.1.0"
