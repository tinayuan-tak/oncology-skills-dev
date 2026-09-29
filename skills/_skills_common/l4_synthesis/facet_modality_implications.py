"""C0e facet builder — modality_implications (epic #1986, #2008). BUILT.

Per-modality (adc / tce / small_molecule) ``{opportunity, liability, critical_unknown}`` triples — deliberately
NOT a scalar ``adc_fit = moderate`` (docs §"The six core L4 products" #4). Frame on the way in, view on the
way out: this REORGANIZES the one synthesis object by modality; it derives no new measurement and authors
no new judgment.

Two substrates are reused, never re-derived:

  * the assessed L3d domain stories already gathered on ``ctx`` (their own ``chapters``/``caveats`` — the
    same structural technique ``facet_opportunity_drivers`` / ``facet_liabilities_contradictions`` apply),
    filtered to the domains each modality actually depends on (``_MODALITY_RELEVANT_DOMAINS``, a fixed,
    documented relevance map — surface-antigen modalities [ADC/TCE] depend on tumor_presence/surface_
    modality/tumor_selectivity/on_target_safety; small_molecule depends on dependency/genomic_alteration/
    tractability/on_target_safety);
  * the SK#1844 per-modality ADC/TCE decision FRAMES (``evidence_frame.adc_modality_fit_frame`` /
    ``tce_modality_fit_frame``) evaluated read-only over the decision's own headline — the SAME typed
    frames the surface-modality-fit skill's question table already renders
    (``surface_modality_question_table._surface_modality_frame_signal``). Calling them here is READ-ONLY
    reuse: no new measurement, no edit to ``evidence_frame.py``. When the envelope does not carry the
    composite class tokens those frames consume (true of every current flagship — surface_modality is not
    yet L3d-exported), the frame honestly resolves nothing (``DECISION_QUESTION``, empty
    ``resolved_inputs``) and contributes NO extra statement beyond the domain-absence critical_unknown
    already emitted — never fabricated content from an unresolved frame. This is a forward hook: once a
    future envelope carries the composite tokens, the frame's own resolved read folds in automatically,
    still citing only refs already resolvable in THIS envelope (the frame object itself is never cited —
    it is not a member of ``ctx.l3f_frames`` in any current flagship).

Load-bearing invariants shared with every L4 facet: absence outranks measurement (an unassessed
modality-relevant domain is NOT_ASSESSED, never guessed); every statement cites a claim ref that resolves
into the envelope (the "cite the resolvable, not the absent" mechanism ``facet_critical_unknowns`` /
``facet_thesis_archetype`` already use for their own NOT_ASSESSED entries — here, the presence of ANY
assessed domain in the envelope); when NOTHING resolves anywhere the facet is omitted (return None),
matching every sibling facet's own guard.

Uniform facet-builder contract: ``build(ctx) -> Optional[dict]``. See schema.py / assembler.FACET_BUILDERS.
"""

from __future__ import annotations

from typing import Mapping, Optional

from _skills_common import evidence_frame as EF
from _skills_common.l4_synthesis import schema as S
from _skills_common.l4_synthesis.context import L4Context

BUILT = True

MODALITY_SMALL_MOLECULE = "small_molecule"
MODALITY_ADC = "adc"
MODALITY_TCE = "tce"
MODALITIES = (MODALITY_SMALL_MOLECULE, MODALITY_ADC, MODALITY_TCE)

# Which KNOWN_DOMAINS each modality's opportunity/liability read depends on. A surface-antigen modality
# (ADC/TCE) needs the target to be PRESENT + SURFACE-ACCESSIBLE + tumor-SELECTIVE + on-target SAFE; a
# small-molecule/degrader modality instead needs a genetic DEPENDENCY + a resolvable ALTERATION mix +
# TRACTABILITY + on-target safety. Fixed, documented, collision-free (duplicated locally rather than
# imported from a sibling facet's private constant, per the module-independence convention #2006/#2007
# already establish).
_MODALITY_RELEVANT_DOMAINS = {
    MODALITY_SMALL_MOLECULE: ("dependency", "genomic_alteration", "tractability", "on_target_safety"),
    MODALITY_ADC: ("tumor_presence", "surface_modality", "tumor_selectivity", "on_target_safety"),
    MODALITY_TCE: ("tumor_presence", "surface_modality", "tumor_selectivity", "on_target_safety"),
}

# The SK#1844 per-modality decision frames this facet reuses read-only, keyed by modality (small_molecule
# has no analogous frame yet — its critical_unknown is domain-absence only).
_MODALITY_FRAME_FN = {
    MODALITY_ADC: EF.adc_modality_fit_frame,
    MODALITY_TCE: EF.tce_modality_fit_frame,
}

_LOW_CORROBORATION = frozenset({"low", "none", "absent"})


def _is_positive_chapter(chapter) -> bool:
    """Structural over the shared L3d chapter shape — see ``facet_opportunity_drivers`` for the same rule
    (duplicated locally, module-independence convention)."""
    if not isinstance(chapter, dict):
        return False
    cls = chapter.get("concordance_class")
    if not isinstance(cls, str) or not cls or "discordant" in cls:
        return False
    corroboration = chapter.get("corroboration")
    if not isinstance(corroboration, str) or corroboration in _LOW_CORROBORATION:
        return False
    return True


def _chapter_ref(chapter: Mapping, domain: str) -> Optional[dict]:
    cid = chapter.get("claim_id")
    if not isinstance(cid, str) or not cid:
        return None
    return S.claim_ref(cid, vector=chapter.get("reconstructable_from"), domain=domain)


