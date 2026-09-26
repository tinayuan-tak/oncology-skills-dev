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

# The three rung-4 canonical property families this L3 bridge must demonstrably reach.
RUNG4_CANONICAL_PROPERTIES = (ESSENTIALITY_PROPERTY, RECURRENCE_PROPERTY, SELECTIVITY_PROPERTY)

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

FRAME_REGISTRY = (REFERENCE_FRAME,)


def reference_emitted_layers() -> dict:
    """Emitted layer for every node in the reference registry — the acyclicity check's ground truth.

    The reference frame's inputs are all property-layer claims; the frame itself is a decision_frame.
    (A canonical/local-composite/measurement input all sit strictly below decision_frame, so the graph
    is trivially a DAG at n=1 — ``assert_acyclic`` is exercised against a synthetic cyclic registry in
    the tests to prove it has teeth.)
    """
    layers = {
        ESSENTIALITY_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        RECURRENCE_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        SELECTIVITY_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
        DEPENDENCY_EFFECT_MEASUREMENT: ClaimType.OBSERVATIONAL_PROPERTY,
        COMPOSITE_SELECTIVITY_CLASS: ClaimType.OBSERVATIONAL_PROPERTY,
        NORMAL_LIABILITY_PROPERTY: ClaimType.INTEGRATED_PROPERTY,
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
