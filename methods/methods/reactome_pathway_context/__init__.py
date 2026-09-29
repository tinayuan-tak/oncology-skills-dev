"""reactome_pathway_context — Reactome pathway-membership annotation reader.

Consumer: signaling-network-mechanism composed card (Phase D), via the
mechanism-and-pharmacology skill. Enriches SIGNOR + CollecTri edges with
pathway-context annotations (which Reactome pathways does the target
participate in, at what hierarchy level).

Scope (v0.1, Sprint 2 per landscape reviewer's recommendation):
  - Pathway-membership annotation for the profiled target (which pathways
    is it in, at what level, evidence code)
  - Pathway-hierarchy rollup (top-level signaling category)
  - Cross-source enrichment: for each SIGNOR/CollecTri partner, does the
    partner share a pathway with the target?

Deferred (Sprint 2.5 follow-up):
  - Reactome K-S edge extraction from BioPAX (needs paxtoolspy + heavier
    parse); the ~1.5k novel Reactome-curated K-S edges beyond SIGNOR
  - ProteinRoleReaction.txt ingest (needs new data-catalog manifest entry)

Uses Reactome v96 files ALREADY CATALOGUED in reactome-v96 source manifest:
  - UniProt2Reactome_All_Levels.txt (~116MB, protein↔pathway map)
  - ReactomePathways.txt (pathway ID → name)
  - ReactomePathwaysRelation.txt (parent→child hierarchy)

License: Reactome CC0-1.0 (public domain). Cleanest license of any
source in the framework. Cite Milacic et al. 2024 NAR.

Companion: data-catalog:manifests/sources/reactome-v96.yaml
"""

METHOD_VERSION = "0.1.0"

# Re-export the public API so dispatchers using __import__(...) find
# read_target_summary at package level.
from .read import read_target_summary  # noqa: F401,E402
