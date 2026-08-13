"""_skills_common/compose_core.py — the shared composition spine.

Stage 1 of the target-profile / compose-dashboard convergence. Both composition
frontends resolve their deterministic verdict spine — normalize card_outputs, fire
interpretation rules, and resolve each gate via the SHARED declarative resolver — and
Stage 1 routes that spine through the ONE code path here, returning a typed
``CompositionResult``.

This module owns ONLY the gate-resolution spine (fired_rules -> resolve_verdict_for_gate).
It deliberately does NOT own the parts that legitimately differ between the two engines,
so the extraction changes NO bytes:

  - card-set determination      dashboard_spec (compose-dashboard) vs SUB_SKILL_CARDS
                                (target-profile) — stays with each caller.
  - card resolution / execution execute_run_plan vs resolve_cards — different output
                                shapes; the caller passes already-resolved card_outputs.
  - governance enrichment       bare build_governance vs + resolved_release_governance —
                                parameterized per caller, attached AFTER this spine.
  - emitter concerns            evidence_package envelope vs nomination.json + LLM
                                synthesis — layered on top of this result.

Byte-golden guards that pin this behavior: compose-dashboard
``tests/test_end_to_end.py::test_e2e_invariance_byte_identical_reruns`` (whole-envelope
byte identity) and ``tests/test_engine_equivalence.py`` (per-gate verdict/driving-rule).
Both must stay green across this extraction.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GateVerdict:
    """One resolved gate — the audit-grade verdict spine block.

    ``as_dict`` field order MUST match compose-dashboard's historical ``_block`` output
    (gate, verdict, driving_rule_id, fired_rule_ids); the evidence_package byte-golden
    pins the on-disk key order.
    """

    gate: str
    verdict: str
    driving_rule_id: "str | None"
    fired_rule_ids: list[str]

    def as_dict(self) -> dict:
        return {
            "gate": self.gate,
            "verdict": self.verdict,
            "driving_rule_id": self.driving_rule_id,
            "fired_rule_ids": self.fired_rule_ids,
        }


@dataclass(frozen=True)
class CompositionResult:
    """The deterministic spine result for one resolved card set.

    Carries the fired-rule audit trail + the resolved gate verdicts, split into
    ``primary_gate_verdict`` (the headline gate; ``None`` when the axis has no gate
    mapping or the gate's resolver spec is absent — the graceful-degradation seam the
    caller falls back on) and ``additional_gate_verdicts`` (gates resolved over the SAME
    fired set; e.g. the intracellular axis emits dependency / genomic_alteration /
    selectivity alongside the tractability headline).

    Emitter-facing fields (governance, input_context, validation_summary) are attached by
    the caller in later stages — this type is intentionally scoped to the gate-resolution
    spine for Stage 1. target-profile (Stage 1b) builds one CompositionResult per
    sub-skill with a single primary gate and no additional gates.
    """

    card_outputs: list[dict]
    fired_rule_ids: list[str]
    primary_gate_verdict: "GateVerdict | None"
    additional_gate_verdicts: list[GateVerdict]

    def primary_dict(self) -> "dict | None":
        """The primary gate block as a plain dict (or None), matching the legacy shape."""
        return self.primary_gate_verdict.as_dict() if self.primary_gate_verdict else None

    def additional_dicts(self) -> list[dict]:
        """The additional gate blocks as plain dicts, in resolution order."""
        return [g.as_dict() for g in self.additional_gate_verdicts]


def resolve_gate_spine(
    card_outputs: list[dict],
    *,
    headline_gate: "str | None",
    additional_gates: "list[str] | None" = None,
    rules: "list[dict] | None" = None,
    contracts_root,
) -> CompositionResult:
    """Resolve a card set's gate verdict(s) via the SHARED declarative resolver.

    Byte-for-byte the logic compose-dashboard's ``_resolve_gate_verdicts`` ran inline:
      - normalize an applies_when-excluded card to ``_missing`` so ``fired_rules`` skips it,
      - fire rules over the surviving card_ids,
      - sort the fired rule-id set,
      - resolve each gate; drop a gate whose resolver spec is absent (graceful).

    ``headline_gate=None`` yields an empty CompositionResult (the axis has no gate mapping).
    The shared ``fired_rule_ids`` set is carried on the result AND stamped into every
    GateVerdict, matching the historical per-block shape.
    """
    # Lazy import (skills/ dir already on sys.path via the caller's shim) — mirrors the
    # exact import the inline implementation used, so name resolution is identical.
    from _skills_common import fired_rules, resolve_verdict_for_gate

    normed = [
        dict(c, _missing=True) if c.get("excluded_by_applies_when") else c
        for c in card_outputs
    ]
    surviving = [
        c["card_id"] for c in normed if c.get("card_id") and not c.get("_missing")
    ]
    fired = fired_rules(normed, axis="", card_id_filter=surviving, rules=rules or [])
    fired_ids = sorted({fr["rule_id"] for fr in fired if fr.get("rule_id")})

    def _block(gate: str) -> "GateVerdict | None":
        res = resolve_verdict_for_gate(fired, gate, contracts_repo=contracts_root)
        if res is None:
            return None  # no resolver spec for this gate → skip (graceful)
        verdict, driving = res
        return GateVerdict(
            gate=gate,
            verdict=verdict,
            driving_rule_id=driving,
            fired_rule_ids=fired_ids,
        )

    primary = _block(headline_gate) if headline_gate else None
    additional: list[GateVerdict] = []
    for g in additional_gates or []:
        blk = _block(g)
        if blk is not None:
            additional.append(blk)

    return CompositionResult(
        card_outputs=card_outputs,
        fired_rule_ids=fired_ids,
        primary_gate_verdict=primary,
        additional_gate_verdicts=additional,
    )


def subskill_composition(
    *,
    card_outputs: list[dict],
    fired: list[dict],
    gate: "str | None",
    verdict_pair: "tuple[str, str | None] | None",
) -> CompositionResult:
    """Wrap a sub-skill's ALREADY-RESOLVED verdict into the shared type WITHOUT re-resolving.

    target-profile (Stage 1b) fans out to standalone sub-skills whose ``_verdict`` / ``_snapshot``
    each resolve their own gate via the shared resolver AND may apply post-resolver logic (vetoes,
    downgrades) before returning the final ``(verdict, driving_rule_id)`` pair. This helper wraps
    that FINAL pair so the sub-skill's post-processing is preserved — it deliberately does NOT call
    ``resolve_verdict_for_gate`` again (that would drop the post-processing). Contrast
    ``resolve_gate_spine``, which resolves from card_outputs and is used where the caller owns the
    full resolution (compose-dashboard).

    ``gate=None`` (a verdict-inert sub-skill with no resolver gate, e.g. tumor-presence) or
    ``verdict_pair=None`` (a sub-skill exposing no verdict function) → an empty primary; the
    fired-rule audit trail is still carried.

    Note: ``fired_rule_ids`` here follows compose_core's sorted-set convention. target-profile's
    nomination.json emits its own RAW-ordered fired list from ``r["fired"]`` separately (the two
    conventions differ), so a byte-sensitive caller reads fired from its existing source, not here.
    """
    fired_ids = sorted({fr["rule_id"] for fr in fired if fr.get("rule_id")})
    primary = None
    if verdict_pair is not None and gate is not None:
        verdict, driving = verdict_pair
        primary = GateVerdict(
            gate=gate,
            verdict=verdict,
            driving_rule_id=driving,
            fired_rule_ids=fired_ids,
        )
    return CompositionResult(
        card_outputs=card_outputs,
        fired_rule_ids=fired_ids,
        primary_gate_verdict=primary,
        additional_gate_verdicts=[],
    )
