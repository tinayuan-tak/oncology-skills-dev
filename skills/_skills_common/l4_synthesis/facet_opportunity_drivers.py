"""C0b facet builder — opportunity_drivers (epic #1986, #2005).

Opportunity drivers are the claims that make the target INTERESTING — each driver citing the L2/L3
claim ref(s) it rests on (docs §"The six core L4 products" #2). Built by walking every ASSESSED domain's
L3d chapters and selecting the ones whose OWN ``concordance_class`` is a corroborated positive read (not
flagged discordant, and not carrying a low/absent ``corroboration``) — this is structural over the
common L3d chapter shape (``concordance_class``/``corroboration``/``reads``), not tumor_presence-specific,
so a later domain's L3d export is picked up here with no change.

A chapter that also carries a ``caveat`` is STILL a driver when its own concordance_class is positive —
the caveat is a DISTINCT evidence relationship surfaced by the sibling ``liabilities_contradictions``
facet (C0c #2006); this facet does not suppress a corroborated positive read merely because a caveat also
rides on it. Drivers and liabilities are independent facets over the SAME claims, not mutually exclusive
partitions of them.

Absence path: when no assessed domain resolves any positive chapter, the facet returns None (never a
placeholder or fabricated driver) — "missing != negative".
"""

from __future__ import annotations

from typing import Optional

from _skills_common.l4_synthesis import schema as S
from _skills_common.l4_synthesis.context import L4Context

BUILT = True

_LOW_CORROBORATION = frozenset({"low", "none", "absent"})


def _is_positive_chapter(chapter) -> bool:
    """A chapter counts as an opportunity driver when its OWN concordance_class is not flagged discordant
    and its corroboration is not low/absent/missing. Structural over the shared L3d chapter shape."""
    if not isinstance(chapter, dict):
        return False
    cls = chapter.get("concordance_class")
    if not isinstance(cls, str) or not cls or "discordant" in cls:
        return False
    corroboration = chapter.get("corroboration")
    if not isinstance(corroboration, str) or corroboration in _LOW_CORROBORATION:
        return False
    return True


def _chapter_ref(chapter: dict, domain: str) -> Optional[dict]:
    cid = chapter.get("claim_id")
    if not isinstance(cid, str) or not cid:
        return None
    vector = chapter.get("reconstructable_from")
    return S.claim_ref(cid, vector=vector, domain=domain)


def build(ctx: L4Context) -> Optional[dict]:
    if not ctx.l3d_domains:
        return None  # no domain story resolved -> nothing to synthesize a driver from (byte-stable)

    drivers: list = []
    statements: list = []
    for domain in ctx.assessed_domains:  # stable (sorted) domain order
        story = ctx.l3d_domains.get(domain)
        chapters = story.get("chapters") if isinstance(story, dict) else None
        for chapter in chapters or []:  # stable chapter order (as exported by the L3d story)
            if not _is_positive_chapter(chapter):
                continue
            ref = _chapter_ref(chapter, domain)
            if ref is None:
                continue
            text = (chapter.get("reads") or chapter.get("within_domain_role") or "").strip()
            if not text:
                continue
            drivers.append(
                {
                    "domain": domain,
                    "aspect": chapter.get("aspect"),
                    "concordance_class": chapter.get("concordance_class"),
                    "corroboration": chapter.get("corroboration"),
                    "statement": text,
                    "claim_ids": [ref],
                }
            )
            statements.append(S.statement(text, [ref]))

    if not drivers:
        return None  # nothing corroborated-positive resolved -> no drivers -> facet omitted (byte-stable)

    return {
        "facet": S.FACET_OPPORTUNITY_DRIVERS,
        "layer": S.L4_LAYER,
        "built_by": "C0b #2005",
        "drivers": drivers,
        "statements": statements,
        "integration_method": S.INTEGRATION_METHOD,
        "_disclaimer": (
            "L4 opportunity_drivers (C0b #2005) — DETERMINISTIC facet assembly over the assessed L3d "
            "chapters, verdict-INERT (reads no verdict, feeds no rule/veto/resolver, moves no emitted "
            "field), no new measurement, no LLM authorship. Each driver cites the resolvable L2/L3 claim "
            "ref(s) it rests on; the absence of a corroborated-positive chapter yields NO drivers (never "
            "a fabricated one) rather than an empty placeholder claim."
        ),
    }
