"""sanger_drug_synergy — per-target CHEMICAL drug×drug synergy reader (Sanger 2022).

Reads sanger-drug-combination-synergy-per-target-v1 via target_gene pushdown: the partner drugs (+ their
targets) a target synergizes with, ranked, with a target-level synergy_opportunity_class. The first
chemical-synergy input to combination-and-vulnerability's new SYNERGY relational axis. Bliss-excess,
3-tissue, cell-line — MoA/hypothesis-generating (NOT a dependency).
"""

from .read import read_target_summary, synergy_partners_for_gene, METHOD_VERSION  # noqa: F401
