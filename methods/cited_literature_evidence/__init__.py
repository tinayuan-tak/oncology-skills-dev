"""cited_literature_evidence — verdict-inert gene×indication cited-literature card (composing reader).

Composes the OT europepmc co-occurrence evidence + PubTator3 typed-relation direction readers into one
verdict-inert card. See read.py for the implementation.
"""

# Re-export the card read-entrypoint (+ the pure assembler / live composer the skills-side shim reuses)
# at package level so the skills generic-dispatch resolution
# (getattr(import_module("methods.cited_literature_evidence"), entrypoint)) resolves
# `cited_literature_evidence.read_cited_literature_evidence` — the cited-literature-evidence card's
# declared method call. (Convention: a card entrypoint that lives only in a submodule breaks the skills
# test_generic_routed_card_resolves_to_real_callable guard; mirrors hcmi_model_availability.)
from .read import (
    read_cited_literature_evidence,
    build_cited_evidence_card,
    cited_evidence,
)

__all__ = ["read_cited_literature_evidence", "build_cited_evidence_card", "cited_evidence"]
