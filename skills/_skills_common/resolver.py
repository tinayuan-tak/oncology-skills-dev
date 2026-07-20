"""Shared declarative verdict-resolver interpreter (gap #5, 2026-07-20).

ONE interpreter, evaluated by BOTH engines (target-profile + compose-dashboard), over a
per-gate declarative spec (target-contracts/resolvers/<gate>.resolver.yaml). Replaces the
hand-rolled `_verdict()` if-chains — the framework's most opinionated dependency/precedence
biology becomes a PR-reviewable ordered ladder instead of per-skill Python, and the
"copied not shared" two-engine drift risk disappears structurally (one implementation).

GUARDRAIL (deliberately NOT Turing-complete — see resolver.schema.json): a spec may ONLY
pattern-match over the SET of fired rule IDs — ordered precedence + when_fired /
when_any_fired / when_all_fired. No arithmetic, thresholds, loops, or lookups. Anything that
tempts past when_all_fired belongs in a card (label) or method (number), not here.

The interpreter reproduces the exact (verdict, driving_rule_id) semantics of the if-chains
it replaces, so the golden-oracle migration can assert spec-output == code-output
byte-for-byte before any if-chain is deleted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# Resolver specs live in target-contracts (they are CONTRACTS, like interpretation-rules).
_CONTRACTS_REPO = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
_RESOLVERS_DIR = _CONTRACTS_REPO / "resolvers"


def load_resolver(gate: str, contracts_repo: Path | None = None) -> Optional[dict]:
    """Load a gate's resolver spec, or None if absent (caller falls back to its own
    _verdict during the golden-oracle migration — never a hard failure)."""
    import yaml
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "resolvers" / f"{gate}.resolver.yaml"
    try:
        return yaml.safe_load(path.read_text())
    except OSError:
        return None


def resolve_verdict(fired: list[dict], spec: dict) -> tuple[str, str | None]:
    """Evaluate a resolver spec against a list of fired rules → (verdict, driving_rule_id).

    `fired` is the flat list of {rule_id, ...} dicts (the shared fired_rules output). The
    first matching rung wins (ordered precedence). driving_rule_id fidelity matches the
    if-chains being replaced:
      - when_fired      → that rule_id
      - when_any_fired  → the FIRST LISTED rule_id that fired (deterministic tie-break)
      - when_all_fired  → the explicit `driving_rule` if set, else the LAST listed rule_id
    No rung matches → (spec['default'], None).
    """
    fired_ids = {r["rule_id"] for r in fired}
    for rung in spec.get("resolve", []):
        verdict = rung["verdict"]
        if "when_fired" in rung:
            rid = rung["when_fired"]
            if rid in fired_ids:
                return verdict, (rung.get("driving_rule") or rid)
        elif "when_any_fired" in rung:
            for rid in rung["when_any_fired"]:          # list order = precedence tie-break
                if rid in fired_ids:
                    return verdict, (rung.get("driving_rule") or rid)
        elif "when_all_fired" in rung:
            rids = rung["when_all_fired"]
            if all(rid in fired_ids for rid in rids):
                return verdict, (rung.get("driving_rule") or rids[-1])
    return spec["default"], None


def resolve_verdict_for_gate(fired: list[dict], gate: str,
                             contracts_repo: Path | None = None
                             ) -> Optional[tuple[str, str | None]]:
    """Convenience: load the gate's spec + resolve. Returns None if no spec exists (the
    caller then uses its legacy _verdict — the migration seam)."""
    spec = load_resolver(gate, contracts_repo)
    if spec is None:
        return None
    return resolve_verdict(fired, spec)
