"""mechanism_composed — composed Phase-D mechanism-network reader.

Unions 3 provenance-explicit source methods into a single per-target
mechanism-network summary consumed by the signaling-network-mechanism
evidence card (Phase D), via mechanism-and-pharmacology skill.

Sources composed (per PSP-replacement research 2026-07-10):
  - signor_mechanism_network: causal signaling edges (CC-BY-SA 4.0)
  - collectri_tf_regulon: signed TF-target regulons (mostly CC-BY, per-row)
  - reactome_pathway_context: pathway-membership annotations (CC0-1.0)

Deferred (Sprint 3+):
  - Johnson 2023 + Yaron-Barir 2024 kinome atlases (~89k kinase-motif
    predictions; separate "kinome-atlas prediction" card per reviewer)
  - OmniPath enzsub row-filtered (adds ProtMapper text-mining +
    dbPTM; requires legal sign-off on row-filter approach)

Composition discipline:
  - Union edges across sources on (partner_symbol, direction) key
  - Each emitted edge carries `sources: List[str]` — the source
    manifest_ids that supported the edge. Governance-critical column.
  - When ≥2 sources agree on an edge, it's high-confidence (join both
    provenance strings).
  - Reactome pathway-context annotation layers ONTO the edge union
    (not per-edge; per-target).
  - MoA ontology + version stamped from moa_ontology.py.
"""

METHOD_VERSION = "0.1.0"

# Re-export the public API so dispatchers using __import__("methods.X",
# fromlist=["*"]) find read_target_summary at package level. Same pattern
# used across the framework's other methods.
from .read import read_target_summary  # noqa: F401,E402
