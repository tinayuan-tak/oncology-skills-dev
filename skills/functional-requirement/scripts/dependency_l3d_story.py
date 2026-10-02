"""dependency_l3d_story — the functional-requirement (dependency) L3d "dependency biology story"
assembler (SK#2488, epic #2210 / parent #1507).

L3d = domain interpretation: "the coherent biological story WITHIN one evidence domain, packaging its
L2 properties into something human- and LLM-usable ... traceable back to L2 claim IDs" (see
``docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md`` §"Layer semantics"). This module builds dependency's
L3d object: a within-domain synthesis over the L2b concordance islands the dependency claim vector
already carries. It is the direct analog of the tumor-presence reference L3d
(``presence_l3d_story.build_tumor_expression_biology_story``, SK#1940) and the cis-feature-coherence
L3d (``cis_coherence_l3d_story.build_cis_coherence_biology_story``, SK#1981) and mirrors their shape.

Design constraints (all load-bearing — copied from the presence/cis exemplars):

  * DETERMINISTIC template/traversal assembly, NOT LLM authorship. Per the governing architecture
    (L2b/L3d "no LLM authorship; reproducible by contract", ``docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md``),
    the L3d story is the deterministic layer — it TRAVERSES the already-computed L2b concordance claims
    and re-uses their own deterministic prose. It is byte-stable and golden-snapshottable. The opt-in
    ``--synthesize`` LLM narration is a SEPARATE view that sits ABOVE L3d and is never wired here.

  * CLAIM-ID TRACEABLE. Every chapter cites the L2b claim ID (the KEY the island occupies on the
    dependency claim vector) it rests on, so a consumer reconstructs the story downward by indexing
    straight back into the vector. It resolves NOTHING itself — it is a pure projection over the L2
    claims handed to it.

  * WITHIN-DOMAIN ONLY (L3d, NOT L3f). It stays strictly inside the dependency semantic scope (genetic
    essentiality / context-selectivity / conditional-SL / chemical-genetic confirmation) and NEVER
    concludes anything that needs another domain's evidence (selectivity, safety, tractability, a
    therapeutic window). ``cross_domain_claims`` is emitted and is ALWAYS empty — a machine-checkable
    floor a governance test pins. It is also distinct from the SEPARATE L3f reference frame this domain
    already carries (``evidence_frame.dependency_priority_frame`` / ``corroborated_dependency_priority``)
    — this module never touches that frame.

  * VERDICT-INERT / additive. It reads no verdict, feeds no rule / veto / resolver rung, and NEVER moves
    dependency_verdict, dependency_verdict_by_scope, or any resolver golden. It rides as a NEW additive
    key on the dependency headline. Returns None (key omitted -> byte-stable) when no L2b island
    resolves, matching the concordance-claim discipline in ``dependency_claims.py``.

  * ISLAND ROSTER, not a hardcoded guarantee. ``_ASPECTS`` below names every L2b concordance island this
    story is DECLARED to package — today only ``crispr_rnai_essentiality_concordance`` (SK#1533) actually
    resolves on the dependency claim vector. ``expression_dependency_concordance`` and
    ``prism_crispr_concordance`` are forward-declared: dependency_claims.py does not populate either key
    today (per this issue's "file NO new L2b concordance family" constraint — that is peer-epic work,
    #1730/#1755/#1779/#1812), so those two aspects simply never resolve yet. A chapter is built ONLY for
    an island actually present on the vector (``_island()`` below) — the roster is forward-compatible,
    not a promise this run emits all three.
"""

from __future__ import annotations

from typing import Mapping, Optional

# The L3d object's emitted layer id — kept in lockstep with the readable-layer declaration in
# ``_skills_common.evidence_frame.reference_emitted_layers`` (SK#2488). A test asserts they match, so
# this string is the single source of truth for the story's property_id / emitted key.
L3D_STORY_PROPERTY_ID = "dependency_biology_story"

