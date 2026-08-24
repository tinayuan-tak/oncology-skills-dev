#!/usr/bin/env python3
"""validate_certainty_disjointness.py — CERTAINTY_MODEL §3 required-validator #1 (R3).

Asserts, per gate, that the certainty_by_axis `corroboration` source cards (declared in
vocabularies/certainty_corroboration.yaml) are DISJOINT from that gate's verdict-precedence card-set:

    corroboration_cards ∩ verdict_precedence_cards = ∅

verdict_precedence_cards = every card_id behind a rule_id that the gate's resolver ladders over
(resolvers/<gate>.resolver.yaml rungs → rule_ids → interpretation-rules `when.card_id`). A corroboration
card that ALSO drives the verdict would count one signal as both `strength` and `certainty` — the
double-count the disjointness rule (CERTAINTY_MODEL.md §2) forbids.

The model documented three required validators; #2 (verdict→strength totality) and #3 (CERTAINTY_MODEL
path exists) were implemented, #1 (this one) was not (arch-review R3). This closes that gap.

Exit codes: 0 = clean; 1 = a disjointness violation, an unknown gate/card, or a load error.

Usage:
    python validators/validate_certainty_disjointness.py
    python validators/validate_certainty_disjointness.py --contracts-root .
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent


def _load_yaml(path: Path) -> dict:
    with path.open() as f:
        return yaml.safe_load(f) or {}


def _rule_id_to_cards(rules_dir: Path) -> dict[str, set[str]]:
    """{rule_id: {card_id, ...}} across every interpretation-rules file (a rule's when.card_id)."""
    out: dict[str, set[str]] = {}
    for f in sorted(rules_dir.glob("*.rules.yaml")):
        doc = _load_yaml(f)
        for rule in doc.get("rules", []) or []:
            rid = rule.get("rule_id")
            card = (rule.get("when", {}) or {}).get("card_id")
            if rid and card:
                out.setdefault(rid, set()).add(card)
    return out


def _resolver_rule_ids(spec: dict) -> set[str]:
    """Every rule_id referenced by any rung of a resolver spec (when_fired / when_any_fired / when_all_fired)."""
    rids: set[str] = set()
    for rung in spec.get("resolve", []) or []:
        if "when_fired" in rung:
            rids.add(rung["when_fired"])
        for key in ("when_any_fired", "when_all_fired"):
            for rid in rung.get(key, []) or []:
                rids.add(rid)
    return rids


def validate(contracts_root: Path) -> list[str]:
    """Return a list of error strings (empty = clean)."""
    errors: list[str] = []
    manifest_path = contracts_root / "vocabularies" / "certainty_corroboration.yaml"
    resolvers_dir = contracts_root / "resolvers"
    rules_dir = contracts_root / "interpretation-rules"

    if not manifest_path.exists():
        return [f"manifest missing: {manifest_path}"]
    manifest = _load_yaml(manifest_path)
    by_gate = manifest.get("corroboration_by_gate", {}) or {}
    # Cards that drive a gate's verdict OUTSIDE its resolver ladder: (a) Python-applied vetoes
    # (selectivity normal-breadth), (b) the FULL precedence set for no-resolver inline-verdict skills.
    # Unioned into verdict_precedence_cards so the disjointness check sees them (closes the resolver-only
    # blind spot). See vocabularies/certainty_corroboration.yaml::verdict_precedence_augment.
    augment = manifest.get("verdict_precedence_augment", {}) or {}

    rule_cards = _rule_id_to_cards(rules_dir)

    for gate, corrob_cards in by_gate.items():
        corrob = set(corrob_cards or [])
        aug = set(augment.get(gate, []) or [])
        resolver_path = resolvers_dir / f"{gate}.resolver.yaml"
        if not resolver_path.exists():
            # No-resolver (inline-verdict) skill: the manifest MUST declare its verdict-precedence set
            # via verdict_precedence_augment (else we cannot check disjointness → refuse silently-passing).
            if not aug:
                errors.append(
                    f"[{gate}] no resolver at {resolver_path} AND no verdict_precedence_augment[{gate}] — "
                    f"an inline-verdict (no-resolver) gate MUST declare its verdict-precedence cards under "
                    f"verdict_precedence_augment so disjointness is checkable.")
                continue
            verdict_cards = set(aug)
        else:
            spec = _load_yaml(resolver_path)
            rids = _resolver_rule_ids(spec)
            # Map the gate's verdict-precedence rule_ids → their emitting cards, + the Python-veto augment.
            verdict_cards = set(aug)
            for rid in rids:
                verdict_cards |= rule_cards.get(rid, set())

        overlap = corrob & verdict_cards
        if overlap:
            errors.append(
                f"[{gate}] DISJOINTNESS VIOLATION: corroboration card(s) {sorted(overlap)} ALSO drive the "
                f"verdict (they back a rule_id in {gate}.resolver.yaml's ladder). A corroboration source "
                f"must be verdict-disjoint (CERTAINTY_MODEL §2) — else certainty double-counts the verdict. "
                f"Move the verdict-disjoint signal here, or drop this card from corroboration_by_gate.")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate certainty corroboration ⟂ verdict-precedence disjointness.")
    ap.add_argument("--contracts-root", type=Path, default=REPO)
    args = ap.parse_args(argv)
    errors = validate(args.contracts_root)
    if errors:
        print("validate_certainty_disjointness.py results:")
        for e in errors:
            print(f"  ERROR: {e}")
        print(f"\nSummary: {len(errors)} disjointness error(s).")
        return 1
    print("validate_certainty_disjointness.py: OK — all registered corroboration cards are verdict-disjoint.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
