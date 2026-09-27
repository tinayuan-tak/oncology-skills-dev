"""presence_l3d_story — the tumor-presence L3d "tumor-expression biology story" assembler (SK#1940).

L3d = domain interpretation: "the coherent biological story WITHIN one evidence domain, packaging its
L2 properties into something human- and LLM-usable ... traceable back to L2 claim IDs" (see
``docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md`` §"Layer semantics", :216-233). This module builds
tumor-presence's L3d object: a within-domain synthesis over the L2b concordance islands the presence
claim vector already carries.

Design constraints (all load-bearing):

  * DETERMINISTIC template/traversal assembly, NOT LLM authorship. Per the governing architecture
    (L2b/L3d "no LLM authorship; reproducible by contract", ``docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md``),
    the L3d story is the deterministic layer — it TRAVERSES the already-computed L2b claims and re-uses
    their own deterministic prose. It is byte-stable and golden-snapshottable. The opt-in
    ``--synthesize`` LLM narration is a SEPARATE view that sits ABOVE L3d and is never wired here.

  * CLAIM-ID TRACEABLE. Every chapter cites the L2b claim ID (the KEY the island occupies on the
    presence claim vector / by-subtype vector) it rests on, so a consumer reconstructs the story
    downward by indexing straight back into those vectors. It resolves NOTHING itself — it is a pure
    projection over the L2 claims handed to it.

  * WITHIN-DOMAIN ONLY (L3d, NOT L3f). It stays strictly inside the tumor-presence semantic scope
    (presence / abundance / coverage-heterogeneity / subtype-restriction / protein confirmation) and
    NEVER concludes anything that needs another domain's evidence (selectivity, safety, tractability,
    a therapeutic window). ``cross_domain_claims`` is emitted and is ALWAYS empty — a machine-checkable
    floor that a governance test pins.

  * VERDICT-INERT / additive. It reads no verdict, feeds no rule / veto / resolver rung, and NEVER
    moves presence_verdict, presence_verdict_by_modality, certainty.level, or any resolver golden. It
    rides as a NEW additive key on the presence headline. Returns None (key omitted -> byte-stable)
    when no L2b island resolves, matching the concordance-atom discipline in presence_claims.py.
"""

from __future__ import annotations

from typing import Mapping, Optional

# The L3d object's emitted layer id — kept in lockstep with the readable-layer declaration in
# ``_skills_common.evidence_frame.reference_emitted_layers`` (SK#1940). A test asserts they match, so
# this string is the single source of truth for the story's property_id / emitted key.
L3D_STORY_PROPERTY_ID = "tumor_expression_biology_story"

# The five L2b presence islands this domain story packages, in a STABLE canonical order (central node
# first — it is the headline cross-source presence property, #1867 — then the modality-pair concordances
# it decomposes into, then the by-subtype refinement). Each tuple is:
#   (aspect, claim_id, vector, aspect_gloss)
# ``vector`` names WHERE the claim lives so the downward reconstruction path is explicit: the central /
# coverage / abundance / protein islands ride the POOLED claim vector; subtype_restriction is keyed on
# the BY-SUBTYPE vector (it is not on the pooled vector — see presence_claims.py).
_POOLED = "pooled_claim_vector"
_BY_SUBTYPE = "by_subtype_claim_vector"
_ASPECTS = (
    (
        "tumor_presence",
        "tumor_presence_concordance",
        _POOLED,
        "cross-source tumor PRESENCE integrated across bulk-RNA x single-cell malignant RNA x antibody-IHC",
    ),
    (
        "coverage",
        "bulk_vs_singlecell_coverage_concordance",
        _POOLED,
        "within-tumour COVERAGE — does bulk presence carry through to single-cell malignant coverage, or "
        "is a fraction bulk-masked?",
    ),
    (
        "abundance",
        "abundance_concordance",
        _POOLED,
        "ABUNDANCE agreement between the RNA transcript level and the protein antigen level",
    ),
    (
        "protein_presence",
        "protein_presence_concordance",
        _POOLED,
        "PROTEIN presence folded across independent antibody-IHC and mass-spec arms",
    ),
    (
        "subtype_restriction",
        "subtype_restriction_concordance",
        _BY_SUBTYPE,
        "SUBTYPE-RESTRICTION — is the presence read uniform across subtypes or concentrated in a stratum?",
    ),
)


def _island(vec: Optional[Mapping], claim_id: str) -> "Optional[dict]":
    """Read an L2b concordance island off a claim vector; None when the vector or the key is absent."""
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


