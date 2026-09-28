"""cis_coherence_l3d_story — the cis-feature-coherence L3d "cis-regulatory coherence biology story"
assembler (SK#1981, epic #1779 B2 / parent #1507).

L3d = domain interpretation: "the coherent biological story WITHIN one evidence domain, packaging its
L2 properties into something human- and LLM-usable ... traceable back to L2 claim IDs" (see
``docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md`` §"Layer semantics"). This module builds
cis-coherence's L3d object: a within-domain synthesis over the L2b concordance islands the cis claim
vector already carries. It is the direct analog of the tumor-presence reference L3d
(``presence_l3d_story.build_tumor_expression_biology_story``, SK#1940) and mirrors its shape exactly.

Design constraints (all load-bearing — copied from the presence exemplar):

  * DETERMINISTIC template/traversal assembly, NOT LLM authorship. Per the governing architecture
    (L2b/L3d "no LLM authorship; reproducible by contract", ``docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md``),
    the L3d story is the deterministic layer — it TRAVERSES the already-computed L2b concordance claims
    and re-uses their own deterministic prose. It is byte-stable and golden-snapshottable. The opt-in
    ``--synthesize`` LLM narration is a SEPARATE view that sits ABOVE L3d and is never wired here.

  * CLAIM-ID TRACEABLE. Every chapter cites the L2b claim ID (the KEY the island occupies on the cis
    claim vector) it rests on, so a consumer reconstructs the story downward by indexing straight back
    into the vector. It resolves NOTHING itself — it is a pure projection over the L2 claims handed to it.

  * WITHIN-DOMAIN ONLY (L3d, NOT L3f). It stays strictly inside the cis-coherence semantic scope
    (cis-dosage coupling / epigenetic silencing / expression->dependency coupling — with the isoform /
    protein modality arms already folded into those L2b islands) and NEVER concludes anything that needs
    another domain's evidence (selectivity, safety, tractability, a therapeutic window).
    ``cross_domain_claims`` is emitted and is ALWAYS empty — a machine-checkable floor a governance test
    pins.

  * VERDICT-INERT / additive. It reads no verdict, feeds no rule / veto / resolver rung, and NEVER moves
    cis_coherence_verdict, driving_rule_id, certainty.*, or any resolver golden. It rides as a NEW
    additive key on the cis-coherence headline. Returns None (key omitted -> byte-stable) when no L2b
    island resolves, matching the concordance-claim discipline in ``cis_coherence_claims.py``.
"""

from __future__ import annotations

from typing import Mapping, Optional

# The L3d object's emitted layer id — kept in lockstep with the readable-layer declaration in
# ``_skills_common.evidence_frame.reference_emitted_layers`` (SK#1981, ``CIS_COHERENCE_BIOLOGY_STORY_L3D``).
# A test asserts they match, so this string is the single source of truth for the story's property_id /
# emitted key.
L3D_STORY_PROPERTY_ID = "cis_coherence_biology_story"

# The three cis-coherence L2b islands this domain story packages, in a STABLE canonical order
# (cis-dosage coupling first — the headline "does copy-number dosage drive own expression" property — then
# the epigenetic-silencing arm, then the expression->dependency coupling arm). Each tuple is:
#   (aspect, claim_id, aspect_gloss)
# All three ride the SINGLE cis claim vector (there is no by-subtype vector for this domain — unlike
# tumor-presence), so the downward reconstruction path is: index ``claim_id`` back into the cis claim
# vector for the full L2b integration claim.
_CIS_CLAIM_VECTOR = "cis_claim_vector"
_ASPECTS = (
    (
        "cis_dosage",
        "cis_dosage_concordance",
        "CIS-DOSAGE coupling — does copy-number dosage drive the target's OWN expression, replicated "
        "across the cell-line-model and patient-tumour grains?",
    ),
    (
        "methylation_silencing",
        "methylation_silencing_concordance",
        "EPIGENETIC SILENCING — does promoter methylation silence the target's OWN expression, replicated "
        "across the cell-line-model and patient-tumour grains?",
    ),
    (
        "expression_dependency",
        "expression_dependency_concordance",
        "EXPRESSION->DEPENDENCY coupling — does the target's own-omics abundance predict its dependency, "
        "agreed across the bulk-RNA and MS-protein assay modalities?",
    ),
)


def _island(vec: Optional[Mapping], claim_id: str) -> "Optional[dict]":
    """Read an L2b concordance island off the claim vector; None when the vector or the key is absent."""
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
        # The downward provenance handle: index this claim_id back into the cis claim vector for the L2b claim.
        "claim_id": claim_id,
        "reconstructable_from": _CIS_CLAIM_VECTOR,
        "concordance_class": island.get("concordance_class"),
        "corroboration": island.get("corroboration"),
        # Re-used verbatim from the L2b claim (deterministic prose; NOT re-authored here).
        "reads": _signal_text(island, "positive_signal"),
        "caveat": _signal_text(island, "qualifying_signal"),
        "boundary_sensitive": bool(island.get("boundary_sensitive")),
        "within_domain_role": island.get("informs"),
    }


