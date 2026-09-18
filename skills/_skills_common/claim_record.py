"""claim_record.py — the shared factored-record ASSEMBLER (M1 of the factored-record migration;
target-contracts/docs/design/VERDICT_REPRESENTATION_MIGRATION.md).

The factored record (target-contracts/schemas/claim_record.schema.json) replaces the single
per-axis verdict TOKEN with a typed record that factors the four concerns the token conflated:
WHAT (finding), WHY (mechanism), FOR-WHAT (modality_scope), HOW-SURE (certainty). At M1 the record
is a SHADOW: each skill computes it in parallel and emits it into decision.json.claim_record_shadow,
and NOTHING consumes it (goldens untouched; the legacy verdict spine is still authoritative).

This module owns the parts that are IDENTICAL across all 10 axes:
  * record SHAPE (matches claim_record.schema.json),
  * the open-world INVARIANT (ignorance != negation): an open-world availability
    {not_wired, data_blocked, read_error} forces a non-committal finding
    (state='unknown', direction='neutral', magnitude flattened to none),
  * provenance assembly (fired_rule_ids MUST equal the resolver's actual fired set — the M1
    cross-check — and cards read).

Each skill supplies only the axis-SPECIFIC mapping (verdict token -> finding.state / direction /
availability / magnitude, mechanism role, modality_scope) via its own `_claim_record(...)` builder,
exactly as each skill already supplies its own `_strength_certainty(...)` certainty hook. The
per-axis certainty dict is passed straight through (it already conforms to CERTAINTY_MODEL.md).

Dependency-free by design (no jsonschema at runtime): schema conformance is guarded by unit tests,
not the hot path.

NOTE (carried to M3): the contracts validate_claim_record.py invariant D currently asserts
certainty.level == ordinal-min(coverage, corroboration) with strict equality; several skills
legitimately DOWNGRADE level below that on a none/absent verdict (a valid downgrade-only move).
When real records first hit the contracts validator (M3), invariant D should relax to
level <= ordinal-min(...) (downgrade-only). At M1 this is moot — the record is shadow-only.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

OPEN_WORLD_AVAILABILITY = frozenset({"not_wired", "data_blocked", "read_error"})
_NONE_MAGNITUDE = {"level": "none", "value": None, "scale": None, "distance_to_cut": None}

_VALID_AVAILABILITY = frozenset(
    {
        "not_wired",
        "data_blocked",
        "read_error",
        "insufficient",
        "measured_negative",
        "measured_positive",
        "out_of_scope",
    }
)
_VALID_DIRECTION = frozenset({"supports", "opposes", "neutral"})


def _rule_ids(fired) -> list[str]:
    """The resolver's fired set as sorted-unique rule_ids — the M1 provenance cross-check anchor."""
    return sorted({r["rule_id"] for r in (fired or []) if isinstance(r, dict) and r.get("rule_id")})


def _card_ids(cards) -> list[str]:
    return sorted({c["card_id"] for c in (cards or []) if isinstance(c, dict) and c.get("card_id")})


def assemble_claim_record(
    *,
    axis: str,
    state: str,
    direction: str,
    availability: str,
    certainty: dict,
    fired,
    cards,
    magnitude: Optional[dict] = None,
    mechanism: Optional[dict] = None,
    modality_scope: Optional[dict] = None,
    source_product_ids: Optional[list] = None,
    versions: Optional[dict] = None,
) -> dict:
    """Assemble a schema-shaped factored claim record from an axis's per-verdict mapping.

    Enforces the open-world invariant in one place so no per-axis builder can accidentally emit a
    directional finding under ignorance. `certainty` is passed through verbatim (already
    CERTAINTY_MODEL-shaped). `magnitude` defaults to the flattened none-magnitude.
    """
    if availability not in _VALID_AVAILABILITY:
        raise ValueError(f"claim_record[{axis}]: availability {availability!r} not in {sorted(_VALID_AVAILABILITY)}")

    # M2 render-equivalence anchor: capture the incoming (raw) verdict token BEFORE the open-world
    # override rewrites state to 'unknown'. For a measured finding this equals finding.state (render is
    # identity); for an open-world record it preserves the specific no-data token the factored finding
    # discards, so render_verdict(record) reproduces the byte-exact legacy decision.json verdict.
    legacy_verdict = state

    mag = dict(magnitude) if magnitude else dict(_NONE_MAGNITUDE)
    # normalize optional magnitude keys so the shape is always complete
    for k, default in _NONE_MAGNITUDE.items():
        mag.setdefault(k, default)

    # OPEN-WORLD INVARIANT — ignorance != negation. A not_wired/data_blocked/read_error record
    # cannot carry a finding or a valence, and its magnitude collapses to none.
    if availability in OPEN_WORLD_AVAILABILITY:
        state, direction, mag = "unknown", "neutral", dict(_NONE_MAGNITUDE)

    if direction not in _VALID_DIRECTION:
        raise ValueError(f"claim_record[{axis}]: direction {direction!r} not in {sorted(_VALID_DIRECTION)}")
    if mag["value"] is not None and mag.get("scale") is None:
        raise ValueError(f"claim_record[{axis}]: magnitude.value set but scale is None (no bare numbers)")

    rec: dict = {
        "axis": axis,
        "finding": {
            "state": state,
            "direction": direction,
            "magnitude": mag,
            "availability": availability,
        },
        "certainty": certainty,
        "provenance": {
            "fired_rule_ids": _rule_ids(fired),
            "cards": _card_ids(cards),
            "legacy_verdict": legacy_verdict,
        },
    }
    if mechanism:
        rec["mechanism"] = mechanism
    if modality_scope:
        rec["modality_scope"] = modality_scope
    if source_product_ids:
        rec["provenance"]["source_product_ids"] = sorted(set(source_product_ids))
    if versions:
        rec["provenance"]["versions"] = versions
    return rec