def _vector_for(chapters: list, claim_id: str) -> Optional[str]:
    for ch in chapters:
        if isinstance(ch, Mapping) and ch.get("claim_id") == claim_id:
            v = ch.get("reconstructable_from")
            return v if isinstance(v, str) else None
    return None


def _domain_ref(domain: str) -> dict:
    return S.claim_ref(f"l3d::{domain}", domain=domain)


def _frame_note(modality: str, headline: Mapping) -> Optional[str]:
    """A read-only informational note from the modality's ADC/TCE decision frame (SK#1844), folded as
    descriptive TEXT into a statement that cites already-resolvable domain refs (see module docstring) —
    never a standalone citation of the frame object itself. None when the envelope carries none of the
    composite class tokens the frame consumes (the honest, non-fabricated common case today)."""
    fn = _MODALITY_FRAME_FN.get(modality)
    if fn is None:
        return None
    result = fn(headline)
    if not result.get("resolved_inputs"):
        return None
    return (
        f"the {modality} decision frame `{result.get('frame_id')}` reads '{result.get('decision')}' over "
        f"the resolved composite input(s) {sorted(result['resolved_inputs'])}"
    )


def build(ctx: L4Context) -> Optional[dict]:
    if not ctx.l3d_domains:
        return None  # nothing assessed anywhere -> nothing to organize by modality (byte-stable omission)

    # The only resolvable fallback refs for a NOT_ASSESSED entry: what the envelope DOES prove.
    presence_refs: list = []
    for name in ctx.assessed_domains:
        story = ctx.l3d_domains[name]
        chapters = story.get("chapters") if isinstance(story.get("chapters"), list) else []
        for ch in chapters:
            ref = _chapter_ref(ch, name) if isinstance(ch, Mapping) else None
            if ref is not None:
                presence_refs.append(ref)
        presence_refs.append(_domain_ref(name))
    if not presence_refs:
        return None  # a resolved domain that cites nothing gives us nothing traceable to fall back on

    headline = ctx.decision.get("headline") if isinstance(ctx.decision, Mapping) else None
    headline = headline if isinstance(headline, Mapping) else {}

    implications: dict = {}
    statements: list = []

    for modality in MODALITIES:
        relevant = _MODALITY_RELEVANT_DOMAINS[modality]
        opportunity: list = []
        liability: list = []
        critical_unknown: list = []

        for domain in relevant:
            story = ctx.l3d_domains.get(domain)
            if not isinstance(story, Mapping):
                critical_unknown.append(
                    {
                        "domain": domain,
                        "status": "NOT_ASSESSED",
                        "note": f"{domain} evidence for {modality} is not assessed in this envelope",
                        "claim_ids": list(presence_refs),
                    }
                )
                continue

            chapters = story.get("chapters") if isinstance(story.get("chapters"), list) else []
            for ch in chapters:
                if not isinstance(ch, Mapping):
                    continue
                ref = _chapter_ref(ch, domain)
                if ref is None or not _is_positive_chapter(ch):
                    continue
                text = (ch.get("reads") or ch.get("within_domain_role") or "").strip()
                if not text:
                    continue
                opportunity.append(
                    {"domain": domain, "aspect": ch.get("aspect"), "statement": text, "claim_ids": [ref]}
                )

            for cv in story.get("caveats") or []:
                if not isinstance(cv, Mapping):
                    continue
                cid = cv.get("claim_id")
                note = cv.get("caveat")
                if not isinstance(cid, str) or not cid or not isinstance(note, str) or not note:
                    continue
                lref = S.claim_ref(cid, vector=_vector_for(chapters, cid), domain=domain)
                liability.append({"domain": domain, "aspect": cv.get("aspect"), "liability": note, "claim_ids": [lref]})

        note = _frame_note(modality, headline)
        if note:
            critical_unknown.append(
                {
                    "domain": "surface_modality",
                    "status": "informational",
                    "note": note,
                    "claim_ids": list(presence_refs),
                }
            )

        if not (opportunity or liability or critical_unknown):
            continue  # nothing resolves for this modality -> omit it, never a placeholder triple

        implications[modality] = {
            "opportunity": opportunity,
            "liability": liability,
            "critical_unknown": critical_unknown,
        }
        for item in opportunity:
            statements.append(
                S.statement(
                    f"[{modality}] opportunity ({item['domain']}/{item['aspect']}): {item['statement']}",
                    item["claim_ids"],
                )
            )
        for item in liability:
            statements.append(
                S.statement(
                    f"[{modality}] liability ({item['domain']}/{item['aspect']}): {item['liability']}",
                    item["claim_ids"],
                )
            )
        for item in critical_unknown:
            statements.append(S.statement(f"[{modality}] critical_unknown: {item['note']}", item["claim_ids"]))

    if not implications:
        return None  # no modality resolved anything -> facet omitted (byte-stable), never fabricated

    return {
        "facet": S.FACET_MODALITY_IMPLICATIONS,
        "layer": S.L4_LAYER,
        "built_by": "C0e #2008",
        "modality_implications": implications,
        "statements": statements,
        "integration_method": S.INTEGRATION_METHOD,
        "_disclaimer": (
            "L4 modality_implications (C0e #2008) — DETERMINISTIC facet assembly, PER MODALITY, over the "
            "assessed L3d domain stories filtered by modality-relevance + the SK#1844 ADC/TCE decision "
            "frames evaluated read-only, verdict-INERT (reads no verdict, feeds no rule/veto/resolver, "
            "moves no emitted field), no new measurement, no LLM authorship. NOT a scalar per-modality "
            "fit score: each modality carries its own {opportunity, liability, critical_unknown} triple. "
            "Absence outranks measurement: an unassessed modality-relevant domain is NOT_ASSESSED, never "
            "guessed. Every statement drills back to the cited L2/L3 claim IDs."
        ),
    }
