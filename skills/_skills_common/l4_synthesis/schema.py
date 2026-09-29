"""l4_synthesis.schema — the L4 target-synthesis FACET-OBJECT schema (epic #1986, C0a #1995).

L4 is the decision-facing synthesis layer that integrates domain interpretations (L3d) and decision
frames (L3f) into a coherent target/program story (see
``docs/EVIDENCE_PROPERTY_ARCHITECTURE_L1_L4.md`` §"L4 — integrated synthesis"). It is:

  * DETERMINISTIC — a facet-based VIEW/synthesis assembled by template/traversal over the ALREADY-computed
    L2b/L3d/L3f evidence. NO LLM authorship of this layer (the opt-in ``--synthesize`` narration is a
    separate view that sits ABOVE it).
  * VERDICT-INERT — it reads no verdict, feeds no rule / veto / resolver rung, and moves NO existing
    emitted field. It is a NEW read-over object; it never mutates the decision/envelope it reads.
  * NO NEW MEASUREMENTS — it resolves nothing itself; it re-packages what L2/L3 already carry.
  * RECONSTRUCTABLE DOWNWARD — every emitted L4 statement cites the L2/L3 claim IDs it rests on, so a
    consumer drills straight back: L4 statement -> claim ref -> claim vector island (L2b) / L3d story /
    L3f frame -> L1 measurements. The assembler validates this (see ``assembler.unresolved_refs``).

The object is organized as FACETS (thesis · archetype · opportunity_drivers · liabilities vs
contradictions · critical_unknowns · modality_implications · next_evidence · decision_dimensions[5R] ·
decision_state), NOT hard-coded around 5R or modality — so one synthesis object renders many decision
views. C0a (#1995) lands the schema + the assembler skeleton + the thesis+archetype facet for ONE
flagship; the remaining facets are declared stubs (ONE module file each) that C0b–C0f flip on
collision-free.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence

# Read-only: the L4 layer already exists in the claim-type ladder (ClaimType.SYNTHESIS at layer 4, above
# DECISION_FRAME). We import it so the L4 object tags its layer consistently WITHOUT modifying
# evidence_frame (C0a is additive-only; envelope-emission wiring + reference_emitted_layers registration
# are deferred to the wiring child C1 #1996, per the SK#1941 L3d precedent).
from _skills_common.evidence_frame import CLAIM_TYPE_LAYER, ClaimType

L4_LAYER = "L4"
L4_CLAIM_TYPE = ClaimType.SYNTHESIS  # "synthesis"
L4_LAYER_ORDINAL = CLAIM_TYPE_LAYER[ClaimType.SYNTHESIS]  # 4

INTEGRATION_METHOD = "deterministic_facet_assembly"

# ── target archetype vocabulary ─────────────────────────────────────────────────────────────────────
# A DEFINITIVE archetype names WHAT KIND of opportunity a target is (docs §"Not a single target score").
# It is inherently a CROSS-DOMAIN classification. When the assessed evidence cannot support a cross-domain
# classification, the honest token is ARCHETYPE_UNDETERMINED — never guessed, never laundered from a
# single domain (that would violate the L3d governance rule and "missing != negative").
ARCHETYPE_UNDETERMINED = "undetermined"
ARCHETYPES = (
    "driver-dependent",
    "lineage-marker",
    "surface-antigen-opportunity",
    "synthetic-lethal",
    "biomarker-defined",
    "pathway-node",
    "immune-context",
)
ALL_ARCHETYPES = (ARCHETYPE_UNDETERMINED,) + ARCHETYPES

# ── thesis states (L4a scientific synthesis) ────────────────────────────────────────────────────────
# Deterministic function of the assessed domains' L3d coherence. NOT a verdict token; never fed back into
# any resolver / veto / spine.
THESIS_STATES = (
    "supported",
    "supported_with_caveats",
    "contested",
    "limited_evidence",
    "partial",
    "insufficient",
)

# ── critical-unknown status (a first-class L4 product) ──────────────────────────────────────────────
UNKNOWN_STATUS = ("KNOWN", "UNKNOWN", "CONTRADICTED", "NOT_ASSESSED")

# ── the facets (ONE module file per builder; see assembler.FACET_BUILDERS) ──────────────────────────
FACET_THESIS_ARCHETYPE = "thesis_archetype"
FACET_OPPORTUNITY_DRIVERS = "opportunity_drivers"
FACET_LIABILITIES_CONTRADICTIONS = "liabilities_contradictions"
FACET_CRITICAL_UNKNOWNS = "critical_unknowns"
FACET_MODALITY_IMPLICATIONS = "modality_implications"
FACET_NEXT_EVIDENCE = "next_evidence"
FACET_DECISION_DIMENSIONS = "decision_dimensions"  # 5R as facets of the one synthesis (not a system)
FACET_DECISION_STATE = "decision_state"  # L4b — tip of the iceberg only

FACET_NAMES = (
    FACET_THESIS_ARCHETYPE,
    FACET_OPPORTUNITY_DRIVERS,
    FACET_LIABILITIES_CONTRADICTIONS,
    FACET_CRITICAL_UNKNOWNS,
    FACET_MODALITY_IMPLICATIONS,
    FACET_NEXT_EVIDENCE,
    FACET_DECISION_DIMENSIONS,
    FACET_DECISION_STATE,
)

# The evidence domains an L4 synthesis reconciles. tumor_presence is the only vertical exported to L3d
# today; the rest are NOT_ASSESSED until their verticals export an L3d story — honest missingness, never
# read as negative evidence.
KNOWN_DOMAINS = (
    "tumor_presence",
    "dependency",
    "on_target_safety",
    "tumor_selectivity",
    "surface_modality",
    "tractability",
    "genomic_alteration",
)


# ── claim-ref / statement factories (the downward-reconstruction spine) ─────────────────────────────
def claim_ref(
    claim_id: str,
    *,
    vector: Optional[str] = None,
    layer: Optional[str] = None,
    domain: Optional[str] = None,
    frame: Optional[str] = None,
) -> dict:
    """A downward-reconstruction handle, mirroring the L3d provenance shape ``{claim_id, vector}``.

    A ref resolves (see ``context.resolve_ref``) either into a claim VECTOR (an L2b island / L2a source
    property key), or by naming an L3d DOMAIN story / an L3f FRAME object present in the envelope.
    """
    ref: dict = {"claim_id": claim_id}
    if vector is not None:
        ref["vector"] = vector
    if layer is not None:
        ref["layer"] = layer
    if domain is not None:
        ref["domain"] = domain
    if frame is not None:
        ref["frame"] = frame
    return ref


def statement(text: str, refs: Sequence[Mapping]) -> dict:
    """One L4 statement + the claim refs it is reconstructable from.

    Every L4 statement MUST cite at least one resolvable ref — that is the traceability contract; an empty
    ``claim_ids`` is a schema violation the assembler rejects (a statement no consumer can drill back on
    is exactly the "launder judgment into a fact" failure L4 must not do).
    """
    return {"text": text, "claim_ids": [dict(r) for r in refs]}


def iter_statements(facet_result: Mapping):
    """Yield every ``statement`` dict carried by a facet result (its ``statements`` list)."""
    for st in facet_result.get("statements") or []:
        if isinstance(st, Mapping):
            yield st
