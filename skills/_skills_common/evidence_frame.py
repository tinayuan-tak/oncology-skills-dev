"""evidence_frame — L3 bridge: frames over a TYPED EVIDENCE INTERFACE (design "G").

This module implements rung 6 of the promotion ladder in ``docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md``
("Consumed via typed interface — frames read islands as typed inputs (G)"). It is the FIRST place in
the framework where verdict-CONSUMPTION legitimately enters: a decision frame consumes typed evidence
to produce ITS OWN new L3 decision surface. It is purely ADDITIVE — nothing in this module is imported
by any dispatcher, resolver, claim_vector builder, question_table, or skill verdict path, so every
existing replay golden / per-skill verdict stays byte-identical. The frame routes NOTHING back into a
lower layer.

Why a typed interface at all
----------------------------
The envelope doc §"Type-integrity invariant" states a system-wide, machine-checkable rule:

    An evidence object may not be consumed downstream as a STRONGER epistemic type than it was
    emitted as.  (measurement != integrated-property · local-composite != atomic property ·
    unresolved != neutral · dependent evidence != independent corroboration · L3 != L2 fact)

Until now that rule was prose. This module makes it code. A frame declares each of its inputs as one
of four INPUT KINDS, and a checker refuses any declaration that over-claims the object's honest
emitted type.

The four input kinds (how a frame DECLARES it consumes an input)
    canonical-property-claim  — an L2b integrated cross-source property (the *_concordance claims).
    local-composite-claim     — a within-skill composite classifier (bundles measurements; NOT a
                                 canonical single-fact property). This is the type-integrity teeth
                                 specimen: it must be REFUSED where a canonical property is declared.
    measurement               — a single raw observed measurement (atomic observational fact).
    missing/unresolved        — a declared-but-absent input. Never silently neutral.

The claim_type taxonomy (the emitted LAYER of any evidence object) — greenfield here
    observational_property (L2a) < integrated_property (L2b) < decision_frame (L3) < synthesis (L3+)
with ENFORCED ACYCLICITY: a decision/synthesis claim never feeds a lower-layer property input
(``assert_acyclic``), and a real dependency-graph cycle is refused (DFS, not just a scalar compare).

Roles, not weights
    required        — must resolve; unresolved -> the frame cannot decide -> L4 QUESTION (never a kill).
    supportive      — strengthens when present; absence is fine.
    contextual      — annotates only; never gates.
    veto_capable    — a MEASURED-adverse value DOWN-RANKS the decision one notch (never a kill).
    critical_unknown— if UNRESOLVED, routes to an L4 QUESTION (never a kill). "unresolved != neutral."

The reference frame (``REFERENCE_FRAME``): corroborated_dependency_priority
    A NEW additive decision surface — NOT a re-derivation of any existing skill verdict — asking
    "is this a well-corroborated, selectively-expressed genetic dependency worth prioritizing?"
    It exercises all four input kinds and all five roles in ONE frame:
      * essentiality  (crispr_rnai_essentiality_concordance)  canonical-property-claim / required
      * recurrence    (recurrence_concordance)                canonical-property-claim / supportive
      * selectivity   (selectivity_concordance)               canonical-property-claim / veto_capable
      * a raw dependency effect measurement                    measurement              / contextual
      * a within-skill composite selectivity classifier        local-composite-claim    / supportive
      * normal-tissue safety liability (deliberately absent)   missing/unresolved       / critical_unknown
    The absent critical drives the missing/unresolved -> L4 QUESTION path.

A second, PRESENCE-domain frame (``PRESENCE_FRAME``): corroborated_tumor_presence (SK#1842)
    The interface now spans >1 domain. It also DECLARES the four remaining built/surfaced concordance
    families as typed inputs (``SURFACED_CONCORDANCE_PROPERTIES``) — the three presence families as
    canonical property claims on this frame, and normal_liability as the shared absent critical:
      * coverage    (bulk_vs_singlecell_coverage_concordance)  canonical-property-claim / required
      * abundance   (abundance_concordance)                    canonical-property-claim / supportive
      * subtype     (subtype_restriction_concordance)          canonical-property-claim / veto_capable
      * normal-tissue safety liability (deliberately absent)   missing/unresolved       / critical_unknown
    Its production entry ``tumor_presence_frame`` mirrors ``dependency_priority_frame``.

Reach audit
    Frame deps are declared ON the frame; the reverse index (property -> frames) is DERIVED
    (``build_reverse_index``) so the property layer stays decision-agnostic. ``decision_reach_audit``
    is the property->frame ratchet (the EPCAM field-reach bug lifted one level): every declared
    property input must demonstrably reach a frame, and the three rung-4 families in particular must.

corroboration is read (``.get("corroboration")``) only to gauge decision confidence off the
independence-correct tier the envelope already computed — no map, an unrecognised rung reads as
itself. This module is therefore registered PASS-THROUGH in the corroboration-reader classification
(test_claim_ladder_vocabulary_coverage.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence


# --------------------------------------------------------------------------------------------------
# Vocabularies
# --------------------------------------------------------------------------------------------------
class InputKind:
    """How a frame DECLARES it consumes an input (the typed consumption interface)."""

    CANONICAL_PROPERTY_CLAIM = "canonical-property-claim"
    LOCAL_COMPOSITE_CLAIM = "local-composite-claim"
    MEASUREMENT = "measurement"
    MISSING_UNRESOLVED = "missing/unresolved"


_PROPERTY_INPUT_KINDS = frozenset(
    {InputKind.CANONICAL_PROPERTY_CLAIM, InputKind.LOCAL_COMPOSITE_CLAIM, InputKind.MEASUREMENT}
)
_ALL_INPUT_KINDS = _PROPERTY_INPUT_KINDS | {InputKind.MISSING_UNRESOLVED}


class ClaimType:
    """The emitted LAYER of an evidence object (the claim_type taxonomy)."""

    OBSERVATIONAL_PROPERTY = "observational_property"
    INTEGRATED_PROPERTY = "integrated_property"
    DECISION_FRAME = "decision_frame"
    SYNTHESIS = "synthesis"


# UNRESOLVED is not a layer — it is the ABSENCE of a resolved claim, kept distinct so it can never be
# spelled as a neutral/pass value.
UNRESOLVED = "unresolved"

# Strict layer order, low -> high. Used for the acyclicity monotonicity check AND the over-claim rule.
CLAIM_TYPE_LAYER = {
    ClaimType.OBSERVATIONAL_PROPERTY: 0,
    ClaimType.INTEGRATED_PROPERTY: 1,
    ClaimType.DECISION_FRAME: 2,
    ClaimType.SYNTHESIS: 3,
}

# Emitted-type strength rank (adds UNRESOLVED below everything). "Consumed as stronger than emitted"
# means the type a KIND asserts outranks the object's honest emitted type.
_EMITTED_RANK = {
    UNRESOLVED: -1,
    ClaimType.OBSERVATIONAL_PROPERTY: 0,
    ClaimType.INTEGRATED_PROPERTY: 1,
    ClaimType.DECISION_FRAME: 2,
    ClaimType.SYNTHESIS: 3,
}

# The emitted layer each INPUT KIND asserts the object holds. A canonical-property-claim asserts an
# integrated_property; a measurement / local-composite assert the observational layer.
_KIND_ASSERTS_LAYER = {
    InputKind.CANONICAL_PROPERTY_CLAIM: ClaimType.INTEGRATED_PROPERTY,
    InputKind.LOCAL_COMPOSITE_CLAIM: ClaimType.OBSERVATIONAL_PROPERTY,
    InputKind.MEASUREMENT: ClaimType.OBSERVATIONAL_PROPERTY,
}


class Role:
    """Roles, not weights."""

    REQUIRED = "required"
    SUPPORTIVE = "supportive"
    CONTEXTUAL = "contextual"
    VETO_CAPABLE = "veto_capable"
    CRITICAL_UNKNOWN = "critical_unknown"


_VALID_ROLES = frozenset({Role.REQUIRED, Role.SUPPORTIVE, Role.CONTEXTUAL, Role.VETO_CAPABLE, Role.CRITICAL_UNKNOWN})

# Frame decision ladder (frame-native tokens — deliberately NOT any skill verdict vocabulary).
DECISION_PRIORITIZE = "prioritize"
DECISION_PRIORITIZE_RESERVED = "prioritize_with_reservation"
DECISION_HOLD = "hold"
DECISION_QUESTION = "question"
_DECISION_LADDER = (DECISION_PRIORITIZE, DECISION_PRIORITIZE_RESERVED, DECISION_HOLD)

# Corroboration tiers (from claim_vector_core.corroboration_from_arms) that signal a WEAK measured
# basis for a required property -> a reservation. An unrecognised tier is not a member (reads as
# itself; honest), so a newly-minted rung never silently degrades the decision.
_WEAK_CORROBORATION = frozenset({"single_arm", "low"})


class TypeIntegrityError(Exception):
    """Raised when an evidence object would be consumed as a stronger epistemic type than emitted."""


class FrameCycleError(Exception):
    """Raised when the declared frame/property dependency graph is not acyclic."""


# --------------------------------------------------------------------------------------------------
# Typed evidence object
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TypedEvidence:
    """A single evidence object, carrying its HONEST emitted type. The frame never mutates it.

    ``claim_type`` is the emitted layer; ``resolved`` False means the object carries no trusted call
    (its emitted type collapses to UNRESOLVED, whatever layer it would occupy resolved). ``is_composite``
    marks a within-skill composite classifier (an observational-layer bundle that is NOT an atomic
    single-fact property). ``state`` is the class token (e.g. concordance_class); ``adverse`` is
    computed against the consuming frame's declared adverse set.
    """

    property_id: str
    claim_type: str
    resolved: bool
    is_composite: bool = False
    state: Optional[str] = None
    corroboration: Optional[str] = None
    independent_arm_count: Optional[int] = None
    resolved_source_count: Optional[int] = None
    value: object = None
    source: Optional[str] = None

    @property
    def emitted_type(self) -> str:
        """The honest emitted epistemic type: UNRESOLVED when nothing resolved, else the claim layer."""
        return self.claim_type if self.resolved else UNRESOLVED


# --- Adapters: wrap real emitted evidence as typed objects (read-only; source families stay byte-stable) ---
def from_concordance(property_id: str, claim: Optional[Mapping]) -> TypedEvidence:
    """Adapt an L2b ``*_concordance`` envelope claim (or None) into a typed canonical property.

    The envelope signature (``integration_method == 'explicit_deterministic'`` + a ``concordance_class``)
    is what makes it an integrated_property. dependent evidence != independent corroboration is honored
    by reading the independence-correct ``corroboration`` tier and ``corroborating_independent_arm_count``
    (never ``resolved_source_count``, which includes dependent supersets).
    """
    if claim is None:
        return TypedEvidence(property_id=property_id, claim_type=ClaimType.INTEGRATED_PROPERTY, resolved=False)
    if claim.get("integration_method") != "explicit_deterministic" or "concordance_class" not in claim:
        raise TypeIntegrityError(
            f"{property_id}: not an L2b integrated_property envelope claim (no explicit_deterministic "
            "integration_method / concordance_class) — refusing to adapt it as a canonical property."
        )
    return TypedEvidence(
        property_id=property_id,
        claim_type=ClaimType.INTEGRATED_PROPERTY,
        resolved=True,
        is_composite=False,
        state=claim.get("concordance_class"),
        corroboration=claim.get("corroboration"),
        independent_arm_count=claim.get("corroborating_independent_arm_count"),
        resolved_source_count=claim.get("resolved_source_count"),
        value=dict(claim),
    )


def measurement(property_id: str, value, *, source: Optional[str] = None) -> TypedEvidence:
    """A single raw observed measurement (atomic observational fact)."""
    return TypedEvidence(
        property_id=property_id,
        claim_type=ClaimType.OBSERVATIONAL_PROPERTY,
        resolved=value is not None,
        is_composite=False,
        value=value,
        source=source,
    )


def local_composite(
    property_id: str, classifier_token: Optional[str], *, source: Optional[str] = None
) -> TypedEvidence:
    """A within-skill composite classifier — observational layer, but NOT an atomic single-fact property."""
    return TypedEvidence(
        property_id=property_id,
        claim_type=ClaimType.OBSERVATIONAL_PROPERTY,
        resolved=classifier_token is not None,
        is_composite=True,
        state=classifier_token,
        value=classifier_token,
        source=source,
    )


def unresolved(property_id: str) -> TypedEvidence:
    """A declared-but-absent input. Its emitted type is UNRESOLVED — never neutral."""
    return TypedEvidence(property_id=property_id, claim_type=ClaimType.OBSERVATIONAL_PROPERTY, resolved=False)


# --------------------------------------------------------------------------------------------------
# Type-integrity checker (machine-checkable invariant, with teeth)
# --------------------------------------------------------------------------------------------------
def check_input_integrity(kind: str, ev: TypedEvidence) -> None:
    """Refuse consuming ``ev`` under declared ``kind`` if that over-claims its emitted type.

    Enforces, with distinct errors:
      R1 no over-claim   — the layer a KIND asserts may not outrank the object's emitted layer
                           (catches local-composite -> canonical, unresolved -> resolved,
                           measurement -> integrated_property).
      R2 atomicity       — a measurement slot may not receive a composite (local-composite != atomic).
      R3 no L3 into L2   — a decision_frame / synthesis object may not be consumed as a property
                           (L3 interpretation != L2 fact).
      R4 unresolved-kind — a missing/unresolved slot must actually be unresolved.
    """
    if kind not in _ALL_INPUT_KINDS:
        raise TypeIntegrityError(f"unknown input kind {kind!r}")

    if kind == InputKind.MISSING_UNRESOLVED:
        if ev.resolved:  # R4
            raise TypeIntegrityError(
                f"{ev.property_id}: declared missing/unresolved but a resolved {ev.emitted_type} was supplied"
            )
        return

    if ev.emitted_type == UNRESOLVED:
        # Absence under a property kind is NOT an over-claim: nothing is being consumed. The evaluator
        # routes an unresolved required/critical input to an L4 QUESTION (never treats it as neutral) —
        # that routing, not this checker, is where "unresolved != neutral" bites for a property slot.
        return

    # R3: an L3+ object may never enter a property-layer slot (acyclicity at the consumption boundary).
    if ev.emitted_type in (ClaimType.DECISION_FRAME, ClaimType.SYNTHESIS):
        raise TypeIntegrityError(
            f"{ev.property_id}: an {ev.emitted_type} (L3) may not be consumed as a property "
            f"({kind}) — L3 interpretation != L2 fact"
        )

    # R1: the layer the kind asserts must not outrank the emitted layer.
    asserted = _KIND_ASSERTS_LAYER[kind]
    if _EMITTED_RANK[asserted] > _EMITTED_RANK[ev.emitted_type]:
        raise TypeIntegrityError(
            f"{ev.property_id}: consumed as {kind} (asserts {asserted}) but emitted only "
            f"{ev.emitted_type} — may not be consumed as a stronger epistemic type than emitted"
        )

    # R2: a canonical/atomic-measurement slot may not receive a composite classifier.
    if ev.is_composite and kind in (InputKind.CANONICAL_PROPERTY_CLAIM, InputKind.MEASUREMENT):
        raise TypeIntegrityError(
            f"{ev.property_id}: a local-composite classifier may not be consumed as {kind} "
            "— local-composite != atomic/canonical property"
        )


# --------------------------------------------------------------------------------------------------
# Frame declaration
# --------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FrameInput:
    property_id: str
    kind: str
    role: str
    positive_states: frozenset = frozenset()
    adverse_states: frozenset = frozenset()

    def __post_init__(self):
        if self.kind not in _ALL_INPUT_KINDS:
            raise ValueError(f"{self.property_id}: unknown input kind {self.kind!r}")
        if self.role not in _VALID_ROLES:
            raise ValueError(f"{self.property_id}: unknown role {self.role!r}")


@dataclass(frozen=True)
class Frame:
    frame_id: str
    inputs: tuple
    claim_type: str = ClaimType.DECISION_FRAME

    def declared_property_ids(self) -> tuple:
        return tuple(i.property_id for i in self.inputs)


# --------------------------------------------------------------------------------------------------
# Acyclicity (real DFS + layer monotonicity)
# --------------------------------------------------------------------------------------------------
def assert_acyclic(frames: Sequence[Frame], emitted_layer: Mapping[str, str]) -> None:
    """Refuse a frame graph that is not a DAG, or that lets a claim feed a same/higher-layer input.

    ``emitted_layer`` maps every property_id / frame_id that appears to its emitted ClaimType. A frame
    node's layer is its own ``claim_type``. Two guards:
      * MONOTONICITY — every input must sit STRICTLY below its consuming frame's layer, so a
        decision/synthesis claim can never feed a lower-layer property (the acyclicity invariant).
      * CYCLE — a real depth-first search over frame -> input edges (a frame may declare another frame
        as an input once synthesis frames exist) refuses any back-edge.
    """
    frame_layer = {f.frame_id: CLAIM_TYPE_LAYER[f.claim_type] for f in frames}

    # Monotonicity.
    for f in frames:
        consumer = frame_layer[f.frame_id]
        for inp in f.inputs:
            src_type = emitted_layer.get(inp.property_id)
            if src_type is None:
                raise FrameCycleError(f"{f.frame_id}: input {inp.property_id} has no declared emitted layer")
            if CLAIM_TYPE_LAYER[src_type] >= consumer:
                raise FrameCycleError(
                    f"{f.frame_id} ({f.claim_type}) may not consume {inp.property_id} ({src_type}): "
                    "a claim may only feed a STRICTLY higher layer (decision claims never feed lower-layer "
                    "properties)"
                )

    # Cycle detection over the directed graph consumer -> input (edges land only on frame nodes that
    # are themselves declared as inputs elsewhere; property leaves have no out-edges).
    adjacency: dict[str, list[str]] = {f.frame_id: [i.property_id for i in f.inputs] for f in frames}
    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def visit(node: str, stack: tuple) -> None:
        color[node] = GREY
        for nxt in adjacency.get(node, ()):  # a property leaf isn't a key -> no out-edges
            if color.get(nxt, WHITE) == GREY:
                raise FrameCycleError(f"dependency cycle: {' -> '.join(stack + (node, nxt))}")
            if color.get(nxt, WHITE) == WHITE:
                visit(nxt, stack + (node,))
        color[node] = BLACK

    for f in frames:
        if color.get(f.frame_id, WHITE) == WHITE:
            visit(f.frame_id, ())


# --------------------------------------------------------------------------------------------------
# Reverse index + property->frame decision-reach audit
# --------------------------------------------------------------------------------------------------
def build_reverse_index(frames: Sequence[Frame]) -> dict:
    """DERIVE {property_id: [frame_id, ...]} from the deps declared ON each frame.

    The forward declaration lives on the frame; this reverse view is never authored — so the property
    layer stays decision-agnostic (a property does not know which frames read it).
    """
    index: dict[str, list[str]] = {}
    for f in frames:
        for pid in f.declared_property_ids():
            index.setdefault(pid, [])
            if f.frame_id not in index[pid]:
                index[pid].append(f.frame_id)
    return index


def decision_reach_audit(frames: Sequence[Frame], must_reach: Sequence[str]) -> dict:
    """The property->frame reach ratchet (the field-reach bug, lifted one level).

    Every property in ``must_reach`` must be declared by >=1 frame; ``unreached`` names any that are
    not. A declared frame input that references a property NOT in ``must_reach`` is still valid (a frame
    may read more than the audited set), but a ``must_reach`` property that reaches NO frame is a hole.
    """
    reverse = build_reverse_index(frames)
    reached = {pid: reverse[pid] for pid in must_reach if reverse.get(pid)}
    unreached = sorted(pid for pid in must_reach if not reverse.get(pid))
    return {"reached": reached, "unreached": unreached, "reverse_index": reverse}


# --------------------------------------------------------------------------------------------------
# Frame evaluation
# --------------------------------------------------------------------------------------------------
def _downrank(decision: str) -> str:
    i = _DECISION_LADDER.index(decision)
    return _DECISION_LADDER[min(i + 1, len(_DECISION_LADDER) - 1)]


def evaluate_frame(frame: Frame, bundle: Mapping[str, TypedEvidence]) -> dict:
    """Evaluate ``frame`` over a bundle of typed evidence, producing its OWN L3 decision object.

    Every input is type-integrity checked first (a real over-claim raises; normal operation passes).
    Routing:
      * a critical_unknown or required input that is UNRESOLVED -> DECISION_QUESTION (an L4 question),
        never a kill.
      * else the base decision is PRIORITIZE, dropped to HOLD if a required property resolved to a
        non-positive state; a veto_capable MEASURED-adverse input DOWN-RANKS one notch; a weak
        corroboration tier on a required property adds a reservation (down-rank one notch).
    Nothing here is written back into any skill verdict / claim_vector / resolver.
    """
    rationale: list[str] = []
    resolved_inputs: dict[str, object] = {}
    unresolved_critical: list[str] = []
    unresolved_required: list[str] = []
    vetoes_applied: list[str] = []
    reservations: list[str] = []

    for inp in frame.inputs:
        ev = bundle.get(inp.property_id) or unresolved(inp.property_id)
        check_input_integrity(inp.kind, ev)

        if not ev.resolved:
            if inp.role == Role.CRITICAL_UNKNOWN:
                unresolved_critical.append(inp.property_id)
            elif inp.role == Role.REQUIRED:
                unresolved_required.append(inp.property_id)
            continue

        resolved_inputs[inp.property_id] = ev.state if ev.state is not None else ev.value

        if inp.role == Role.REQUIRED:
            if inp.positive_states and ev.state not in inp.positive_states:
                rationale.append(f"required {inp.property_id} resolved non-positive ({ev.state}) -> hold")
            else:
                rationale.append(f"required {inp.property_id} positive ({ev.state})")
            if ev.corroboration in _WEAK_CORROBORATION:
                reservations.append(f"{inp.property_id} corroboration {ev.corroboration}")
        elif inp.role == Role.SUPPORTIVE:
            if not inp.positive_states or ev.state in inp.positive_states:
                rationale.append(f"supportive {inp.property_id} ({ev.state or ev.value})")
        elif inp.role == Role.VETO_CAPABLE:
            if ev.state in inp.adverse_states:
                vetoes_applied.append(f"{inp.property_id} measured-adverse ({ev.state})")
        elif inp.role == Role.CONTEXTUAL:
            rationale.append(f"context {inp.property_id}={ev.value}")

    # Unresolved critical / required -> L4 QUESTION (never a kill).
    if unresolved_critical or unresolved_required:
        question = (
            "cannot decide "
            f"{frame.frame_id}: unresolved "
            + ", ".join(f"{p} (critical)" for p in unresolved_critical)
            + ("; " if unresolved_critical and unresolved_required else "")
            + ", ".join(f"{p} (required)" for p in unresolved_required)
        )
        return _frame_result(
            frame,
            DECISION_QUESTION,
            rationale,
            resolved_inputs,
            unresolved_critical,
            unresolved_required,
            vetoes_applied,
            reservations,
            l4_question=question,
        )

    # Base decision, then measured down-ranking.
    decision = DECISION_PRIORITIZE
    for inp in frame.inputs:
        if inp.role == Role.REQUIRED:
            ev = bundle.get(inp.property_id)
            if ev and inp.positive_states and ev.state not in inp.positive_states:
                decision = DECISION_HOLD
    for _ in vetoes_applied:
        decision = _downrank(decision)
    for _ in reservations:
        decision = _downrank(decision)

    return _frame_result(
        frame,
        decision,
        rationale,
        resolved_inputs,
        unresolved_critical,
        unresolved_required,
        vetoes_applied,
        reservations,
        l4_question=None,
    )


def _frame_result(
    frame,
    decision,
    rationale,
    resolved_inputs,
    unresolved_critical,
    unresolved_required,
    vetoes_applied,
    reservations,
    *,
    l4_question,
) -> dict:
    out = {
        "claim_type": frame.claim_type,
        "frame_id": frame.frame_id,
        "decision": decision,
        "rationale": rationale,
        "resolved_inputs": resolved_inputs,
        "unresolved_critical": unresolved_critical,
        "unresolved_required": unresolved_required,
        "vetoes_applied": vetoes_applied,
        "reservations": reservations,
        "integration_method": "explicit_deterministic",
        "_disclaimer": (
            "L3 DECISION FRAME (design G, typed evidence interface) — ADDITIVE: consumes typed evidence "
            "to produce its OWN decision surface; routes NOTHING back into any skill verdict, claim_vector, "
            "question_table, or resolver. Not a re-derivation of any existing skill verdict."
        ),
    }
    if l4_question is not None:
        out["l4_question"] = l4_question
    return out


# --------------------------------------------------------------------------------------------------
# L4 forward-question projector (G3.3) — shared over the typed interface
# --------------------------------------------------------------------------------------------------
def forward_question_from_frame(frame_result: Mapping) -> Optional[dict]:
    """Render a frame's CRITICAL_UNKNOWN role (an unresolved-critical typed input) as an L4 FORWARD
    QUESTION on the relevant skill's answer surface — never a kill. Returns None when the frame did not
    route to a question (no ``l4_question`` on the result).

    This is the SHARED G3.3 projector over the typed interface (epic #1749 Milestone-2). It generalizes
    the CRITICAL_UNKNOWN -> forward-question rendering that #1841 (dependency Q4) and #1842 (presence Q7)
    each hand-rolled, so every production frame routes through ONE projector rather than each diverging.
    It emits one forward-question per frame that routed to a question, and extends cleanly as Draft-2
    adds frames: the ``provenance_ref`` is DERIVED from the frame's own ``frame_id`` (``evidence_frame.
    <frame_id>``), so no per-domain rendering code is needed. Per roles-not-weights, an unresolved
    CRITICAL_UNKNOWN routes to a QUESTION (never a kill); a MEASURED-adverse veto DOWN-RANKS instead
    (handled in ``evaluate_frame``). The forward-question is an ADDITIVE answer, verdict-INERT — never a
    verdict input; it routes nothing back into any skill verdict, claim_vector, question_table meter
    cell, or resolver.
    """
    q = frame_result.get("l4_question")
    if not q:
        return None
    return {
        "kind": "l4_forward_question",
        "role": "critical_unknown",
        "question": q,
        "unresolved_critical": frame_result.get("unresolved_critical"),
        "unresolved_required": frame_result.get("unresolved_required"),
        "provenance_ref": f"evidence_frame.{frame_result.get('frame_id')}",
        "_disclaimer": (
            "L4 FORWARD QUESTION (design G, roles-not-weights): an unresolved CRITICAL_UNKNOWN routes to a "
            "QUESTION, never a kill; verdict-INERT — routes nothing back into any verdict / claim_vector / "
            "resolver."
        ),
    }


# --------------------------------------------------------------------------------------------------
# The FIRST reference frame + registry
# --------------------------------------------------------------------------------------------------
ESSENTIALITY_PROPERTY = "crispr_rnai_essentiality_concordance"
RECURRENCE_PROPERTY = "recurrence_concordance"
SELECTIVITY_PROPERTY = "selectivity_concordance"
DEPENDENCY_EFFECT_MEASUREMENT = "dependency_effect_size"
COMPOSITE_SELECTIVITY_CLASS = "composite_selectivity_class"
# The name safety_claims.py actually EMITS onto the safety claim_vector (`_normal_liability_concordance_claim`).
# Reconciled from the earlier `normal_tissue_liability_concordance` (SK#1841 precondition) so the input is
# WIREABLE by name — the reference frame still holds it as the deliberately-ABSENT critical_unknown specimen
# (a functional-requirement surface never carries a safety claim), so this is name-correctness, not presence.
NORMAL_LIABILITY_PROPERTY = "normal_liability_concordance"

# ── The four remaining built/surfaced concordance families (SK#1842, epic #1749 Milestone-2) ────────
# Until now the typed interface referenced only the three rung-4 families above (as canonical property
# claims on the REFERENCE_FRAME) — the other four surfaced/built L2b `*_concordance` families were not
# reachable by the interface at all. These are their EMITTED keys (the presence trio is emitted onto the
# tumor-presence claim vector / by-subtype vector; normal_liability onto the safety vector) so a frame can
# consume them BY NAME. Each is an L2b integrated_property (`integration_method == explicit_deterministic`
# + a `concordance_class`), so a frame declares each as a CANONICAL_PROPERTY_CLAIM where it consumes its
# resolved value, or (for a surface that structurally never carries it) as MISSING_UNRESOLVED.
COVERAGE_CONCORDANCE_PROPERTY = "bulk_vs_singlecell_coverage_concordance"
ABUNDANCE_CONCORDANCE_PROPERTY = "abundance_concordance"
SUBTYPE_RESTRICTION_PROPERTY = "subtype_restriction_concordance"

# The three rung-4 canonical property families this L3 bridge must demonstrably reach.
RUNG4_CANONICAL_PROPERTIES = (ESSENTIALITY_PROPERTY, RECURRENCE_PROPERTY, SELECTIVITY_PROPERTY)

# The four remaining built/surfaced concordance families the interface now declares as typed inputs
# (SK#1842). Every member must demonstrably reach a frame (the decision-reach ratchet, lifted to the
# surfaced set): the presence trio reaches PRESENCE_FRAME as canonical property claims, normal_liability
# reaches BOTH frames as the deliberately-absent critical_unknown specimen.
SURFACED_CONCORDANCE_PROPERTIES = (
    COVERAGE_CONCORDANCE_PROPERTY,
    ABUNDANCE_CONCORDANCE_PROPERTY,
    SUBTYPE_RESTRICTION_PROPERTY,
    NORMAL_LIABILITY_PROPERTY,
)

# The presence frame's declared CANONICAL_PROPERTY_CLAIM inputs — the field-reach ratchet lifted to the
# frame layer (SK#1856, standing guard, child of #1848). Mirrors RUNG4_CANONICAL_PROPERTIES for the
# reference frame: the three cross-source presence concordance families PRESENCE_FRAME consumes as
# canonical property claims (coverage / abundance / subtype_restriction — normal_liability is the
# deliberately-absent MISSING_UNRESOLVED critical, NOT a canonical property claim, so it is excluded).
# Every member must demonstrably reach a frame in FRAME_REGISTRY via decision_reach_audit; a canonical
# property the presence frame declares but that reaches NO frame is a hole that fails loudly.
PRESENCE_FRAME_CANONICAL_PROPERTIES = (
    COVERAGE_CONCORDANCE_PROPERTY,
    ABUNDANCE_CONCORDANCE_PROPERTY,
    SUBTYPE_RESTRICTION_PROPERTY,
)

REFERENCE_FRAME = Frame(
    frame_id="corroborated_dependency_priority",
    inputs=(
        FrameInput(
            property_id=ESSENTIALITY_PROPERTY,
            kind=InputKind.CANONICAL_PROPERTY_CLAIM,
            role=Role.REQUIRED,
            positive_states=frozenset({"essentiality_concordant_dependent"}),
        ),
        FrameInput(
            property_id=RECURRENCE_PROPERTY,
            kind=InputKind.CANONICAL_PROPERTY_CLAIM,
            role=Role.SUPPORTIVE,
            positive_states=frozenset({"recurrence_concordant"}),
        ),
        FrameInput(
            property_id=SELECTIVITY_PROPERTY,
            kind=InputKind.CANONICAL_PROPERTY_CLAIM,
            role=Role.VETO_CAPABLE,
            adverse_states=frozenset({"protein_masks_selectivity_window", "rna_masks_selectivity_window"}),
        ),
        FrameInput(
            property_id=DEPENDENCY_EFFECT_MEASUREMENT,
            kind=InputKind.MEASUREMENT,
            role=Role.CONTEXTUAL,
        ),
        FrameInput(
            property_id=COMPOSITE_SELECTIVITY_CLASS,
            kind=InputKind.LOCAL_COMPOSITE_CLAIM,
            role=Role.SUPPORTIVE,
        ),
        FrameInput(
            property_id=NORMAL_LIABILITY_PROPERTY,
            kind=InputKind.MISSING_UNRESOLVED,
            role=Role.CRITICAL_UNKNOWN,
        ),
    ),
)

# --------------------------------------------------------------------------------------------------
# Second reference frame — a PRESENCE-domain decision frame over the typed interface (SK#1842)
# --------------------------------------------------------------------------------------------------
# The SECOND domain the L3 typed-evidence interface reaches (epic #1749 Milestone-2): a NEW additive
# presence-priority decision surface — NOT a re-derivation of the tumor-presence verdict — asking "is this
# a well-corroborated, cross-source-consistent tumor-presence signal worth prioritizing?". It exercises the
# three surfaced PRESENCE concordance families as canonical property claims plus the safety critical:
#   * coverage    (bulk_vs_singlecell_coverage_concordance)  canonical-property-claim / required
#   * abundance   (abundance_concordance)                     canonical-property-claim / supportive
#   * subtype     (subtype_restriction_concordance)           canonical-property-claim / veto_capable
#     (a MEASURED cross-modality restriction MASK — protein/rna_masks_subtype_restriction — down-ranks one
#      notch, never a kill)
#   * normal-tissue safety liability (deliberately absent)    missing/unresolved       / critical_unknown
# The presence surface never carries the safety claim, so the unresolved critical routes the frame to an
# L4 QUESTION (never a kill) — the same roles-not-weights forward-question path as the reference frame.
PRESENCE_FRAME = Frame(
    frame_id="corroborated_tumor_presence",
    inputs=(
        FrameInput(
            property_id=COVERAGE_CONCORDANCE_PROPERTY,
            kind=InputKind.CANONICAL_PROPERTY_CLAIM,
            role=Role.REQUIRED,
            positive_states=frozenset({"coverage_concordant"}),
        ),
        FrameInput(
            property_id=ABUNDANCE_CONCORDANCE_PROPERTY,
            kind=InputKind.CANONICAL_PROPERTY_CLAIM,
            role=Role.SUPPORTIVE,
            positive_states=frozenset({"abundance_concordant"}),
        ),
        FrameInput(
            property_id=SUBTYPE_RESTRICTION_PROPERTY,
            kind=InputKind.CANONICAL_PROPERTY_CLAIM,
            role=Role.VETO_CAPABLE,
            adverse_states=frozenset({"protein_masks_subtype_restriction", "rna_masks_subtype_restriction"}),
        ),
        FrameInput(
            property_id=NORMAL_LIABILITY_PROPERTY,
            kind=InputKind.MISSING_UNRESOLVED,
            role=Role.CRITICAL_UNKNOWN,
        ),
    ),
)

# --------------------------------------------------------------------------------------------------
# Third PRESENCE-domain frame — the targetable-antigen PRIORITY surface (SK#1854, epic #1848 C1)
# --------------------------------------------------------------------------------------------------
# The THIRD frame the L3 typed-evidence interface mints, and the SECOND over the presence domain (after
# PRESENCE_FRAME, #1842) — proving the interface carries MORE THAN ONE decision surface over one domain
# whose decision-implications differ (mirroring the per-modality family, #1844). This is the antigen-
# PRIORITY view — NOT a re-derivation of the tumor-presence verdict — asking "is this a well-corroborated
# tumor-presence signal worth PRIORITIZING as a targetable antigen?". It weights the SAME presence
# evidence differently from PRESENCE_FRAME: here the cross-modality ABUNDANCE agreement is the down-rank
# lever (an rna_high_protein_low split means the transcript is present but the PROTEIN antigen is lower —
# a real targeting-abundance caveat that DOWN-RANKS one notch, never a kill), while subtype-restriction is
# merely CONTEXTUAL annotation on this surface. It also exercises the two remaining input KINDS the
# presence frame did not: a raw tumor-RNA all-gene percentile MEASUREMENT (contextual) and the within-skill
# presence_strength LOCAL-COMPOSITE classifier (supportive):
#   * coverage             (bulk_vs_singlecell_coverage_concordance) canonical-property-claim / required
#   * abundance            (abundance_concordance)                    canonical-property-claim / veto_capable
#     (a MEASURED rna_high_protein_low cross-modality split down-ranks one notch, never a kill)
#   * subtype_restriction  (subtype_restriction_concordance)         canonical-property-claim / contextual
#   * tumor-RNA percentile (tumor_rna_allgene_percentile)            measurement              / contextual
#   * presence_strength    (presence_strength_class)                 local-composite-claim    / supportive
#   * normal-tissue safety liability (deliberately absent)           missing/unresolved       / critical_unknown
# normal_liability is the SAME deliberately-absent critical_unknown specimen as the other production frames:
# a tumor-presence surface never carries the cross-source safety concordance, so the unresolved critical
# routes the frame to an L4 QUESTION (never a kill). Per SK#1854 (epic #1848-C1) the frame DECLARES that
# critical_unknown role but does NOT render its forward-question here — the forward-question endpoint is the
# separate #1855 (C-endpoint); this frame only surfaces its synthesis as a verdict-inert annotation.
TUMOR_RNA_ALLGENE_PERCENTILE = "tumor_rna_allgene_percentile"
PRESENCE_STRENGTH_CLASS = "presence_strength_class"

# The two genuinely-NEW typed inputs this frame adds beyond the surfaced concordance families (SK#1854):
# a raw observed all-gene percentile MEASUREMENT and a within-skill presence_strength LOCAL-COMPOSITE
# classifier — each an OBSERVATIONAL-layer object (strictly below the decision_frame layer, so the frame
# stays inside the DAG). The three concordance families it also consumes (coverage / abundance / subtype)
# are the ALREADY-DECLARED SURFACED_CONCORDANCE_PROPERTIES (#1842) — reused, NOT re-declared.
PRESENCE_PRIORITY_OBSERVATIONAL_INPUTS = (TUMOR_RNA_ALLGENE_PERCENTILE, PRESENCE_STRENGTH_CLASS)

PRESENCE_PRIORITY_FRAME = Frame(
    frame_id="present_targetable_antigen_priority",
    inputs=(
        FrameInput(
            property_id=COVERAGE_CONCORDANCE_PROPERTY,
            kind=InputKind.CANONICAL_PROPERTY_CLAIM,
            role=Role.REQUIRED,
            positive_states=frozenset({"coverage_concordant"}),
        ),
        FrameInput(
            property_id=ABUNDANCE_CONCORDANCE_PROPERTY,
            kind=InputKind.CANONICAL_PROPERTY_CLAIM,
            role=Role.VETO_CAPABLE,
            adverse_states=frozenset({"rna_high_protein_low"}),
        ),
        FrameInput(
            property_id=SUBTYPE_RESTRICTION_PROPERTY,
            kind=InputKind.CANONICAL_PROPERTY_CLAIM,
            role=Role.CONTEXTUAL,
        ),
        FrameInput(
            property_id=TUMOR_RNA_ALLGENE_PERCENTILE,
            kind=InputKind.MEASUREMENT,
            role=Role.CONTEXTUAL,
        ),
        FrameInput(
            property_id=PRESENCE_STRENGTH_CLASS,
            kind=InputKind.LOCAL_COMPOSITE_CLAIM,
            role=Role.SUPPORTIVE,
        ),
        FrameInput(
            property_id=NORMAL_LIABILITY_PROPERTY,
            kind=InputKind.MISSING_UNRESOLVED,
            role=Role.CRITICAL_UNKNOWN,
        ),
    ),
)

# --------------------------------------------------------------------------------------------------
# Per-MODALITY decision frames — the deferred modality-fit territory (SK#1844, G3.4, epic #1749 M2)
# --------------------------------------------------------------------------------------------------
# G3.4 is the modality-fit frame that #1753 deliberately DEFERRED: it re-derives surface-modality-fit
# territory (the biologics-substrate call) and so carries the highest verdict-collision risk — it lands
# LAST and gated HARDEST. It is the FIRST place the typed interface mints MORE THAN ONE frame over the
# SAME domain: a per-MODALITY family of decision surfaces (ADC / TCE today; the SM / degrader analog is
# a small-molecule surface the biologics ladder never sees, filed separately), because the DECISION-
# IMPLICATIONS of the same surface evidence DIFFER by modality — a clinically-shed ectodomain is an
# ADC antigen sink (a veto for the ADC frame) while within-tumour antigen ESCAPE is the TCE reservoir
# risk (a veto for the TCE frame). These are lossy-by-design L3 decision objects on the "verdict-
# follows" side — a DIFFERENT KIND of object from the L2 properties they read — NOT a re-derivation of
# the surface-modality-fit verdict, which stays byte-stable (owned by the shared resolver).
#
# Every input is a WITHIN-SKILL composite classifier the surface-modality-fit headline already carries
# (a class token bundling several card measurements — surface_density_class from copies/cell estimates,
# topology_class from tm_pass_count, shed_liability_class / tce_antigen_escape_class from multi-axis
# reads), so each is honestly consumed as a LOCAL_COMPOSITE_CLAIM (observational layer, is_composite),
# strictly below the decision_frame layer → the two new frames stay inside the existing DAG acyclicity
# proof. normal_liability is the SAME deliberately-absent critical_unknown specimen as the other two
# production frames: a surface-modality surface never carries the cross-source safety concordance, so
# the unresolved critical routes each modality frame to an L4 forward QUESTION (never a kill).
SURFACE_DENSITY_CLASS = "surface_density_class"
SURFACE_TOPOLOGY_CLASS = "topology_class"
SHED_LIABILITY_CLASS = "shed_liability_class"
TCE_ANTIGEN_ESCAPE_CLASS = "tce_antigen_escape_class"

# Surface topologies that mean "there is a cell-surface protein to engineer a binder against" — the
# supportive membrane-presence read shared by both modality frames (a no_transmembrane / data_unavailable
# read is NOT positive; its absence is fine — supportive, never a kill).
_SURFACE_TOPOLOGY_POSITIVE = frozenset(
    {
        "single_pass_type_1",
        "single_pass_type_2",
        "single_pass_type_other",
        "multi_pass",
        "gpi_anchored",
        "beta_barrel",
    }
)
# A density class at or above the ADC/TCE payload floor (a viable antigen abundance for either modality).
_SURFACE_DENSITY_POSITIVE = frozenset({"high", "moderate"})

ADC_MODALITY_FRAME = Frame(
    frame_id="adc_surface_modality_fit",
    inputs=(
        FrameInput(
            property_id=SURFACE_DENSITY_CLASS,
            kind=InputKind.LOCAL_COMPOSITE_CLAIM,
            role=Role.REQUIRED,
            positive_states=_SURFACE_DENSITY_POSITIVE,
        ),
        FrameInput(
            property_id=SURFACE_TOPOLOGY_CLASS,
            kind=InputKind.LOCAL_COMPOSITE_CLAIM,
            role=Role.SUPPORTIVE,
            positive_states=_SURFACE_TOPOLOGY_POSITIVE,
        ),
        FrameInput(
            property_id=SHED_LIABILITY_CLASS,
            kind=InputKind.LOCAL_COMPOSITE_CLAIM,
            role=Role.VETO_CAPABLE,
            adverse_states=frozenset({"clinically_shed"}),
        ),
        FrameInput(
            property_id=NORMAL_LIABILITY_PROPERTY,
            kind=InputKind.MISSING_UNRESOLVED,
            role=Role.CRITICAL_UNKNOWN,
        ),
    ),
)

TCE_MODALITY_FRAME = Frame(
    frame_id="tce_surface_modality_fit",
    inputs=(
        FrameInput(
            property_id=SURFACE_DENSITY_CLASS,
            kind=InputKind.LOCAL_COMPOSITE_CLAIM,
            role=Role.REQUIRED,
            positive_states=_SURFACE_DENSITY_POSITIVE,
        ),
        FrameInput(
            property_id=TCE_ANTIGEN_ESCAPE_CLASS,
            kind=InputKind.LOCAL_COMPOSITE_CLAIM,
            role=Role.VETO_CAPABLE,
            adverse_states=frozenset({"escape_risk_high", "escape_risk_patient_variable"}),
        ),
        FrameInput(
            property_id=SURFACE_TOPOLOGY_CLASS,
            kind=InputKind.LOCAL_COMPOSITE_CLAIM,
            role=Role.SUPPORTIVE,
            positive_states=_SURFACE_TOPOLOGY_POSITIVE,
        ),
        FrameInput(
            property_id=NORMAL_LIABILITY_PROPERTY,
            kind=InputKind.MISSING_UNRESOLVED,
            role=Role.CRITICAL_UNKNOWN,
        ),
    ),
)

# The per-modality frames (SK#1844). A family over ONE domain, keyed by modality — the interface's first
# multi-frame-per-domain surface.
MODALITY_FIT_FRAMES = (ADC_MODALITY_FRAME, TCE_MODALITY_FRAME)

# The surface-modality composite families the modality frames declare as typed inputs. Every member must
# demonstrably reach a frame (the decision-reach ratchet, lifted to the modality set): density + topology
# reach BOTH modality frames, shed reaches only ADC, escape only TCE, and normal_liability is the shared
# absent critical on every production frame.
MODALITY_FIT_PROPERTIES = (
    SURFACE_DENSITY_CLASS,
    SURFACE_TOPOLOGY_CLASS,
    SHED_LIABILITY_CLASS,
    TCE_ANTIGEN_ESCAPE_CLASS,
    NORMAL_LIABILITY_PROPERTY,
)

FRAME_REGISTRY = (
    REFERENCE_FRAME,
    PRESENCE_FRAME,
    PRESENCE_PRIORITY_FRAME,
    ADC_MODALITY_FRAME,
    TCE_MODALITY_FRAME,
)


def reference_emitted_layers() -> dict:
    """Emitted layer for every node in the reference registry — the acyclicity check's ground truth.

    Both reference frames' inputs are property-layer claims; each frame itself is a decision_frame.
    (A canonical/local-composite/measurement input all sit strictly below decision_frame, so the two
    frames are each a trivial DAG that shares no cross-frame edge — ``assert_acyclic`` is exercised
    against a synthetic cyclic registry in the tests to prove it has teeth.)
    """
    layers = {
        ESSENTIALITY_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        RECURRENCE_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        SELECTIVITY_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        DEPENDENCY_EFFECT_MEASUREMENT: ClaimType.OBSERVATIONAL_PROPERTY,
        COMPOSITE_SELECTIVITY_CLASS: ClaimType.OBSERVATIONAL_PROPERTY,
        NORMAL_LIABILITY_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        # The three surfaced PRESENCE concordance families PRESENCE_FRAME consumes (SK#1842) — each an
        # L2b integrated_property, strictly below the decision_frame layer, so the graph stays a DAG.
        COVERAGE_CONCORDANCE_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        ABUNDANCE_CONCORDANCE_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        SUBTYPE_RESTRICTION_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        # The four surface-modality composite families the per-modality frames consume (SK#1844). Each is
        # a WITHIN-SKILL composite classifier — an OBSERVATIONAL-layer bundle, NOT an L2b integrated
        # property — so each sits strictly below the decision_frame layer and the modality frames stay a
        # DAG (their honest InputKind is LOCAL_COMPOSITE_CLAIM, which asserts only the observational layer).
        SURFACE_DENSITY_CLASS: ClaimType.OBSERVATIONAL_PROPERTY,
        SURFACE_TOPOLOGY_CLASS: ClaimType.OBSERVATIONAL_PROPERTY,
        SHED_LIABILITY_CLASS: ClaimType.OBSERVATIONAL_PROPERTY,
        TCE_ANTIGEN_ESCAPE_CLASS: ClaimType.OBSERVATIONAL_PROPERTY,
        # The two genuinely-NEW typed inputs the antigen-priority frame adds (SK#1854): a raw tumor-RNA
        # all-gene percentile MEASUREMENT and the within-skill presence_strength LOCAL-COMPOSITE classifier.
        # Each is an OBSERVATIONAL-layer object (a measurement / a within-skill composite, NOT an L2b
        # integrated property), strictly below the decision_frame layer, so PRESENCE_PRIORITY_FRAME stays a
        # DAG. (Its three concordance inputs reuse the INTEGRATED_PROPERTY layers already mapped above.)
        TUMOR_RNA_ALLGENE_PERCENTILE: ClaimType.OBSERVATIONAL_PROPERTY,
        PRESENCE_STRENGTH_CLASS: ClaimType.OBSERVATIONAL_PROPERTY,
    }
    for f in FRAME_REGISTRY:
        layers[f.frame_id] = f.claim_type
    return layers


# --------------------------------------------------------------------------------------------------
# Production entry — the L3 -> production beachhead (SK#1841)
# --------------------------------------------------------------------------------------------------
def dependency_priority_frame(claim_vector: Optional[Mapping] = None, headline: Optional[Mapping] = None) -> dict:
    """Evaluate the ``corroborated_dependency_priority`` REFERENCE_FRAME over a functional-requirement
    skill's ALREADY-EMITTED typed evidence, returning the frame's OWN L3 decision object.

    This is the FIRST place the L3 typed-evidence interface reaches a production answer surface (SK#1841,
    epic #1749 Milestone-2). Purely ADDITIVE / verdict-INERT: it consumes the emitted claim_vector as
    typed inputs and produces a NEW decision surface; it routes NOTHING back into the dependency_verdict,
    the claim_vector, any question_table row's meter cell, or a resolver. The source claims are read
    through the read-only adapters, so every emitted family stays byte-stable.

    Bundle construction (an input NOT supplied auto-resolves to ``unresolved`` inside ``evaluate_frame``):
      * ESSENTIALITY (required)   <- the L2b ``crispr_rnai_essentiality_concordance`` claim on the FR
        vector — the anchor input this surface natively carries.
      * RECURRENCE / SELECTIVITY  <- adapted only IF present on the vector (they are OTHER skills' L2b
        properties, structurally absent on a functional-requirement surface, so their supportive/veto
        absence is fine — never a kill).
      * DEPENDENCY_EFFECT (contextual) / COMPOSITE_SELECTIVITY (supportive) <- optional headline reads.
      * NORMAL_LIABILITY (critical_unknown) is DELIBERATELY never supplied: a functional-requirement
        surface never carries the safety claim, so the unresolved critical routes the frame to an L4
        forward QUESTION (never a kill) — the roles-not-weights G3.3 forward-question path.
    """
    cv = claim_vector or {}
    h = headline or {}
    bundle: dict = {}
    for pid in (ESSENTIALITY_PROPERTY, RECURRENCE_PROPERTY, SELECTIVITY_PROPERTY):
        claim = cv.get(pid)
        if claim is not None:
            bundle[pid] = from_concordance(pid, claim)
    eff = h.get(DEPENDENCY_EFFECT_MEASUREMENT)
    if eff is not None:
        bundle[DEPENDENCY_EFFECT_MEASUREMENT] = measurement(DEPENDENCY_EFFECT_MEASUREMENT, eff)
    comp = h.get(COMPOSITE_SELECTIVITY_CLASS)
    if comp is not None:
        bundle[COMPOSITE_SELECTIVITY_CLASS] = local_composite(COMPOSITE_SELECTIVITY_CLASS, comp)
    # NORMAL_LIABILITY_PROPERTY intentionally omitted -> unresolved critical_unknown -> L4 question.
    return evaluate_frame(REFERENCE_FRAME, bundle)


# --------------------------------------------------------------------------------------------------
# Second production entry — the PRESENCE-domain L3 surface (SK#1842)
# --------------------------------------------------------------------------------------------------
def tumor_presence_frame(claim_vector: Optional[Mapping] = None, by_subtype_vector: Optional[Mapping] = None) -> dict:
    """Evaluate the ``corroborated_tumor_presence`` PRESENCE_FRAME over a tumor-presence skill's
    ALREADY-EMITTED typed evidence, returning the frame's OWN L3 decision object.

    This is the SECOND domain the L3 typed-evidence interface reaches (SK#1842, epic #1749 Milestone-2),
    proving the interface spans >1 domain, not just dependency. Purely ADDITIVE / verdict-INERT: it
    consumes the emitted claim vectors as typed inputs and produces a NEW decision surface; it routes
    NOTHING back into the presence_verdict, the claim_vector, any question_table row's meter cell, or a
    resolver. Every source claim is read through the read-only adapters, so every emitted family stays
    byte-stable.

    Bundle construction (an input NOT supplied auto-resolves to ``unresolved`` inside ``evaluate_frame``):
      * COVERAGE (required)   <- the L2b ``bulk_vs_singlecell_coverage_concordance`` claim on the POOLED
        presence vector — the anchor cross-source presence property this surface natively carries.
      * ABUNDANCE (supportive) <- the L2b ``abundance_concordance`` claim on the pooled vector, adapted
        only IF present (a second modality-pair strengthens when it agrees; its absence is fine).
      * SUBTYPE_RESTRICTION (veto_capable) <- the L2b ``subtype_restriction_concordance`` claim on the
        BY-SUBTYPE vector (it is keyed there, not on the pooled vector — see presence_claims.py). A
        MEASURED cross-modality restriction MASK down-ranks one notch, never a kill; its absence is fine.
      * NORMAL_LIABILITY (critical_unknown) is DELIBERATELY never supplied: a tumor-presence surface never
        carries the safety claim, so the unresolved critical routes the frame to an L4 forward QUESTION
        (never a kill) — the roles-not-weights forward-question path.
    """
    cv = claim_vector or {}
    sv = by_subtype_vector or {}
    bundle: dict = {}
    cov = cv.get(COVERAGE_CONCORDANCE_PROPERTY)
    if cov is not None:
        bundle[COVERAGE_CONCORDANCE_PROPERTY] = from_concordance(COVERAGE_CONCORDANCE_PROPERTY, cov)
    ab = cv.get(ABUNDANCE_CONCORDANCE_PROPERTY)
    if ab is not None:
        bundle[ABUNDANCE_CONCORDANCE_PROPERTY] = from_concordance(ABUNDANCE_CONCORDANCE_PROPERTY, ab)
    sub = sv.get(SUBTYPE_RESTRICTION_PROPERTY)
    if sub is not None:
        bundle[SUBTYPE_RESTRICTION_PROPERTY] = from_concordance(SUBTYPE_RESTRICTION_PROPERTY, sub)
    # NORMAL_LIABILITY_PROPERTY intentionally omitted -> unresolved critical_unknown -> L4 question.
    return evaluate_frame(PRESENCE_FRAME, bundle)


# --------------------------------------------------------------------------------------------------
# Third production entry — the targetable-antigen PRIORITY L3 surface (SK#1854, epic #1848 C1)
# --------------------------------------------------------------------------------------------------
def presence_priority_frame(
    claim_vector: Optional[Mapping] = None,
    headline: Optional[Mapping] = None,
    by_subtype_vector: Optional[Mapping] = None,
) -> dict:
    """Evaluate the ``present_targetable_antigen_priority`` PRESENCE_PRIORITY_FRAME over a tumor-presence
    skill's ALREADY-EMITTED typed evidence, returning the frame's OWN L3 decision object.

    The THIRD production frame (SK#1854, epic #1848-C1) and the SECOND over the presence domain — a NEW
    additive antigen-PRIORITY decision surface, NOT a re-derivation of the presence_verdict. Purely
    ADDITIVE / verdict-INERT: it consumes the emitted claim vectors + headline reads as typed inputs and
    produces a NEW decision surface; it routes NOTHING back into the presence_verdict, the claim_vector, any
    question_table row's meter cell, or a resolver. Every source claim is read through the read-only
    adapters, so every emitted family stays byte-stable.

    Bundle construction (an input NOT supplied auto-resolves to ``unresolved`` inside ``evaluate_frame``):
      * COVERAGE (required)    <- the L2b ``bulk_vs_singlecell_coverage_concordance`` claim on the POOLED
        presence vector — the anchor cross-source presence property this surface natively carries.
      * ABUNDANCE (veto_capable) <- the L2b ``abundance_concordance`` claim on the pooled vector. On THIS
        surface a MEASURED ``rna_high_protein_low`` cross-modality split (transcript present, protein antigen
        lower) DOWN-RANKS one notch (never a kill); its absence is fine. (This is where the priority view
        weights the same evidence differently from PRESENCE_FRAME, where abundance is merely supportive.)
      * SUBTYPE_RESTRICTION (contextual) <- the L2b ``subtype_restriction_concordance`` claim on the
        BY-SUBTYPE vector (it is keyed there, not on the pooled vector — see presence_claims.py); annotation
        only, never gates.
      * TUMOR_RNA_ALLGENE_PERCENTILE (measurement, contextual) <- an optional raw all-gene percentile read
        off ``headline`` (a single observed measurement; annotation only).
      * PRESENCE_STRENGTH_CLASS (local-composite, supportive) <- the within-skill presence_strength composite
        classifier read off ``headline`` (a bundle of the A/B/C/D signals floored by presence_state — NOT an
        atomic canonical property, so honestly consumed as a local-composite; absence is fine).
      * NORMAL_LIABILITY (critical_unknown) is DELIBERATELY never supplied: a tumor-presence surface never
        carries the safety claim, so the unresolved critical routes the frame to an L4 QUESTION (never a
        kill). Per SK#1854 (epic #1848-C1) this role is DECLARED but its forward-question is NOT rendered
        here — that endpoint is the separate #1855.
    """
    cv = claim_vector or {}
    h = headline or {}
    sv = by_subtype_vector or {}
    bundle: dict = {}
    cov = cv.get(COVERAGE_CONCORDANCE_PROPERTY)
    if cov is not None:
        bundle[COVERAGE_CONCORDANCE_PROPERTY] = from_concordance(COVERAGE_CONCORDANCE_PROPERTY, cov)
    ab = cv.get(ABUNDANCE_CONCORDANCE_PROPERTY)
    if ab is not None:
        bundle[ABUNDANCE_CONCORDANCE_PROPERTY] = from_concordance(ABUNDANCE_CONCORDANCE_PROPERTY, ab)
    sub = sv.get(SUBTYPE_RESTRICTION_PROPERTY)
    if sub is not None:
        bundle[SUBTYPE_RESTRICTION_PROPERTY] = from_concordance(SUBTYPE_RESTRICTION_PROPERTY, sub)
    pct = h.get(TUMOR_RNA_ALLGENE_PERCENTILE)
    if pct is not None:
        bundle[TUMOR_RNA_ALLGENE_PERCENTILE] = measurement(TUMOR_RNA_ALLGENE_PERCENTILE, pct)
    strength = h.get(PRESENCE_STRENGTH_CLASS)
    if strength is not None:
        bundle[PRESENCE_STRENGTH_CLASS] = local_composite(PRESENCE_STRENGTH_CLASS, strength)
    # NORMAL_LIABILITY_PROPERTY intentionally omitted -> unresolved critical_unknown -> L4 question.
    return evaluate_frame(PRESENCE_PRIORITY_FRAME, bundle)


# --------------------------------------------------------------------------------------------------
# Per-modality production entries — the deferred modality-fit L3 surfaces (SK#1844, G3.4)
# --------------------------------------------------------------------------------------------------
# A surface_density_class token that is a data GAP rather than a measured density class — an unmeasured
# density is NOT a resolved observational read, so it is left OUT of the bundle (the REQUIRED anchor then
# routes the frame to an L4 QUESTION, never a HOLD on a phantom "measured very-low").
DENSITY_GAP_TOKENS = frozenset(
    {"unmeasured", "data_unavailable", "not_surface_density_whole_cell_estimate", "no_absolute_measurement"}
)


def _surface_modality_bundle(frame: Frame, headline: Optional[Mapping]) -> dict:
    """Adapt a surface-modality-fit headline's ALREADY-EMITTED composite class tokens into typed evidence
    for ``frame``. Every consumed field is a within-skill composite classifier → wrapped as a read-only
    ``local_composite`` (never over-claimed as a canonical property), so the source headline stays byte-
    stable. A field absent / a density GAP token is simply not supplied (auto-resolves to unresolved inside
    ``evaluate_frame``). ``normal_liability`` is DELIBERATELY never supplied — the surface-modality surface
    never carries the cross-source safety concordance, so the critical_unknown routes to an L4 question."""
    h = headline or {}
    bundle: dict = {}
    for inp in frame.inputs:
        if inp.kind != InputKind.LOCAL_COMPOSITE_CLAIM:
            continue  # the critical_unknown / any non-composite slot is left for evaluate_frame to route
        token = h.get(inp.property_id)
        if inp.property_id == SURFACE_DENSITY_CLASS and token in DENSITY_GAP_TOKENS:
            continue  # a density GAP is unresolved, not a measured non-positive
        if token is not None:
            bundle[inp.property_id] = local_composite(inp.property_id, token)
    return bundle


def adc_modality_fit_frame(headline: Optional[Mapping] = None) -> dict:
    """Evaluate the ``adc_surface_modality_fit`` ADC_MODALITY_FRAME over a surface-modality-fit skill's
    ALREADY-EMITTED composite class tokens, returning the frame's OWN L3 decision object.

    The ADC decision-implications view (SK#1844, G3.4, epic #1749 Milestone-2): surface antigen abundance
    is the payload-floor anchor (REQUIRED), an engineerable surface topology strengthens it (SUPPORTIVE),
    and a clinically-shed ectodomain is an ADC antigen sink that DOWN-RANKS one notch (VETO_CAPABLE, never
    a kill). Purely ADDITIVE / verdict-INERT: it consumes the emitted headline as typed inputs and produces
    a NEW decision surface; it routes NOTHING back into the surface-modality-fit verdict (``fit_class``),
    the claim_vector, any question_table row's meter cell, ``safety_verdict_by_modality``, ``modality_rubric``,
    or a resolver. The absent safety critical routes the frame to an L4 forward QUESTION (never a kill)."""
    return evaluate_frame(ADC_MODALITY_FRAME, _surface_modality_bundle(ADC_MODALITY_FRAME, headline))


def tce_modality_fit_frame(headline: Optional[Mapping] = None) -> dict:
    """Evaluate the ``tce_surface_modality_fit`` TCE_MODALITY_FRAME over a surface-modality-fit skill's
    ALREADY-EMITTED composite class tokens, returning the frame's OWN L3 decision object.

    The TCE decision-implications view (SK#1844, G3.4, epic #1749 Milestone-2): the SAME surface antigen
    abundance is the engager-floor anchor (REQUIRED) and an engineerable topology strengthens it
    (SUPPORTIVE), but the modality-specific liability is DIFFERENT — within-tumour antigen ESCAPE
    (escape_risk_high / escape_risk_patient_variable) is the TCE efficacy-escape reservoir that DOWN-RANKS
    one notch (VETO_CAPABLE, never a kill), where the ADC frame instead vetoes on shedding. This is why the
    per-modality decision surface is a family, not one frame. Purely ADDITIVE / verdict-INERT: routes
    NOTHING back into any surface verdict, claim_vector, meter cell, ``safety_verdict_by_modality``,
    ``modality_rubric``, or resolver. The absent safety critical routes to an L4 forward QUESTION."""
    return evaluate_frame(TCE_MODALITY_FRAME, _surface_modality_bundle(TCE_MODALITY_FRAME, headline))
