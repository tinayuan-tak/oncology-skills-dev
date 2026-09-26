"""Shared declarative verdict-resolver interpreter (gap #5, 2026-07-20).

ONE interpreter for the framework's verdict logic, over a per-gate declarative spec
(target-contracts/resolvers/<gate>.resolver.yaml). Used by the standalone focused skills
(run_wired_skill → _verdict → resolve_verdict_for_gate) AND by target-profile, which INHERITS
those sub-skill verdicts (it calls each sub-skill's _verdict). Replaces the hand-rolled
`_verdict()` if-chains — the framework's most opinionated dependency/precedence biology becomes a
PR-reviewable ordered ladder instead of per-skill Python.

NOTE (2026-08-12): compose-dashboard now calls this interpreter too — Phase D CONVERGED its
verdict path onto this resolver, which is the PRIMARY verdict; the former per-modality fit_level
scorer (compose-dashboard/scripts/_synthesis.py) is demoted to a display lens. The "copied not
shared" two-engine drift risk for the compose-dashboard path is resolved.

GUARDRAIL (deliberately NOT Turing-complete — see resolver.schema.json): a spec may ONLY
pattern-match over the SET of fired rule IDs — ordered precedence + when_fired /
when_any_fired / when_all_fired. No arithmetic, thresholds, loops, or lookups. Anything that
tempts past when_all_fired belongs in a card (label) or method (number), not here.

The interpreter reproduces the exact (verdict, driving_rule_id) semantics of the if-chains
it replaces, so the golden-oracle migration can assert spec-output == code-output
byte-for-byte before any if-chain is deleted.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Optional

from _skills_common.paths import target_contracts_root

# Resolver specs live in target-contracts (they are CONTRACTS, like interpretation-rules).
_CONTRACTS_REPO = target_contracts_root()


@functools.lru_cache(maxsize=None)
def load_resolver(gate: str, contracts_repo: Path | None = None) -> Optional[dict]:
    """Load a gate's resolver spec, or None if absent (caller falls back to its own
    _verdict during the golden-oracle migration — never a hard failure)."""
    import yaml

    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "resolvers" / f"{gate}.resolver.yaml"
    try:
        return yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return None


def _rung_match(rung: dict, fired_ids: set) -> tuple[bool, str | None]:
    """SINGLE source of rung-match semantics for BOTH evaluation modes (so first_match and
    match_all_reduce cannot drift). Returns (matched, driving_rule_id):
      - when_fired      → that rule_id
      - when_any_fired  → the FIRST LISTED rule_id that fired (deterministic tie-break)
      - when_all_fired  → the explicit `driving_rule` if set, else the LAST listed rule_id
    """
    if "when_fired" in rung:
        rid = rung["when_fired"]
        return (rid in fired_ids, rung.get("driving_rule") or rid)
    if "when_any_fired" in rung:
        for rid in rung["when_any_fired"]:  # list order = precedence tie-break
            if rid in fired_ids:
                return True, (rung.get("driving_rule") or rid)
        return False, None
    if "when_all_fired" in rung:
        rids = rung["when_all_fired"]
        if all(rid in fired_ids for rid in rids):
            return True, (rung.get("driving_rule") or rids[-1])
        return False, None
    return False, None


def resolve_verdict(fired: list[dict], spec: dict) -> tuple[str, str | None]:
    """Evaluate a resolver spec against a list of fired rules → (verdict, driving_rule_id).

    `fired` is the flat list of {rule_id, ...} dicts (the shared fired_rules output). Two evaluation
    modes (spec['evaluation'], default 'first_match'):

      - first_match       (default / legacy): the FIRST matching rung in ladder order wins — the
        implicit positional precedence the if-chains encoded.
      - match_all_reduce  (the Fold — VERDICT_REPRESENTATION_FOLD.md): evaluate EVERY rung, then
        return the matching rung of MINIMUM `priority`. Precedence is EXPLICIT DATA, so rung ORDER is
        irrelevant (R6 order-independence). With priority = ladder index this is byte-equivalent to
        first_match by construction (argmin(index) == first match).

    No rung matches → (spec['default'], None). Both modes share `_rung_match`, so they cannot drift.
    """
    fired_ids = {r["rule_id"] for r in fired}
    rungs = spec.get("resolve", [])

    if spec.get("evaluation") == "match_all_reduce":
        best: tuple[int, str, str | None] | None = None  # (priority, verdict, driving_rule_id)
        for i, rung in enumerate(rungs):
            matched, drv = _rung_match(rung, fired_ids)
            if matched:
                pr = rung.get("priority", i)  # explicit priority, else ladder index
                if best is None or pr < best[0]:  # min priority wins; < → first-seen breaks ties
                    best = (pr, rung["verdict"], drv)
        return (best[1], best[2]) if best is not None else (spec["default"], None)

    for rung in rungs:  # first_match (default / legacy)
        matched, drv = _rung_match(rung, fired_ids)
        if matched:
            return rung["verdict"], drv
    return spec["default"], None


def resolve_verdict_provenance(
    fired: list[dict], spec: dict
) -> tuple[str, str | None, list[tuple[int, str, str | None]]]:
    """Like resolve_verdict but ALSO returns the matching rungs that LOST to the winner — observability
    for precedence-review (RFC discordance-taxonomy Class A). Returns
    (verdict, driving_rule_id, discarded), where discarded = [(priority, verdict, driving_rule_id), ...] for
    every rung that MATCHED the fired set but did not win. Additive + read-only: resolve_verdict (the hot
    path used by every skill) is deliberately left UNCHANGED (2-tuple), so this cannot affect any verdict.

    match_all_reduce: winner = min-priority match; discarded = the other matches (priority-sorted).
    first_match:      winner = first matching rung; discarded = later matching rungs in ladder order."""
    fired_ids = {r["rule_id"] for r in fired}
    rungs = spec.get("resolve", [])
    if spec.get("evaluation") == "match_all_reduce":
        matches: list[tuple[int, str, str | None]] = []
        for i, rung in enumerate(rungs):
            matched, drv = _rung_match(rung, fired_ids)
            if matched:
                matches.append((rung.get("priority", i), rung["verdict"], drv))
        if not matches:
            return spec["default"], None, []
        matches.sort(key=lambda m: m[0])  # min priority wins; stable → first-seen breaks ties
        return matches[0][1], matches[0][2], matches[1:]
    for i, rung in enumerate(rungs):  # first_match
        matched, drv = _rung_match(rung, fired_ids)
        if matched:
            discarded: list[tuple[int, str, str | None]] = []
            for j in range(i + 1, len(rungs)):
                m2, d2 = _rung_match(rungs[j], fired_ids)
                if m2:
                    discarded.append((rungs[j].get("priority", j), rungs[j]["verdict"], d2))
            return rung["verdict"], drv, discarded
    return spec["default"], None, []


def resolve_verdict_for_gate(
    fired: list[dict], gate: str, contracts_repo: Path | None = None
) -> Optional[tuple[str, str | None]]:
    """Convenience: load the gate's spec + resolve. Returns None if no spec exists (the
    caller then uses its legacy _verdict — the migration seam)."""
    spec = load_resolver(gate, contracts_repo)
    if spec is None:
        return None
    return resolve_verdict(fired, spec)


def resolve_or_raise(fired: list[dict], gate: str, contracts_repo: Path | None = None) -> tuple[str, str | None]:
    """The standard skill `_verdict` body: resolve a gate's verdict from the shared
    declarative resolver, raising if the spec is absent.

    The resolver YAML (target-contracts/resolvers/<gate>.resolver.yaml) is the single
    source of truth, so a missing spec is a HARD error — never a silent fallback to a
    stale in-code copy, which would reintroduce the verdict drift this design eliminates.

    Returns (verdict, driving_rule_id). Raises RuntimeError if no spec exists for `gate`.
    """
    result = resolve_verdict_for_gate(fired, gate, contracts_repo)
    if result is None:
        raise RuntimeError(
            f"{gate} resolver spec missing "
            f"(target-contracts/resolvers/{gate}.resolver.yaml) "
            "— the verdict source of truth is absent."
        )
    return result
