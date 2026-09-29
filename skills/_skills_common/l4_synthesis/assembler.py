"""l4_synthesis.assembler — the L4 target-synthesis SKELETON (epic #1986, C0a #1995).

Reads L3d/L3f + selected L2 claims from an emitted decision / evidence package, dispatches to ONE facet
builder MODULE per facet, and assembles the ``target_synthesis`` facet object. Load-bearing invariants:

  * PURE READ-OVER — it never mutates the object it reads. It emits a NEW synthesis object, not an
    existing field, so the decision/envelope goldens are byte-unchanged (verdict-inert; the flat verdict
    dictates nothing). It is NOT wired into envelope emission in C0a — that (and the
    ``reference_emitted_layers`` registration + schema declaration) is deferred to the wiring child C1
    (#1996), per the SK#1941 L3d precedent.
  * ONE MODULE PER FACET BUILDER — ``FACET_BUILDERS`` is the collision-free fan-out registry. C0b–C0f
    each own exactly one module below; a child implements ``build`` + flips ``BUILT`` in ITS module with
    no edit to this registry or the schema, so the children never touch the same lines.
  * CLAIM-ID TRACEABILITY — every emitted statement must cite claim refs that drill back into the
    envelope; the assembler validates this and RAISES ``L4TraceabilityError`` otherwise (the mutation
    teeth: break a cited claim_id and the assemble red-fails).
"""

from __future__ import annotations

from typing import Mapping, Optional

from _skills_common.l4_synthesis import (
    facet_critical_unknowns,
    facet_decision_dimensions,
    facet_decision_state,
    facet_liabilities_contradictions,
    facet_modality_implications,
    facet_next_evidence,
    facet_opportunity_drivers,
    facet_thesis_archetype,
)
from _skills_common.l4_synthesis import schema as S
from _skills_common.l4_synthesis.context import L4Context, read_context, resolve_ref


class L4TraceabilityError(ValueError):
    """Raised when an emitted L4 statement cites a claim ID that does not drill back into the envelope."""


# ── the facet-builder registry (ONE module per builder — the module boundary is a C0a deliverable) ──
# thesis_archetype is BUILT (C0a #1995); the rest are declared stubs (return None -> facet omitted) that
# C0b–C0f flip on in their own module.
FACET_BUILDERS = (
    (S.FACET_THESIS_ARCHETYPE, facet_thesis_archetype),
    (S.FACET_OPPORTUNITY_DRIVERS, facet_opportunity_drivers),
    (S.FACET_LIABILITIES_CONTRADICTIONS, facet_liabilities_contradictions),
    (S.FACET_CRITICAL_UNKNOWNS, facet_critical_unknowns),
    (S.FACET_MODALITY_IMPLICATIONS, facet_modality_implications),
    (S.FACET_NEXT_EVIDENCE, facet_next_evidence),
    (S.FACET_DECISION_DIMENSIONS, facet_decision_dimensions),
    (S.FACET_DECISION_STATE, facet_decision_state),
)


def unresolved_refs(ctx: L4Context, synthesis: Mapping) -> list:
    """Every emitted statement's claim refs that do NOT drill back into the envelope (empty == fully
    traceable). A statement with no refs is itself a violation (nothing to reconstruct)."""
    bad: list = []
    for fname, fr in (synthesis.get("facets") or {}).items():
        if not isinstance(fr, Mapping):
            continue
        for st in S.iter_statements(fr):
            refs = st.get("claim_ids") or []
            if not refs:
                bad.append({"facet": fname, "text": st.get("text"), "reason": "no_claim_ids"})
                continue
            for ref in refs:
                if not resolve_ref(ctx, ref):
                    bad.append({"facet": fname, "text": st.get("text"), "ref": ref, "reason": "unresolvable"})
    return bad


def _all_refs(facets: Mapping) -> list:
    """De-duplicated union of every claim ref cited across all facets (the synthesis-level provenance)."""
    seen: set = set()
    out: list = []
    for fr in facets.values():
        if not isinstance(fr, Mapping):
            continue
        for st in S.iter_statements(fr):
            for ref in st.get("claim_ids") or []:
                key = (ref.get("claim_id"), ref.get("vector"), ref.get("domain"), ref.get("frame"))
                if key not in seen:
                    seen.add(key)
                    out.append(dict(ref))
    return out


def assemble_target_synthesis(
    decision: Mapping,
    *,
    stage: Optional[str] = None,
    target: Optional[str] = None,
    indication: Optional[str] = None,
    validate: bool = True,
) -> Optional[dict]:
    """Assemble the L4 target-synthesis facet object over an emitted decision / evidence package.

    Returns None (byte-stable omission) when no facet resolves. Never mutates ``decision``. When
    ``validate`` (default), raises ``L4TraceabilityError`` if any emitted statement is untraceable.
    """
    ctx = read_context(decision, stage=stage, target=target, indication=indication)

    facets: dict = {}
    for name, module in FACET_BUILDERS:
        fr = module.build(ctx)  # stubs return None
        if fr is not None:
            facets[name] = fr

    if not facets:
        return None  # nothing built/resolved -> no synthesis -> omitted (byte-stable)

    ta = facets.get(S.FACET_THESIS_ARCHETYPE) or {}
    ds = facets.get(S.FACET_DECISION_STATE) or {}
    synthesis = {
        "layer": S.L4_LAYER,
        "claim_type": S.L4_CLAIM_TYPE,
        "target": ctx.target,
        "indication": ctx.indication,
        # thesis + archetype promoted to the top level per the L4 object shape (docs §"L4 object").
        "archetype": ta.get("archetype"),
        "thesis": ta.get("thesis"),
        "assessed_domains": ctx.assessed_domains,
        "unassessed_domains": [d for d in S.KNOWN_DOMAINS if d not in ctx.l3d_domains],
        # every facet the fan-out has built rides under `facets` (a child adds ONE key here).
        "facets": facets,
        # L4b decision state — the tip of the iceberg only (present when the C0-child builder resolves it).
        "decision_state": ds.get("decision_state"),
        "stage": stage,
        "integration_method": S.INTEGRATION_METHOD,
        "provenance": {
            "claim_ids": _all_refs(facets),
            "reconstructable": (
                "each ref indexes back into the named claim vector (L2b island / L2a source property), "
                "L3d domain story, or L3f frame the emitted package already carries; the L4 synthesis "
                "asserts nothing the L2/L3 claims do not already carry"
            ),
        },
        "_disclaimer": (
            "L4 target synthesis (epic #1986, C0a #1995) — DETERMINISTIC facet assembly, verdict-INERT "
            "(reads no verdict, feeds no rule/veto/resolver rung, moves NO emitted field), no new "
            "measurement, no LLM authorship. A decision-facing VIEW over the L2b/L3d/L3f evidence; "
            "every statement drills back to the cited claim IDs."
        ),
    }

    if validate:
        bad = unresolved_refs(ctx, synthesis)
        if bad:
            raise L4TraceabilityError(
                f"{len(bad)} L4 statement(s) cite claim IDs that do not resolve into the envelope: {bad[:3]}"
            )
    return synthesis
