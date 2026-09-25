"""narrative_grounding — INV-6 generalized from the VERDICT to the LLM narrative PROSE.

INV-6 (target-profile `tp_facets.build_skill_report_rollup`) is a verdict-level coherence flag: the
recommendation must not read MORE favorable than the peak gating signal supports
(`recommendation_exceeds_signals`). The generative narrative layer (`narrator_engine`) can violate the
SAME invariant one level up — it can faithfully quote a claim and still smooth over it, e.g. cite a claim
whose `concordance = mixed` (an off-scale / weak signal) and write "overall, evidence STRONGLY supports
broad expression." That destroys exactly the disagreement signal the L2b concordance claims exist to
preserve. This module generalizes INV-6 from the collapsed verdict scalar to prose:

  1. CITATION CONTRACT. Every MATERIAL narrative statement must be grounded in registered claims — it
     carries `supported_by: [claim_id, ...]` naming the claim atoms it rests on.
  2. NON-EXCEEDANCE GATE. No cited statement may assert a POLARITY or STRENGTH stronger than the PEAK
     (most-favorable / most-corroborated) signal across its cited claims. This is INV-6 (scalar <= peak
     claim-chip signal) applied to the prose's asserted (polarity, strength) instead of the verdict.

WHAT THIS IS NOT (scope discipline, #1609). This is the citation contract + the polarity/strength
non-exceedance test — NOT full semantic entailment. We do NOT parse the prose to infer what it asserts;
the statement DECLARES its asserted `polarity` / `strength` (the author of a narrator bullet is asserting
a claim of some direction and strength, and declares it). The north-star `narrative -> cited claim IDs ->
entailment` is a later direction, out of scope here.

MATERIALITY is operationalized WITHOUT semantics so it is decidable independent of citation: a statement
is MATERIAL iff it ASSERTS a polarity or a strength (it makes an evidentiary claim about direction or
corroboration). A statement that asserts neither (pure framing / scoping / a stated ignorance-gap) is
IMMATERIAL and exempt from the citation contract. This mirrors the verdict guard, which only fires on a
POSITIVE recommendation — an evidentiary assertion — never on a `hold`.

VERDICT-INERT. A guard over the generative layer; it moves no verdict and no property. It reads the
narrative object + a claim registry and returns findings; it never mutates either.

Ordinal scales are the fleet-canonical claim-vector contracts (`claim_vector_core`): `SIGNAL_ORD` for
polarity, `CORROBORATION_ORD` for strength. An `unmeasured` / `underpowered` claim tier is `None`
(off-scale) — a gap can support NO measured assertion, so any measured polarity/strength asserted against
an all-gap citation EXCEEDS it. That is the "smoothed over a gap" catch.
"""

from __future__ import annotations

from typing import Optional

from _skills_common.claim_vector_core import CORROBORATION_ORD, SIGNAL_ORD

# Finding kinds (stable strings; consumed by tests/tooling).
UNCITED = "material_statement_uncited"  # material statement with no supported_by claim ids
UNKNOWN_CLAIM = "unknown_claim_id"  # a cited claim id absent from the registry
POLARITY_EXCEEDS = "polarity_exceeds_claim"  # asserted polarity ranks above the peak cited claim signal
STRENGTH_EXCEEDS = "strength_exceeds_claim"  # asserted strength ranks above the peak cited claim corrob


def _ord(scale: dict, tier) -> Optional[int]:
    """Ordinal for a tier on a claim-vector scale. An unknown or off-scale (`unmeasured`/`underpowered`)
    tier is None — off-scale, NOT comparable as a magnitude."""
    if tier is None:
        return None
    return scale.get(tier)


def _peak(scale: dict, tiers) -> Optional[int]:
    """The most-favorable ON-SCALE ordinal across a set of claim tiers, or None if EVERY cited tier is
    off-scale (a gap). `None` means: these claims support no measured assertion of this dimension."""
    ords = [o for o in (_ord(scale, t) for t in tiers) if o is not None]
    return max(ords) if ords else None


