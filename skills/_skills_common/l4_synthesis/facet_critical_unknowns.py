"""C0d facet builder — critical_unknowns (epic #1986, #2007). BUILT.

critical_unknowns is a FIRST-CLASS L4 product (docs §"The six core L4 products" #5), not an appendix: for
every domain the framework knows how to assess (``schema.KNOWN_DOMAINS``), this facet names whether that
domain's central question is KNOWN, still UNKNOWN, CONTRADICTED across sources, or NOT_ASSESSED in the
current envelope — and flags which of those are DECISION-CRITICAL (the cross-domain-defining ones the
thesis+archetype facet names in ``archetype_promote_when``).

Load-bearing invariant: **absence outranks measurement**. A domain with no resolved L3d story is
NOT_ASSESSED — never silently omitted, never read as reassuring/negative evidence. But the traceability
contract (``assembler.unresolved_refs`` / ``L4TraceabilityError``) still applies: every statement,
INCLUDING a NOT_ASSESSED one, must cite claim refs that resolve into the envelope. An absent domain
cannot cite itself (nothing there to resolve against) — the honest citation for a NOT_ASSESSED entry is
the resolvable evidence of what the envelope DOES carry (the assessed domain(s) it already proves), the
same "cite the resolvable, not the absent" mechanism ``facet_thesis_archetype`` uses to back its
``archetype=undetermined`` statement. When the envelope carries NO resolved L3d domain at all, there is
nothing anywhere to cite — the honest behavior is to omit the facet (return None), never to fabricate a
NOT_ASSESSED list backed by nothing (this mirrors ``facet_thesis_archetype.build``'s own guard and keeps
``test_no_l3d_yields_no_synthesis`` true for critical_unknowns too).

Uniform facet-builder contract: ``build(ctx) -> Optional[dict]``. See schema.py / assembler.FACET_BUILDERS.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.l4_synthesis import schema as S
from _skills_common.l4_synthesis.context import L4Context

BUILT = True

# The domains that resolve the DEFINITIVE archetype (facet_thesis_archetype._ARCHETYPE_REQUIRED_DOMAINS,
# duplicated here as a plain vocabulary constant — deliberately NOT imported, so this module has zero
# coupling to a sibling facet module and stays collision-free / independently testable). While any of
# these is not KNOWN, the opportunity KIND cannot be named — that is what makes its unknown
# decision-critical rather than a low-priority gap.
_ARCHETYPE_DEFINING_DOMAINS = ("dependency", "surface_modality", "on_target_safety")

# Deterministic map: an L3d within-domain coherence class -> a critical-unknown STATUS
# (schema.UNKNOWN_STATUS). An assessed domain that resolved cleanly is KNOWN; one whose sources disagree
# is CONTRADICTED; every other resolved-but-not-clean coherence class means the domain WAS assessed but
# its central question is still UNKNOWN. A domain absent from ``ctx.l3d_domains`` entirely is NOT_ASSESSED
# (handled separately in ``build`` — there is no coherence value to map for it).
_COHERENCE_TO_STATUS = {
    "cross_source_corroborated": "KNOWN",
    "cross_source_corroborated_boundary_sensitive": "KNOWN",
    "cross_source_discordant": "CONTRADICTED",
    "single_source_read": "UNKNOWN",
    "peripheral_islands_only": "UNKNOWN",
    "central_node_unclassified": "UNKNOWN",
    "no_resolved_island": "UNKNOWN",
}


def _story_refs(story) -> list:
    """The claim refs a resolved L3d story already cites (its ``provenance.claim_ids``)."""
    refs: list = []
    prov = story.get("provenance") if isinstance(story, dict) else None
    for pc in (prov.get("claim_ids") if isinstance(prov, dict) else None) or []:
        if isinstance(pc, dict) and pc.get("claim_id"):
            refs.append(S.claim_ref(pc["claim_id"], vector=pc.get("vector")))
    return refs


def build(ctx: L4Context) -> Optional[dict]:
    if not ctx.l3d_domains:
        # Nothing anywhere to cite -- an all-NOT_ASSESSED list backed by no resolvable evidence would be
        # exactly the "launder judgment into a fact" failure the traceability contract forbids. Honest
        # omission, matching facet_thesis_archetype's own guard for the same reason.
        return None

    assessed_names = sorted(ctx.l3d_domains)

    # The resolvable evidence that backs every NOT_ASSESSED entry: we can only assert a domain is absent
    # because we have proven presence elsewhere in the SAME envelope (each assessed domain's own refs,
    # plus a bare domain ref to the assessed domain itself).
    presence_refs: list = []
    for name in assessed_names:
        presence_refs.extend(_story_refs(ctx.l3d_domains[name]))
        presence_refs.append(S.claim_ref(f"l3d::{name}", domain=name))

    unknowns: list = []
    statements: list = []
    for domain in S.KNOWN_DOMAINS:
        defining = domain in _ARCHETYPE_DEFINING_DOMAINS
        if domain in ctx.l3d_domains:
            story = ctx.l3d_domains[domain]
            coherence = story.get("coherence")
            status = _COHERENCE_TO_STATUS.get(coherence, "UNKNOWN")
            refs = _story_refs(story) or [S.claim_ref(f"l3d::{domain}", domain=domain)]
            current_status = coherence or "assessed_without_coherence"
        else:
            status = "NOT_ASSESSED"
            refs = list(presence_refs)
            current_status = "no L3d story exported for this domain in the current envelope"

        decision_critical = defining and status != "KNOWN"
        unknown = {
            "question": (
                f"Is the {domain.replace('_', ' ')} evidence for "
                f"{ctx.target or 'the target'} in {ctx.indication or 'this indication'} resolved?"
            ),
            "status": status,
            "affects": ["archetype"] if defining else [],
            "decision_importance": "high" if defining else "supporting",
            "decision_critical": decision_critical,
            "current_status": current_status,
            "claim_ids": refs,
        }
        unknowns.append(unknown)
        statements.append(S.statement(f"{domain}: {status} ({current_status})", refs))

    return {
        "facet": S.FACET_CRITICAL_UNKNOWNS,
        "layer": S.L4_LAYER,
        "built_by": "C0d #2007",
        "critical_unknowns": unknowns,
        "statements": statements,
        "integration_method": S.INTEGRATION_METHOD,
        "_disclaimer": (
            "L4 critical_unknowns (C0d #2007) — DETERMINISTIC facet assembly over the assessed/unassessed "
            "domain set, verdict-INERT (reads no verdict, feeds no rule/veto/resolver, moves no emitted "
            "field), no new measurement, no LLM authorship. Absence outranks measurement: an unassessed "
            "domain is NOT_ASSESSED, never guessed and never read as reassuring. Every statement drills "
            "back to the cited L2/L3 claim IDs."
        ),
    }