def _coherence(chapters: list) -> str:
    """The WITHIN-DOMAIN coherence class — a deterministic synthesis token (deliberately NOT any
    cis_coherence_verdict vocabulary, and never a cross-domain decision).

    cis-coherence has no single central-node island (its verdict is the 2x2 INTERACTION of legs owned by
    the resolver, not one integration claim), so the token is synthesized over the RESOLVED cis axes: an
    island whose concordance_class names a cross-arm ``discordant`` is the informative disagreement and
    dominates; otherwise a multi-axis corroborated read outranks a single-axis one, with boundary
    sensitivity surfaced (never suppressed)."""
    if not chapters:
        return "no_resolved_island"
    classes = [ch["concordance_class"] for ch in chapters]
    if any(isinstance(c, str) and "discordant" in c for c in classes):
        return "within_domain_discordant"
    boundary = any(ch["boundary_sensitive"] for ch in chapters)
    if len(chapters) >= 2:
        return "cross_axis_corroborated_boundary_sensitive" if boundary else "cross_axis_corroborated"
    return "single_axis_boundary_sensitive" if boundary else "single_axis_read"


def build_cis_coherence_biology_story(claim_vector: Optional[Mapping]) -> "Optional[dict]":
    """Assemble the L3d cis-regulatory coherence biology story from the ALREADY-computed L2 claims.

    Pure, deterministic traversal of the L2b concordance islands on the cis claim vector. Returns None —
    key omitted, byte-stable — when NO island resolves. Verdict-INERT: reads no verdict, produces no
    decision, routes nothing back into a lower layer; it is a NEW additive interpretation key, not a
    re-derivation of cis_coherence_verdict.
    """
    chapters: list = []
    for aspect, claim_id, gloss in _ASPECTS:
        island = _island(claim_vector, claim_id)
        if island is None:
            continue
        chapters.append(_chapter(aspect, claim_id, gloss, island))

    if not chapters:
        return None  # no L2b island resolves -> no story -> key omitted (byte-stable)

    # The within-domain caveats a reader should carry, each tagged with the claim ID it came from —
    # surfaced (never suppressed), never a negation. Deterministic order (chapter order).
    caveats = [
        {"aspect": ch["aspect"], "claim_id": ch["claim_id"], "caveat": ch["caveat"]} for ch in chapters if ch["caveat"]
    ]
    # The story headline: a deterministic within-domain sentence assembled from the resolved islands'
    # OWN prose (leads with the first resolved island in canonical order — cis-dosage when present). NOT
    # re-authored here.
    lead = chapters[0]
    headline = lead["reads"] or (f"cis-coherence read rests on {lead['aspect']} ({lead['claim_id']})")

    return {
        "layer": "L3d",
        "domain": "cis_feature_coherence",
        "title": "cis-regulatory coherence biology story",
        # The within-domain synthesis class (deterministic; NOT a cis_coherence_verdict, NOT cross-domain).
        "coherence": _coherence(chapters),
        "headline": headline,
        # The traversed chapters — one per resolved L2b island, each claim-ID traceable downward.
        "chapters": chapters,
        "caveats": caveats,
        # Machine-checkable within-domain floor: L3d NEVER concludes what needs another domain. Always [].
        "cross_domain_claims": [],
        "scope": {
            "within_domain": "cis_feature_coherence",
            "excludes": ["tumor_selectivity", "on_target_safety", "tractability", "therapeutic_window"],
            "note": (
                "L3d domain interpretation — stays strictly inside cis-feature-coherence's semantic scope "
                "(cis-dosage coupling / epigenetic silencing / expression->dependency coupling, with the "
                "isoform / protein modality arms folded into those L2b islands). It does NOT conclude "
                "anything that requires another domain's evidence; that cross-domain implication is "
                "reserved for an L3f decision frame."
            ),
        },
        "integration_method": "deterministic_template_traversal",
        "provenance": {
            # Every L2b claim ID this story rests on — reconstruct the full claim downward by indexing
            # the named vector with the claim_id.
            "claim_ids": [{"claim_id": ch["claim_id"], "vector": ch["reconstructable_from"]} for ch in chapters],
            "reconstructable": (
                "each chapter's claim_id indexes back into the cis claim vector for the full L2b "
                "integration claim; the L3d story asserts nothing the L2 claims do not already carry"
            ),
        },
        "_disclaimer": (
            "L3d WITHIN-DOMAIN interpretation (SK#1981) — DETERMINISTIC template/traversal assembly (no "
            "LLM authorship, reproducible by contract), verdict-INERT: never a signal tier, never "
            "averaged, never feeds the cis_coherence_verdict, driving_rule_id, certainty.*, or any "
            "resolver rung. The opt-in --synthesize LLM narration is a SEPARATE view above this layer. "
            "Traceable back to the L2b claim IDs it cites; makes NO cross-domain conclusion."
        ),
    }
