"""domain_modality_relevance — per-target domain→MODALITY implication.

Turns the EXISTING domain-architecture inventory (uniprot_protein_features / protein-domains-class:
protein_class + domain_names + InterPro hits) into an interpretive signal: does a target's
domain FUNCTION favor a catalytic-site inhibitor, or REMOVAL (degrader /
molecular glue) because the therapeutic function is scaffolding / non-catalytic?

Fuses a CURATED override (target-contracts/vocabularies/domain_modality_targets.yaml — the
kinase-independent / scaffolding biology the data can't infer, e.g. RIPK1) with a CLASS-DRIVEN
heuristic over protein_class + domain architecture. Emits modality_implication_class
{inhibitor_sufficient / removal_favored / removal_required_scaffolding / context_dependent /
data_unavailable}. Additive / verdict-inert DISPLAY facet for the modality skills.

METHOD_VERSION 0.1.0.
"""
from __future__ import annotations

METHOD_VERSION = "0.1.0"

from .read import domain_modality_for_gene  # noqa: E402,F401