def magnitude_from_interpretation(gv: Optional[dict]) -> dict:
    """Map a key_evidence.interpretation gauged_value → the claim_record.magnitude COORDINATE fields
    (value / scale / distance_to_cut) so the factored record and the display ruler speak ONE vocabulary
    (the interpretation-encoding Stage-3 convergence). Returns {} when the ruler carries no value/scale
    (level stays the sole coordinate). distance_to_cut PREFERS the ruler's own surfaced delta; only when
    that is absent does it fall back to value-minus-cut (both pinned) — mirroring tumor-selectivity's
    proven `max_log2fc - cut`."""
    if not isinstance(gv, dict):
        return {}
    out: dict = {}
    val, scale = gv.get("value"), gv.get("scale")
    if val is not None and scale:  # no bare number (assemble_claim_record re-checks)
        out["value"] = val
        out["scale"] = scale
    dtc = gv.get("distance_to_cut")
    if dtc is None and isinstance(val, (int, float)) and not isinstance(val, bool):
        cut = next(
            (
                a.get("value")
                for a in ((gv.get("frame") or {}).get("anchors") or [])
                if isinstance(a, dict) and a.get("role") == "cut"
            ),
            None,
        )
        if isinstance(cut, (int, float)) and not isinstance(cut, bool):
            dtc = round(val - cut, 4)
    if dtc is not None:
        out["distance_to_cut"] = dtc
    return out


def magnitude_for_card(
    cards, card_id: str, measurement_type: str, level: str, contracts_repo: Optional[str] = None
) -> dict:
    """A claim_record magnitude {level, [value, scale, distance_to_cut]} for a single-value axis whose
    strength is carried by ONE card's reference-frame ruler. Builds that card's interpretation ruler from
    the SAME SALIENCE_SPEC + summary the display graph uses (evidence_salience.build_interpretation), so
    the factored record converges to the display reading. level-only when: level is 'none', the card is
    absent, the type has no reference_frame, or the summary lacks the ruler value (e.g. a stripped fixture
    / an un-measured signal). ONLY for a clean axis↔card mapping — a MULTI-CLASS axis (genomic_alteration,
    mechanism, ...) has no single continuous value matching its ordinal level, so it stays level-only and
    converges per-CARD in the display ruler instead."""
    mag = {"level": level}
    if level == "none" or not card_id:
        return mag
    c = next((x for x in (cards or []) if isinstance(x, dict) and x.get("card_id") == card_id), None)
    summary = (c or {}).get("summary") or {}
    try:
        from _skills_common.evidence_salience import build_interpretation, spec_for

        interp = build_interpretation({}, summary, spec_for(measurement_type), card_id, contracts_repo)
    except Exception:  # noqa: BLE001 — shadow record; never break the run over a ruler
        interp = []
    if interp:
        mag.update(magnitude_from_interpretation(interp[0]))
    return mag


def render_verdict(record: dict) -> str:
    """rho(record) -> the legacy verdict TOKEN (M2 render-equivalence).

    The token is DERIVABLE from the factored record, which is the strangler-fig invariant that lets
    the migration swap decision.json's verdict source to the record (M3) without moving any hash:

      * MEASURED finding  -> finding.state IS the token (identity). The record carries strictly more
        than the token (magnitude, modality_scope, certainty, ...); the token is the state projection.
      * OPEN-WORLD finding -> finding.state is the honest sentinel 'unknown' (ignorance != negation),
        which is NOT a legacy token; the exact discarded no-data token is read back from
        provenance.legacy_verdict so rho reproduces the byte-exact pre-migration verdict.

    Deterministic and pure — no data lookups, no arithmetic.
    """
    finding = record.get("finding") or {}
    state = finding.get("state")
    if state and state != "unknown":
        return state
    return (record.get("provenance") or {}).get("legacy_verdict")


