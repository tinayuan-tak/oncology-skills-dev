#!/usr/bin/env python3
"""
validate_measurement_types.py — governance validator for the measurement-type registry.

DATA_TO_SKILL_CONTRACT.md (2026-07-21) makes a card's identity (measurement_type × entity_grain)
and stands up vocabularies/measurement_types.yaml as the governed vocabulary of per-target-entity
CLAIMS. This validator machine-enforces the doc's governance rules so the registry can't silently
rot:

  1. evidence_tier is MANDATORY per provider (measured | inferred | estimated) — the machine home
     for the measured-vs-inferred discipline (Rule 5 / "missing middle" §2).
  2. Every derived_from provider's `inputs` must resolve to real measurement_type keys (Rule 4 —
     the type→type DAG edges must not dangle), and must not be self-referential.
  3. A type with >1 provider MUST declare a `multi_provider_policy`
     (tier_dominant | surface_discordance) — averaging/pick-one is forbidden (Rule 5).
  4. Every entity_grain is a key in the entity_grain_vocabulary (Rule 1/5 — grain is a governed,
     extensible vocabulary, never ad-hoc).
  5. Card back-references (a type's `cards:` list) name real cards/*.card.yaml files (catches a
     renamed/deleted card leaving a dangling registry ref) — skipped gracefully if cards/ absent.
  6. The DAG is acyclic (a derived type cannot transitively derive from itself).

Usage:
  python validate_measurement_types.py --vocab vocabularies/measurement_types.yaml --cards cards/
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_TIERS = {"measured", "inferred", "estimated"}
VALID_POLICIES = {"tier_dominant", "surface_discordance"}


@dataclass
class Report:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def err(self, m: str) -> None:
        self.errors.append(m)

    def warn(self, m: str) -> None:
        self.warnings.append(m)


def _known_card_ids(cards_dir: Path) -> set[str] | None:
    if not cards_dir.exists():
        return None
    ids = set()
    for p in cards_dir.glob("*.card.yaml"):
        try:
            spec = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError:
            continue
        cid = spec.get("card_id")
        if cid:
            ids.add(cid)
    return ids


def _has_cycle(types: dict) -> list[str]:
    """Return a list of type keys involved in a derived_from cycle (empty if acyclic)."""
    # edges: type -> set(input types) via derived_from providers
    edges: dict[str, set[str]] = {}
    for k, v in types.items():
        deps: set[str] = set()
        for p in v.get("providers", []) or []:
            if p.get("kind") == "derived_from":
                deps.update(p.get("inputs", []) or [])
        edges[k] = deps
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in edges}
    in_cycle: set[str] = set()

    def dfs(node: str, stack: list[str]) -> None:
        color[node] = GRAY
        stack.append(node)
        for dep in edges.get(node, ()):
            if dep not in color:  # dangling input — caught separately
                continue
            if color[dep] == GRAY:
                # cycle: everything from dep's position on the stack
                if dep in stack:
                    in_cycle.update(stack[stack.index(dep):])
            elif color[dep] == WHITE:
                dfs(dep, stack)
        stack.pop()
        color[node] = BLACK

    for k in edges:
        if color[k] == WHITE:
            dfs(k, [])
    return sorted(in_cycle)


def validate(vocab_path: Path, cards_dir: Path | None) -> Report:
    r = Report()
    try:
        doc = yaml.safe_load(vocab_path.read_text()) or {}
    except yaml.YAMLError as e:
        r.err(f"YAML_PARSE: {e}")
        return r
    if not isinstance(doc, dict):
        r.err("YAML_SHAPE: top level must be a mapping")
        return r

    grain_vocab = set(doc.get("entity_grain_vocabulary") or {})
    if not grain_vocab:
        r.err("MISSING: entity_grain_vocabulary is empty or absent")
    types = doc.get("measurement_types")
    if not isinstance(types, dict) or not types:
        r.err("MISSING: measurement_types is empty or absent")
        return r
    keys = set(types)
    known_cards = _known_card_ids(cards_dir) if cards_dir else None

    for name, spec in types.items():
        if not isinstance(spec, dict):
            r.err(f"[{name}] type entry must be a mapping")
            continue
        if not spec.get("claim"):
            r.err(f"[{name}] missing `claim`")
        grains = spec.get("entity_grains") or []
        if not grains:
            r.err(f"[{name}] missing/empty `entity_grains` (the capability ceiling, Rule 5)")
        for g in grains:
            if g not in grain_vocab:
                r.err(f"[{name}] entity_grain `{g}` not in entity_grain_vocabulary")

        providers = spec.get("providers") or []
        if not providers:
            r.err(f"[{name}] has no providers (a type must declare at least one)")
        # Rule: >1 provider requires a conflict policy
        if len(providers) > 1 and spec.get("multi_provider_policy") not in VALID_POLICIES:
            r.err(f"[{name}] has {len(providers)} providers but no valid multi_provider_policy "
                  f"(need one of {sorted(VALID_POLICIES)}) — averaging/pick-one is forbidden (Rule 5)")
        if spec.get("multi_provider_policy") and spec["multi_provider_policy"] not in VALID_POLICIES:
            r.err(f"[{name}] multi_provider_policy `{spec['multi_provider_policy']}` invalid")

        for i, p in enumerate(providers):
            tier = p.get("evidence_tier")
            if tier not in VALID_TIERS:
                r.err(f"[{name}] provider #{i} evidence_tier `{tier}` invalid "
                      f"(mandatory; one of {sorted(VALID_TIERS)})")
            kind = p.get("kind")
            if kind == "derived_from":
                inputs = p.get("inputs") or []
                if not inputs:
                    r.err(f"[{name}] derived_from provider #{i} has no inputs")
                for inp in inputs:
                    if inp == name:
                        r.err(f"[{name}] derived_from input is self-referential")
                    elif inp not in keys:
                        r.err(f"[{name}] derived_from input `{inp}` is not a registered "
                              f"measurement_type (dangling DAG edge, Rule 4)")
            elif kind != "dataset":
                r.err(f"[{name}] provider #{i} kind `{kind}` must be `dataset` or `derived_from`")

        # Card back-refs resolve (only when cards/ is available)
        if known_cards is not None:
            for cid in spec.get("cards") or []:
                if cid not in known_cards:
                    r.err(f"[{name}] cards back-ref `{cid}` has no cards/{cid}.card.yaml")

    cyclic = _has_cycle(types)
    if cyclic:
        r.err(f"CYCLE: derived_from DAG has a cycle involving {cyclic}")

    return r


def _main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--vocab", type=Path,
                    default=Path(__file__).resolve().parent.parent
                    / "vocabularies" / "measurement_types.yaml")
    ap.add_argument("--cards", type=Path,
                    default=Path(__file__).resolve().parent.parent / "cards")
    args = ap.parse_args(argv)
    r = validate(args.vocab, args.cards)
    print("validate_measurement_types.py results:")
    for e in r.errors:
        print(f"  [ERROR]   {e}")
    for w in r.warnings:
        print(f"  [WARNING] {w}")
    types = (yaml.safe_load(args.vocab.read_text()) or {}).get("measurement_types") or {}
    print(f"\nSummary: {len(types)} measurement_type(s); "
          f"{'OK' if r.ok else str(len(r.errors)) + ' error(s)'}.")
    return 0 if r.ok else 1


if __name__ == "__main__":
    sys.exit(_main())
