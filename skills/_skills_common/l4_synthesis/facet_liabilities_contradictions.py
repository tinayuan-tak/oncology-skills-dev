"""C0c facet builder — liabilities AND contradictions (kept DISTINCT). BUILT (#2006).

Builds two SEPARATE products (docs §"The six core L4 products" #3), read straight off the ALREADY-computed
L3d domain story chapters — no new measurement, no LLM authorship, deterministic, verdict-inert:

  * ``liabilities`` — adverse properties that count against the target. Sourced from a domain story's own
    ``caveats`` list (each ``{aspect, claim_id, caveat}`` the L3d template already surfaces, e.g. tumor
    presence's "MS-protein abundance ranks BELOW RNA"). Each liability cites the ONE claim ref it came
    from.
  * ``contradictions`` — evidence RELATIONSHIPS worth understanding, a ``{between:[claim_ref, claim_ref],
    note}`` — NOT a low score, NOT folded into liabilities. A domain story's chapters are emitted in a
    fixed canonical order with the CENTRAL cross-source node first (see ``presence_l3d_story._ASPECTS``);
    every ``concordance_class`` naming convention in the template ends in ``..._concordant`` for agreement
    and something else (a directional split, e.g. ``rna_high_protein_low``, or an outright
    ``..._discordant``) when two independently-resolvable claims pull apart. When the central node reads
    agreement but a peripheral chapter's class does NOT, that pair IS a contradiction: the central claim
    and the peripheral claim disagree on direction, not merely a lower score on one of them. This is the
    ONLY classification rule this module applies — it repackages a naming convention the template already
    emits, it invents no new comparison.

Keeping the two DISTINCT is the load-bearing rule (docs + issue #2006): a liability is a one-sided adverse
read; a contradiction is a two-claim tension. A single chapter with a caveat can ALSO participate in a
contradiction (e.g. tumor-presence's abundance chapter is both, in the EPCAM flagship) — that is not
conflation, it is the same underlying evidence read from its two distinct, independently-emitted facets.

Absence discipline: when NO domain resolves an L3d story at all (``ctx.l3d_domains`` empty — nothing
assessed), this returns None (facet omitted, byte-stable) — "missing != negative", never fabricated. When
at least one domain DOES resolve but neither a caveat nor a directional split is found, the facet still
emits with both lists empty: "checked the assessed domain(s), found nothing adverse or discordant" is an
honest, non-fabricated statement in its own right, distinct from "did not check."

Uniform facet-builder contract: ``build(ctx) -> Optional[dict]`` returning a facet-result dict (with
``statements`` each citing resolvable claim refs) or None. See schema.py / assembler.FACET_BUILDERS.
"""

from __future__ import annotations

from typing import Mapping, Optional

from _skills_common.l4_synthesis import schema as S
from _skills_common.l4_synthesis.context import L4Context

BUILT = True


def _vector_for(chapters: list, claim_id: str) -> Optional[str]:
    """The claim vector a chapter's claim_id is ``reconstructable_from`` (None if not found)."""
    for ch in chapters:
        if isinstance(ch, Mapping) and ch.get("claim_id") == claim_id:
            v = ch.get("reconstructable_from")
            return v if isinstance(v, str) else None
    return None


def _liabilities_for_domain(domain: str, story: Mapping) -> list:
    """One liability per caveat the domain's L3d story already surfaces, each citing its own claim ref."""
    chapters = story.get("chapters") if isinstance(story.get("chapters"), list) else []
    out: list = []
    for cv in story.get("caveats") or []:
        if not isinstance(cv, Mapping):
            continue
        claim_id = cv.get("claim_id")
        note = cv.get("caveat")
        if not isinstance(claim_id, str) or not claim_id or not isinstance(note, str) or not note:
            continue  # no claim to cite / nothing to say -> never fabricate a liability
        ref = S.claim_ref(claim_id, vector=_vector_for(chapters, claim_id), domain=domain)
        out.append({"domain": domain, "aspect": cv.get("aspect"), "liability": note, "claim_ids": [ref]})
    return out


def _contradictions_for_domain(domain: str, story: Mapping) -> list:
    """Central-vs-peripheral directional splits within one domain's L3d story (see module docstring for
    the classification rule). Returns [] (never fabricates) when the central node itself is unresolved,
    or when every peripheral chapter reads concordant with it."""
    chapters = story.get("chapters") if isinstance(story.get("chapters"), list) else []
    if len(chapters) < 2:
        return []
    central = chapters[0]
    central_cls = central.get("concordance_class") if isinstance(central, Mapping) else None
    central_claim_id = central.get("claim_id") if isinstance(central, Mapping) else None
    if not isinstance(central_cls, str) or not central_cls.endswith("_concordant") or not central_claim_id:
        return []  # central reads discordant/unresolved -> that tension belongs to the thesis coherence,
        # not this pairwise rule; never guess a "between" pair off an unresolved central node.
    central_ref = S.claim_ref(central_claim_id, vector=central.get("reconstructable_from"), domain=domain)
    out: list = []
    for ch in chapters[1:]:
        if not isinstance(ch, Mapping):
            continue
        cls = ch.get("concordance_class")
        claim_id = ch.get("claim_id")
        if not isinstance(cls, str) or not claim_id or cls.endswith("_concordant"):
            continue  # peripheral chapter agrees with (or carries no) concordance class -> no split
        ref = S.claim_ref(claim_id, vector=ch.get("reconstructable_from"), domain=domain)
        note = (
            f"within {domain}: {central.get('aspect')} reads '{central_cls}' (cross-source agreement) "
            f"while {ch.get('aspect')} reads '{cls}' — a directional split between two "
            "independently-resolvable claims, not a negation of the central read."
        )
        out.append({"between": [central_ref, ref], "note": note})
    return out


def build(ctx: L4Context) -> Optional[dict]:
    if not ctx.l3d_domains:
        return None  # nothing assessed -> nothing to check -> omitted (byte-stable), never fabricated

    liabilities: list = []
    contradictions: list = []
    statements: list = []
    for domain in ctx.assessed_domains:
        story = ctx.l3d_domains.get(domain)
        if not isinstance(story, Mapping):
            continue
        for lia in _liabilities_for_domain(domain, story):
            liabilities.append(lia)
            statements.append(
                S.statement(f"liability [{domain}/{lia.get('aspect')}]: {lia['liability']}", lia["claim_ids"])
            )
        for con in _contradictions_for_domain(domain, story):
            contradictions.append(con)
            statements.append(S.statement(f"contradiction [{domain}]: {con['note']}", con["between"]))

    return {
        "facet": S.FACET_LIABILITIES_CONTRADICTIONS,
        "layer": S.L4_LAYER,
        "built_by": "C0c #2006",
        "liabilities": liabilities,
        "contradictions": contradictions,
        "statements": statements,
        "integration_method": S.INTEGRATION_METHOD,
        "_disclaimer": (
            "L4 liabilities-vs-contradictions (C0c #2006) — DETERMINISTIC facet assembly over the "
            "assessed L3d stories' own caveats + concordance-class naming convention, verdict-INERT "
            "(reads no verdict, feeds no rule/veto/resolver, moves no emitted field), no new measurement, "
            "no LLM authorship. `liabilities` (adverse claims) and `contradictions` (two-claim evidence "
            "relationships) are kept strictly distinct products; either list may be honestly empty. Every "
            "statement drills back to the cited L2/L3 claim IDs."
        ),
    }