# The dependency L2b islands this domain story is declared to package, in a STABLE canonical order
# (essentiality concordance first — the central, currently-landed cross-source island; the two
# forward-declared aspects follow). Each tuple is: (aspect, claim_id, aspect_gloss). All three ride the
# SINGLE dependency claim vector (there is no by-subtype vector for this domain's L2b islands), so the
# downward reconstruction path is: index ``claim_id`` back into the dependency claim vector for the full
# L2b integration claim.
_DEPENDENCY_CLAIM_VECTOR = "claim_vector"
_PRIMARY_ASPECT = "essentiality_concordance"
_ASPECTS = (
    (
        _PRIMARY_ASPECT,
        "crispr_rnai_essentiality_concordance",
        "ESSENTIALITY DEPTH — do two independent loss-of-function assays (CRISPR Chronos knockout x "
        "RNAi DEMETER2 knockdown) agree the target is a genetic dependency?",
    ),
    (
        # Forward-declared (SK#2488): no card currently populates this claim_id on the dependency
        # vector — dependency_claims.py carries NO expression->dependency L2b island today (the
        # analogous `expression_dependency_concordance` family lives on the cis-feature-coherence
        # claim vector instead, a DIFFERENT skill/domain). Resolves automatically, with zero further
        # change to this file, once/if a sibling peer epic lands that island on THIS vector.
        "expression_dependency",
        "expression_dependency_concordance",
        "EXPRESSION->DEPENDENCY coupling — does the target's own-omics expression predict its genetic dependency?",
    ),
    (
        # Forward-declared (SK#2488): the CHEM axis today carries a signal-bearing (not concordance-
        # shaped) claim keyed off the prism-crispr-concordance card; this is a distinct, not-yet-landed
        # L2b concordance island on the SAME vector. Resolves automatically once a sibling peer epic
        # lands it.
        "chemical_genetic_concordance",
        "prism_crispr_concordance",
        "CHEMICAL-GENETIC CONFIRMATION — does PRISM compound-kill track the CRISPR/RNAi genetic "
        "dependency, cross-validating the essentiality call?",
    ),
)


def _island(vec: Optional[Mapping], claim_id: str) -> "Optional[dict]":
    """Read an L2b concordance island off the dependency claim vector; None when the vector or the key
    is absent."""
    if not isinstance(vec, Mapping):
        return None
    isl = vec.get(claim_id)
    return isl if isinstance(isl, Mapping) else None


def _signal_text(island: Mapping, key: str) -> "Optional[str]":
    """The deterministic prose an island already carries for its positive/qualifying direction."""
    sig = island.get(key)
    if isinstance(sig, Mapping):
        stmt = sig.get("statement")
        return stmt if isinstance(stmt, str) and stmt else None
    return None


def _chapter(aspect: str, claim_id: str, gloss: str, island: Mapping) -> dict:
    """One traversed chapter: the island's concordance read, re-using its OWN deterministic signals,
    tagged with the claim ID + the vector it is reconstructable from. Verdict-inert projection."""
    return {
        "aspect": aspect,
        "aspect_question": gloss,
        # The downward provenance handle: index this claim_id back into the dependency claim vector.
        "claim_id": claim_id,
        "reconstructable_from": _DEPENDENCY_CLAIM_VECTOR,
        "concordance_class": island.get("concordance_class"),
        "corroboration": island.get("corroboration"),
        # Re-used verbatim from the L2b claim (deterministic prose; NOT re-authored here).
        "reads": _signal_text(island, "positive_signal"),
        "caveat": _signal_text(island, "qualifying_signal"),
        "boundary_sensitive": bool(island.get("boundary_sensitive")),
        "within_domain_role": island.get("informs"),
    }


def _coherence(central: "Optional[dict]", chapters: list) -> str:
    """The WITHIN-DOMAIN coherence class — a deterministic synthesis token (deliberately NOT any
    dependency_verdict vocabulary, and never a cross-domain decision). It is anchored on the
    ``crispr_rnai_essentiality_concordance`` central node when present; otherwise it names that the
    story rests on the peripheral islands alone."""
    if central is not None:
        cls = central.get("concordance_class")
        boundary = bool(central.get("boundary_sensitive"))
        if cls == "essentiality_concordant_dependent":
            return "cross_assay_corroborated_boundary_sensitive" if boundary else "cross_assay_corroborated"
        if cls == "essentiality_concordant_nondependent":
            return "cross_assay_corroborated_nondependent"
        if cls == "essentiality_assay_discordant":
            return "cross_assay_discordant"
        if cls == "essentiality_single_assay_only":
            return "single_assay_read"
        return "central_node_unclassified"
    # No central node — synthesize from the peripheral islands alone.
    return "peripheral_islands_only" if chapters else "no_resolved_island"


