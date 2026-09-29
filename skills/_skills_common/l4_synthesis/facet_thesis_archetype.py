"""C0a facet builder — thesis + archetype (#1995). BUILT end-to-end (proves the skeleton).

The thesis+archetype facet is the L4a core: the most defensible integrated read of the target, and the
KIND of opportunity it is. It is a DETERMINISTIC projection over the assessed domains' L3d stories:

  * thesis.state  — a deterministic function of the domain L3d coherence (NOT a verdict; never fed back).
  * thesis.narrative — assembled from the L3d story's OWN deterministic headline prose (NOT re-authored,
    no LLM).
  * thesis.supported_by — the L2b claim refs the L3d story already cites (each drills back into a claim
    vector).
  * archetype — a definitive archetype is a CROSS-DOMAIN classification. When the domains that would
    resolve the opportunity KIND (dependency / surface-modality / on-target-safety) are NOT_ASSESSED, we
    emit ``ARCHETYPE_UNDETERMINED`` + the honest basis + what would promote it — never a guess laundered
    from a single domain.

Every emitted statement cites resolvable claim refs; if the assessed L3d carries nothing citable, the
facet is omitted (return None) rather than emitting an untraceable statement.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.l4_synthesis import schema as S
from _skills_common.l4_synthesis.context import L4Context

BUILT = True

# The DEFINITIVE archetype hinges on these cross-domain reads; while they are NOT_ASSESSED the honest
# archetype is UNDETERMINED. (Extended by a later child once their L3d verticals export.)
_ARCHETYPE_REQUIRED_DOMAINS = ("dependency", "surface_modality", "on_target_safety")

# Deterministic map: an L3d within-domain coherence class -> an L4a thesis state. Kept in this module so
# a later child that reconciles MULTIPLE domains' coherence extends only here (collision-free).
_COHERENCE_TO_STATE = {
    "cross_source_corroborated": "supported",
    "cross_source_corroborated_boundary_sensitive": "supported_with_caveats",
    "cross_source_discordant": "contested",
    "single_source_read": "limited_evidence",
    "peripheral_islands_only": "partial",
    "central_node_unclassified": "partial",
    "no_resolved_island": "insufficient",
}


def _supported_by(stories: list) -> list:
    """The claim refs every resolved L3d story cites (its ``provenance.claim_ids`` -> {claim_id, vector}),
    in stable story-then-chapter order. These are the downward-reconstruction handles for the thesis."""
    refs: list = []
    for story in stories:
        prov = story.get("provenance") if isinstance(story, dict) else None
        for pc in (prov.get("claim_ids") if isinstance(prov, dict) else None) or []:
            if isinstance(pc, dict) and pc.get("claim_id"):
                refs.append(S.claim_ref(pc["claim_id"], vector=pc.get("vector")))
    return refs


def build(ctx: L4Context) -> Optional[dict]:
    if not ctx.l3d_domains:
        return None  # no domain story resolved -> no thesis -> facet omitted (byte-stable)

    domains = ctx.assessed_domains
    stories = [ctx.l3d_domains[d] for d in domains]
    supported_by = _supported_by(stories)
    if not supported_by:
        # A resolved story that cites no L2 claim gives us nothing traceable to stand a thesis on.
        return None

    # Thesis state from the PRIMARY domain's coherence. Today only tumor_presence is exported to L3d; the
    # multi-domain reconciliation (when other verticals export) is a later child that extends this block.
    primary = ctx.l3d_domains.get("tumor_presence") or stories[0]
    coherence = primary.get("coherence")
    state = _COHERENCE_TO_STATE.get(coherence, "partial")

    lead = (primary.get("headline") or "").strip()
    domain_names = ", ".join(domains)
    narrative = f"Integrated across the assessed domain(s) [{domain_names}], the target read is '{state}'." + (
        f" {lead}" if lead else ""
    )

    thesis = {
        "state": state,
        "narrative": narrative,
        "supported_by": supported_by,
        "assessed_domains": domains,
        "primary_domain": "tumor_presence" if "tumor_presence" in ctx.l3d_domains else domains[0],
        "primary_coherence": coherence,
    }

    # Archetype — honest cross-domain classification (never guessed from one domain).
    missing = [d for d in _ARCHETYPE_REQUIRED_DOMAINS if d not in ctx.l3d_domains]
    archetype = S.ARCHETYPE_UNDETERMINED
    if missing:
        archetype_basis = (
            "a definitive target archetype is a cross-domain classification; only "
            f"[{domain_names}] is assessed here — the domains that would resolve the opportunity KIND "
            f"({', '.join(_ARCHETYPE_REQUIRED_DOMAINS)}) are NOT_ASSESSED in this envelope, so the "
            "archetype is left UNDETERMINED rather than laundered from a single domain"
        )
        promote_when = list(missing)
    else:
        # All defining domains present — definitive archetype derivation is a later child (C0x); C0a
        # deliberately stops at UNDETERMINED so it never ships an unvalidated cross-domain classifier.
        archetype_basis = (
            "all defining domains are assessed; definitive archetype derivation is a later child — C0a "
            "leaves the token UNDETERMINED"
        )
        promote_when = []

    statements = [
        S.statement(narrative, supported_by),
        S.statement(f"archetype={archetype}: {archetype_basis}", supported_by),
    ]

    return {
        "facet": S.FACET_THESIS_ARCHETYPE,
        "layer": S.L4_LAYER,
        "built_by": "C0a #1995",
        "thesis": thesis,
        "archetype": archetype,
        "archetype_basis": archetype_basis,
        "archetype_promote_when": promote_when,
        "statements": statements,
        "integration_method": S.INTEGRATION_METHOD,
        "_disclaimer": (
            "L4 thesis+archetype (C0a #1995) — DETERMINISTIC facet assembly over the assessed L3d "
            "stories, verdict-INERT (reads no verdict, feeds no rule/veto/resolver, moves no emitted "
            "field), no new measurement, no LLM authorship. Every statement drills back to the cited "
            "L2/L3 claim IDs."
        ),
    }