def _chapter(aspect: str, claim_id: str, vector: str, gloss: str, island: Mapping) -> dict:
    """One traversed chapter: the island's concordance read, re-using its OWN deterministic signals,
    tagged with the claim ID + the vector it is reconstructable from. Verdict-inert projection."""
    return {
        "aspect": aspect,
        "aspect_question": gloss,
        # The downward provenance handle: index this claim_id back into ``vector`` for the full L2b claim.
        "claim_id": claim_id,
        "reconstructable_from": vector,
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
    presence_verdict vocabulary, and never a cross-domain decision). It is anchored on the central
    ``tumor_presence_concordance`` node (#1867) when present; otherwise it names that the story rests on
    the peripheral islands alone."""
    if central is not None:
        cls = central.get("concordance_class")
        boundary = bool(central.get("boundary_sensitive"))
        if cls == "tumor_presence_concordant":
            return "cross_source_corroborated_boundary_sensitive" if boundary else "cross_source_corroborated"
        if cls == "tumor_presence_discordant":
            return "cross_source_discordant"
        if cls == "single_source_only":
            return "single_source_read"
        return "central_node_unclassified"
    # No central node — synthesize from the peripheral islands alone.
    return "peripheral_islands_only" if chapters else "no_resolved_island"


def build_tumor_expression_biology_story(
    claim_vector: Optional[Mapping], claim_vector_by_subtype: Optional[Mapping] = None
) -> "Optional[dict]":
    """Assemble the L3d tumor-expression biology story from the ALREADY-computed L2 claims.

    Pure, deterministic traversal of the L2b concordance islands on the pooled claim vector (+ the
    by-subtype vector for subtype-restriction). Returns None — key omitted, byte-stable — when NO island
    resolves. Verdict-INERT: reads no verdict, produces no decision, routes nothing back into a lower
    layer; it is a NEW additive interpretation key, not a re-derivation of presence_verdict.
    """
    vectors = {_POOLED: claim_vector, _BY_SUBTYPE: claim_vector_by_subtype}
    chapters: list = []
    central_chapter: Optional[dict] = None
    for aspect, claim_id, vector, gloss in _ASPECTS:
        island = _island(vectors.get(vector), claim_id)
        if island is None:
            continue
        ch = _chapter(aspect, claim_id, vector, gloss, island)
        chapters.append(ch)
        if aspect == "tumor_presence":
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
    headline = lead["reads"] or (f"tumor-presence read rests on {lead['aspect']} ({lead['claim_id']})")

    return {
        "layer": "L3d",
        "domain": "tumor_presence",
        "title": "tumor-expression biology story",
        # The within-domain synthesis class (deterministic; NOT a presence_verdict, NOT cross-domain).
        "coherence": _coherence(central_chapter, chapters),
        "headline": headline,
        # The traversed chapters — one per resolved L2b island, each claim-ID traceable downward.
        "chapters": chapters,
        "caveats": caveats,
        # Machine-checkable within-domain floor: L3d NEVER concludes what needs another domain. Always [].
        "cross_domain_claims": [],
        "scope": {
            "within_domain": "tumor_presence",
            "excludes": ["tumor_selectivity", "on_target_safety", "tractability", "therapeutic_window"],
            "note": (
                "L3d domain interpretation — stays strictly inside tumor-presence's semantic scope "
                "(presence / abundance / coverage-heterogeneity / subtype-restriction / protein "
                "confirmation). It does NOT conclude anything that requires another domain's evidence; "
                "that cross-domain implication is reserved for an L3f decision frame."
            ),
        },
        "integration_method": "deterministic_template_traversal",
        "provenance": {
            # Every L2b claim ID this story rests on — reconstruct the full claim downward by indexing
            # the named vector with the claim_id.
            "claim_ids": [{"claim_id": ch["claim_id"], "vector": ch["reconstructable_from"]} for ch in chapters],
            "reconstructable": (
                "each chapter's claim_id indexes back into the named presence claim vector "
                "(pooled) or by-subtype claim vector for the full L2b integration claim; the L3d "
                "story asserts nothing the L2 claims do not already carry"
            ),
        },
        "_disclaimer": (
            "L3d WITHIN-DOMAIN interpretation (SK#1940) — DETERMINISTIC template/traversal assembly (no "
            "LLM authorship, reproducible by contract), verdict-INERT: never a signal tier, never "
            "averaged, never feeds the presence_verdict, presence_verdict_by_modality, certainty.level, "
            "or any resolver rung. The opt-in --synthesize LLM narration is a SEPARATE view above this "
            "layer. Traceable back to the L2b claim IDs it cites; makes NO cross-domain conclusion."
        ),
    }