# ---------------------------------------------------------------------------
# L2 record-grain identity (target-contracts #804 context+identity; decision #4 —
# PILOT on tumor-presence). These are the SKILL-side populators of the OPTIONAL
# claim_record.context + identity blocks that shipped DORMANT (zero populators) on
# claim_record.schema.json. They MIRROR the pinned canonical serialization in
# target-contracts/validators/validate_claim_record.py (_canonical_json + the
# F/G/H `_context_identity_invariants`), which is the SINGLE SOURCE OF TRUTH and
# RECOMPUTES every id — so ANY drift here (separators, sort_keys, ensure_ascii, or
# the record_revision_id payload join order) makes every emitted id mismatch its
# recompute. test_l2_context_identity.py cross-checks these against the contracts
# validator's own recipe so the two cannot silently diverge.
# ---------------------------------------------------------------------------

# The pan-cancer indication sentinels the framework uses on the (target, indication)
# path (dispatcher: `args.indication or "PANCANCER"`). A pan-cancer claim is scope ALL.
_L2_INDICATION_ALL = frozenset({"PANCANCER", "PAN_CANCER", "PAN-CANCER"})


def _l2_canonical_json(obj) -> str:
    """The pinned canonical serialization for identity hashing — byte-identical to
    validate_claim_record._canonical_json. Defined ONCE and reused by both helpers so a
    context_id and its record_revision_id can never disagree on serialization."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def build_l2_context(*, target: dict, indication: str, subgroup_spec, modality_scope: str = "ALL") -> dict:
    """Build the claim_record.context L2 join key from a run's binding. Each dimension carries an
    explicit scope so a pan-X claim (ALL / NOT_STRATIFIED) never silently joins to a specific-X one —
    the empty-join the indication-sentinel precedent records. Shapes + the SPECIFIC<->specifier
    coupling match claim_record.schema.json and the validator's H invariant exactly:

      target      — {symbol, hgnc_id} (+ensembl/uniprot when present), reused from the package's
                    already-resolved context.target (real hgnc_id).
      indication  — SPECIFIC(+oncotree_code) unless the run is pan-cancer (ALL, no specifier).
      subtype     — SPECIFIC(+subgroup_ids) for a strata list; ALL for the "all" sentinel;
                    NOT_STRATIFIED when subgroup_spec is null/empty (the honest 3rd state — 'not
                    stratified at all' is a DIFFERENT claim from 'pan-subtype').
      modality    — presence-grade axes are modality-INDEPENDENT (ALL). A channel-specific claim
                    passes modality_scope='SPECIFIC' with a channel (generalized in a later arc).
    """
    tgt = {"symbol": target["symbol"], "hgnc_id": int(target["hgnc_id"])}
    if target.get("ensembl"):
        tgt["ensembl"] = target["ensembl"]
    if target.get("uniprot"):
        tgt["uniprot"] = target["uniprot"]

    if indication and str(indication).upper() in _L2_INDICATION_ALL:
        ind = {"scope": "ALL"}
    else:
        ind = {"scope": "SPECIFIC", "oncotree_code": indication}

    if isinstance(subgroup_spec, str) and subgroup_spec.lower() == "all":
        sub = {"scope": "ALL"}
    elif subgroup_spec:  # a truthy strata list => subtype-scoped
        sub = {"scope": "SPECIFIC", "subgroup_ids": sorted({str(s) for s in subgroup_spec})}
    else:  # None / empty => the target was not stratified at all
        sub = {"scope": "NOT_STRATIFIED"}

    if modality_scope == "SPECIFIC":  # pragma: no cover — pilot is modality-independent
        raise ValueError("build_l2_context: SPECIFIC modality needs a channel (later arc); pilot is ALL")
    mod = {"scope": modality_scope}
    return {"target": tgt, "indication": ind, "subtype": sub, "modality": mod}


def derive_l2_identity(*, context: dict, axis: str, l0_digest: str, ruleset_version: str, versions: dict) -> dict:
    """Derive the claim_record.identity block — NEVER authored; every field recomputes from these
    inputs (the validator's F/G invariants recompute and reject a mismatch).

      context_id         = sha256(canonical(context))[:16]
      logical_key        = '<context_id>::<axis>'
      record_revision_id = sha256(logical_key|l0_digest|ruleset_version|canonical(versions))[:16]

    `l0_digest` MUST be the enclosing package's governance.resolved_release_digest so the emission-side
    R6 invariant holds by construction. `versions` MUST be the SAME dict stored at provenance.versions
    (the validator recomputes the rrid from provenance.versions, not from this block)."""
    cid = hashlib.sha256(_l2_canonical_json(context).encode("utf-8")).hexdigest()[:16]
    lk = f"{cid}::{axis}"
    payload = "|".join([lk, l0_digest, ruleset_version, _l2_canonical_json(versions or {})])
    rrid = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return {
        "context_id": cid,
        "logical_key": lk,
        "l0_digest": l0_digest,
        "ruleset_version": ruleset_version,
        "record_revision_id": rrid,
    }
