"""Facet builder — decision_dimensions (5R as FACETS of the one synthesis). BUILT (C0e #2008).

The 5R read — right_target / right_tissue / right_safety / right_patient / right_drug — as VIEWS that
REORGANIZE the already-assessed L3d domain evidence gathered on ``ctx``, NOT a separate scoring system and
NOT a scalar N/5 (docs §"L4 object" ``decision_dimensions`` + §"Frame on the way in, view on the way out").
Each dimension is a fixed, documented projection over a subset of ``schema.KNOWN_DOMAINS`` — the same
domains the OTHER L4 facets already read, re-bucketed by the classic 5R decision question instead of by
biological domain:

  * right_target  — is there a genetic/molecular reason this target matters?      (dependency, genomic_alteration)
  * right_tissue   — is the target actually present/selective in this indication?  (tumor_presence, tumor_selectivity)
  * right_safety   — is targeting it likely safe?                                  (on_target_safety,)
  * right_patient  — can the right patients be selected?                          (genomic_alteration, tumor_selectivity)
  * right_drug     — is there a tractable modality path?                          (tractability, surface_modality)

Each dimension's ``state`` is a deterministic function of its PRIMARY assessed domain's L3d ``coherence``
(the same ``coherence -> state`` map ``facet_thesis_archetype`` uses, duplicated here per the
module-independence convention #2006/#2007/#2008 already establish) when at least one relevant domain is
assessed, else ``NOT_ASSESSED`` — absence outranks measurement, never guessed. This builder does NOT
receive the other facets' already-built output (the assembler calls every ``build(ctx)`` with only ``ctx``
— see ``assembler.FACET_BUILDERS``); it re-derives its own read directly from ``ctx.l3d_domains``, which is
the SAME source every sibling facet reads, so the "view over the one synthesis" framing holds at the level
of the shared evidence substrate, not a literal second-order read of sibling facet dicts.

Uniform facet-builder contract: ``build(ctx) -> Optional[dict]``. See schema.py / assembler.FACET_BUILDERS.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.l4_synthesis import schema as S
from _skills_common.l4_synthesis.context import L4Context

BUILT = True

RIGHT_TARGET = "right_target"
RIGHT_TISSUE = "right_tissue"
RIGHT_SAFETY = "right_safety"
RIGHT_PATIENT = "right_patient"
RIGHT_DRUG = "right_drug"
DIMENSIONS = (RIGHT_TARGET, RIGHT_TISSUE, RIGHT_SAFETY, RIGHT_PATIENT, RIGHT_DRUG)

# Fixed, documented 5R -> KNOWN_DOMAINS relevance map (see module docstring for the rationale of each).
_DIMENSION_RELEVANT_DOMAINS = {
    RIGHT_TARGET: ("dependency", "genomic_alteration"),
    RIGHT_TISSUE: ("tumor_presence", "tumor_selectivity"),
    RIGHT_SAFETY: ("on_target_safety",),
    RIGHT_PATIENT: ("genomic_alteration", "tumor_selectivity"),
    RIGHT_DRUG: ("tractability", "surface_modality"),
}

# Deterministic map: an L3d within-domain coherence class -> a 5R dimension STATE. Duplicated from
# ``facet_thesis_archetype._COHERENCE_TO_STATE`` (module-independence convention — a later child that
# reconciles multiple domains per dimension extends only here, collision-free).
_COHERENCE_TO_STATE = {
    "cross_source_corroborated": "supported",
    "cross_source_corroborated_boundary_sensitive": "supported_with_caveats",
    "cross_source_discordant": "contested",
    "single_source_read": "limited_evidence",
    "peripheral_islands_only": "partial",
    "central_node_unclassified": "partial",
    "no_resolved_island": "insufficient",
}


def _story_refs(story) -> list:
    refs: list = []
    prov = story.get("provenance") if isinstance(story, dict) else None
    for pc in (prov.get("claim_ids") if isinstance(prov, dict) else None) or []:
        if isinstance(pc, dict) and pc.get("claim_id"):
            refs.append(S.claim_ref(pc["claim_id"], vector=pc.get("vector")))
    return refs


def build(ctx: L4Context) -> Optional[dict]:
    if not ctx.l3d_domains:
        return None  # nothing assessed anywhere -> nothing to view by 5R (byte-stable omission)

    presence_refs: list = []
    for name in ctx.assessed_domains:
        presence_refs.extend(_story_refs(ctx.l3d_domains[name]))
        presence_refs.append(S.claim_ref(f"l3d::{name}", domain=name))
    if not presence_refs:
        return None  # a resolved domain that cites nothing gives us nothing traceable to fall back on

    dimensions: dict = {}
    statements: list = []
    for dim in DIMENSIONS:
        relevant = _DIMENSION_RELEVANT_DOMAINS[dim]
        assessed = [d for d in relevant if d in ctx.l3d_domains]
        unassessed = [d for d in relevant if d not in ctx.l3d_domains]

        if assessed:
            primary_name = assessed[0]
            primary = ctx.l3d_domains[primary_name]
            coherence = primary.get("coherence")
            state = _COHERENCE_TO_STATE.get(coherence, "partial")
            refs = _story_refs(primary) or [S.claim_ref(f"l3d::{primary_name}", domain=primary_name)]
            basis = f"read from {primary_name} (coherence={coherence})"
        else:
            state = "NOT_ASSESSED"
            refs = list(presence_refs)
            basis = f"none of [{', '.join(relevant)}] are assessed in this envelope"

        dimensions[dim] = {
            "dimension": dim,
            "state": state,
            "assessed_domains": assessed,
            "unassessed_domains": unassessed,
            "basis": basis,
            "claim_ids": refs,
        }
        statements.append(S.statement(f"{dim}: {state} ({basis})", refs))

    return {
        "facet": S.FACET_DECISION_DIMENSIONS,
        "layer": S.L4_LAYER,
        "built_by": "C0e #2008",
        "decision_dimensions": dimensions,
        "statements": statements,
        "integration_method": S.INTEGRATION_METHOD,
        "_disclaimer": (
            "L4 decision_dimensions / 5R (C0e #2008) — DETERMINISTIC facet assembly reorganizing the "
            "assessed L3d domain evidence into the right_target/right_tissue/right_safety/right_patient/"
            "right_drug VIEW, verdict-INERT (reads no verdict, feeds no rule/veto/resolver, moves no "
            "emitted field), no new measurement, no LLM authorship, NOT a scalar N/5 score. A dimension "
            "with no relevant domain assessed reads NOT_ASSESSED, never guessed. Every statement drills "
            "back to the cited L2/L3 claim IDs."
        ),
    }
