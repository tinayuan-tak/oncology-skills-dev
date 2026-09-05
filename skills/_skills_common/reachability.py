"""Resolver reachability — the VERDICT-RELEVANT card set for a gate.

A resolver-backed skill's verdict = ``resolve_verdict_for_gate(fired, gate)``, which pattern-matches
ONLY the rule_ids its resolver's rungs reference (``when_fired`` / ``when_any_fired`` /
``when_all_fired``). So the cards whose rules the resolver references are exactly the cards that can
MOVE the verdict; every other card a skill consumes is verdict-inert enrichment (feeds
narrative/facets, not the verdict).

``verdict_relevant_cards(gate)`` computes that set from the resolver spec + interpretation-rules. It
is the safe basis for a "lean" / ``--verdict-only`` read path: resolving ONLY these cards yields a
verdict byte-identical to resolving the full card set, because ``resolve_verdict_for_gate`` ignores
fired rules whose rule_id no rung references.

This is the RUNTIME twin of the composer guard
``target-profile/tests/test_composer_card_manifest_consistency.py`` (``_rule_id_to_card`` /
``_resolver_rule_ids``), which pins the identical rule_id->card + resolver-rule-id derivation. Path
resolution mirrors ``resolver.py`` / ``rules_loader.py`` (env-var ``TARGET_CONTRACTS_ROOT`` first,
local sibling fallback) — never a bare hardcoded path.

SAFETY CONTRACT: an empty return means "cannot prove a lean set" (resolver absent, or a referenced
rule_id has no card mapping) — callers MUST treat empty as "read ALL cards", never "read nothing".
Callers should additionally assert ``verdict_relevant_cards(gate) <= set(skill_CARDS)`` (a lean set
must be a subset of what the skill declares); the shipped guard test enforces this per gate.
"""
from __future__ import annotations

import functools
import os
from pathlib import Path

import yaml

from _skills_common.paths import target_contracts_root

_CONTRACTS_REPO = target_contracts_root()


def _root(contracts_repo: Path | None) -> Path:
    return Path(contracts_repo) if contracts_repo is not None else _CONTRACTS_REPO


@functools.lru_cache(maxsize=8)
def _rule_id_to_card(root: Path) -> dict:
    """{rule_id: card_id} across every interpretation-rules file (a rule's ``when.card_id``)."""
    out: dict[str, str] = {}
    rules_dir = root / "interpretation-rules"
    if not rules_dir.is_dir():
        return out
    for f in sorted(rules_dir.glob("*.rules.yaml")):
        doc = yaml.safe_load(f.read_text()) or {}
        for r in doc.get("rules", []) or []:
            when = r.get("when") or {}
            if r.get("rule_id") and isinstance(when, dict) and when.get("card_id"):
                out[r["rule_id"]] = when["card_id"]
    return out


def resolver_referenced_rule_ids(gate: str, contracts_repo: Path | None = None) -> set:
    """Every rule_id a gate's resolver references (``when_fired`` / ``when_any_fired`` /
    ``when_all_fired``). Empty set if the resolver spec is absent."""
    path = _root(contracts_repo) / "resolvers" / f"{gate}.resolver.yaml"
    if not path.exists():
        return set()
    spec = yaml.safe_load(path.read_text()) or {}
    rids: set[str] = set()
    for rung in spec.get("resolve", []) or []:
        if "when_fired" in rung:
            rids.add(rung["when_fired"])
        for key in ("when_any_fired", "when_all_fired"):
            rids.update(rung.get(key, []) or [])
    return rids


def verdict_relevant_cards(gate: str, contracts_repo: Path | None = None) -> set:
    """card_ids whose rules the gate's resolver references — the cards that can MOVE the verdict.

    Resolving only these yields a byte-identical verdict. Returns EMPTY if the resolver is absent OR
    any referenced rule_id has no ``when.card_id`` mapping (i.e. the derivation is incomplete and a
    lean set can't be proven safe) — the caller must then read ALL cards. See module SAFETY CONTRACT.
    """
    root = _root(contracts_repo)
    rids = resolver_referenced_rule_ids(gate, contracts_repo)
    if not rids:
        return set()
    r2c = _rule_id_to_card(root)
    # If any referenced rule_id is unmapped, we cannot guarantee completeness -> refuse to lean.
    if any(rid not in r2c for rid in rids):
        return set()
    return {r2c[rid] for rid in rids}