def is_material(statement: dict) -> bool:
    """A statement is MATERIAL iff it asserts a polarity or a strength (an evidentiary claim). Decidable
    without reading the prose or its citations."""
    if not isinstance(statement, dict):
        return False
    return statement.get("polarity") is not None or statement.get("strength") is not None


def check_statement(statement: dict, claims_by_id: dict) -> list[dict]:
    """Findings for ONE narrative statement against the claim registry.

    statement: {text?, polarity?, strength?, supported_by: [claim_id, ...]}
        polarity  — asserted signal tier in `SIGNAL_ORD` vocab (strong/moderate/weak/absent/negative/...).
        strength  — asserted corroboration tier in `CORROBORATION_ORD` vocab (high/moderate/single_arm/...).
    claims_by_id: {claim_id: {signal?, corroboration?}} — the registered claim atoms (the claim_chips /
        claim_vector atoms carry exactly `signal` + `corroboration`).

    Immaterial statements produce no findings (exempt from the citation contract).
    """
    findings: list[dict] = []
    if not is_material(statement):
        return findings

    supported_by = statement.get("supported_by") or []
    if not supported_by:
        findings.append({"kind": UNCITED, "statement": statement.get("text"), "supported_by": []})
        return findings  # nothing to non-exceedance-check against

    cited_signals: list = []
    cited_corrobs: list = []
    for cid in supported_by:
        claim = claims_by_id.get(cid)
        if claim is None:
            findings.append({"kind": UNKNOWN_CLAIM, "statement": statement.get("text"), "claim_id": cid})
            continue
        cited_signals.append(claim.get("signal"))
        cited_corrobs.append(claim.get("corroboration"))

    if any(f["kind"] == UNKNOWN_CLAIM for f in findings):
        # An unresolved citation means the claim floor is unknown — do not additionally assert
        # non-exceedance against a partial/empty basis; the unknown-claim finding is the actionable one.
        return findings

    polarity = statement.get("polarity")
    if polarity is not None:
        asserted = _ord(SIGNAL_ORD, polarity)
        peak = _peak(SIGNAL_ORD, cited_signals)
        # asserted on-scale, and it exceeds the peak claim signal (peak None = a gap supports nothing).
        if asserted is not None and (peak is None or asserted > peak):
            findings.append(
                {
                    "kind": POLARITY_EXCEEDS,
                    "statement": statement.get("text"),
                    "asserted": polarity,
                    "peak_claim_signal": None
                    if peak is None
                    else max(
                        cited_signals, key=lambda t: _ord(SIGNAL_ORD, t) if _ord(SIGNAL_ORD, t) is not None else -1
                    ),
                }
            )

    strength = statement.get("strength")
    if strength is not None:
        asserted = _ord(CORROBORATION_ORD, strength)
        peak = _peak(CORROBORATION_ORD, cited_corrobs)
        if asserted is not None and (peak is None or asserted > peak):
            findings.append(
                {
                    "kind": STRENGTH_EXCEEDS,
                    "statement": statement.get("text"),
                    "asserted": strength,
                    "peak_claim_corroboration": None
                    if peak is None
                    else max(
                        cited_corrobs,
                        key=lambda t: _ord(CORROBORATION_ORD, t) if _ord(CORROBORATION_ORD, t) is not None else -1,
                    ),
                }
            )

    return findings


def check_grounding(statements, claims_by_id: Optional[dict] = None) -> list[dict]:
    """Findings across a narrative's material statements. Empty list == the narrative is grounded and
    non-exceeding. VERDICT-INERT (reads only)."""
    claims_by_id = claims_by_id or {}
    findings: list[dict] = []
    for st in statements or []:
        findings.extend(check_statement(st, claims_by_id))
    return findings


__all__ = [
    "check_grounding",
    "check_statement",
    "is_material",
    "UNCITED",
    "UNKNOWN_CLAIM",
    "POLARITY_EXCEEDS",
    "STRENGTH_EXCEEDS",
]