def build_dependency_biology_story(claim_vector: Optional[Mapping]) -> "Optional[dict]":
    """Assemble the L3d dependency biology story from the ALREADY-computed L2 claims.

    Pure, deterministic traversal of the L2b concordance islands on the dependency claim vector.
    Returns None — key omitted, byte-stable — when NO island resolves. Verdict-INERT: reads no verdict,
    produces no decision, routes nothing back into a lower layer; it is a NEW additive interpretation
    key, not a re-derivation of dependency_verdict.
    """
    chapters: list = []
    central_chapter: Optional[dict] = None
    for aspect, claim_id, gloss in _ASPECTS:
        island = _island(claim_vector, claim_id)
        if island is None:
            continue
        ch = _chapter(aspect, claim_id, gloss, island)
        chapters.append(ch)
        if aspect == _PRIMARY_ASPECT:
            central_chapter = ch

    if not chapters:
        return None  # no L2b island resolves -> no story -> key omitted (byte-stable)

    # The within-domain caveats a reader should carry, each tagged with the claim ID it came from —
    # surfaced (never suppressed), never a negation. Deterministic order (chapter order).
    caveats = [
        {"aspect": ch["aspect"], "claim_id": ch["claim_id"], "caveat": ch["caveat"]} for ch in chapters if ch["caveat"]
    ]
    # The story headline: a deterministic within-domain sentence assembled from the resolved islands'
    # OWN prose (central node's read first when present, else the first resolved island). NOT re-authored.
    lead = central_chapter or chapters[0]
    headline = lead["reads"] or (f"dependency read rests on {lead['aspect']} ({lead['claim_id']})")

    return {
        "layer": "L3d",
        "domain": "dependency",
        "title": "dependency biology story",
        # The within-domain synthesis class (deterministic; NOT a dependency_verdict, NOT cross-domain).
        "coherence": _coherence(central_chapter, chapters),
        "headline": headline,
        # The traversed chapters — one per resolved L2b island, each claim-ID traceable downward.
        "chapters": chapters,
        "caveats": caveats,
        # Machine-checkable within-domain floor: L3d NEVER concludes what needs another domain. Always [].
        "cross_domain_claims": [],
        "scope": {
            "within_domain": "dependency",
            "excludes": ["tumor_selectivity", "on_target_safety", "tractability", "therapeutic_window"],
            "note": (
                "L3d domain interpretation — stays strictly inside dependency's semantic scope (genetic "
                "essentiality / context-selectivity / conditional-SL / chemical-genetic confirmation). It "
                "does NOT conclude anything that requires another domain's evidence; that cross-domain "
                "implication is reserved for an L3f decision frame (this domain's own "
                "`corroborated_dependency_priority` reference frame, untouched by this module)."
            ),
        },
        "integration_method": "deterministic_template_traversal",
        "provenance": {
            # Every L2b claim ID this story rests on — reconstruct the full claim downward by indexing
            # the named vector with the claim_id.
            "claim_ids": [{"claim_id": ch["claim_id"], "vector": ch["reconstructable_from"]} for ch in chapters],
            "reconstructable": (
                "each chapter's claim_id indexes back into the dependency claim vector for the full L2b "
                "integration claim; the L3d story asserts nothing the L2 claims do not already carry"
            ),
        },
        "_disclaimer": (
            "L3d WITHIN-DOMAIN interpretation (SK#2488) — DETERMINISTIC template/traversal assembly (no "
            "LLM authorship, reproducible by contract), verdict-INERT: never a signal tier, never "
            "averaged, never feeds the dependency_verdict, dependency_verdict_by_scope, or any resolver "
            "rung. The opt-in --synthesize LLM narration is a SEPARATE view above this layer. Traceable "
            "back to the L2b claim IDs it cites; makes NO cross-domain conclusion."
        ),
    }
