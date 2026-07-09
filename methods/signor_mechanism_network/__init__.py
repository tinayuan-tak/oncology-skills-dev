"""signor_mechanism_network — SIGNOR-tagged signaling mechanism derived from OmniPath.

Extracts the SIGNOR-tagged subset of the OmniPath commercially-cleared interactions
file, classifies each edge under a curated MoA-class ontology, and emits a per-gene
network summary keyed by UniProt-AC. Consumer: the mechanism-and-pharmacology skill
(Phase D) via the signaling-network-mechanism evidence card.

Companion:
    data-catalog:manifests/derived/signor-mechanism-network-per-gene-v1.yaml

Modules:
    moa_ontology  — versioned SIGNOR-mechanism → MoA-class classification table
    cli           — Click CLI: OmniPath interactions.tsv → per-gene network parquet
"""
METHOD_VERSION = "0.1.0"

# Re-export the public API so dispatchers using __import__(...) find
# read_target_summary at package level.
from .read import read_target_summary  # noqa: F401,E402
