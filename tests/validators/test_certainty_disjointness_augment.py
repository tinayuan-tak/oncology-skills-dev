"""Hardening guards for validate_certainty_disjointness (2026-08-24): verdict_precedence_augment must
(a) count Python-applied veto cards as verdict-precedence (closing the resolver-only blind spot), and
(b) let a no-resolver inline-verdict gate declare its precedence set (instead of erroring)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("vcd", REPO / "validators" / "validate_certainty_disjointness.py")
vcd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vcd)


def _mk(root: Path, *, resolvers: dict, rules: list, manifest: dict):
    (root / "resolvers").mkdir(parents=True, exist_ok=True)
    (root / "interpretation-rules").mkdir(parents=True, exist_ok=True)
    (root / "vocabularies").mkdir(parents=True, exist_ok=True)
    for gate, spec in resolvers.items():
        (root / "resolvers" / f"{gate}.resolver.yaml").write_text(yaml.safe_dump(spec))
    (root / "interpretation-rules" / "x.rules.yaml").write_text(yaml.safe_dump({"rules": rules}))
    (root / "vocabularies" / "certainty_corroboration.yaml").write_text(yaml.safe_dump(manifest))


def test_augment_card_counts_as_verdict_precedence(tmp_path):
    # 'window-card' drives the verdict via a PYTHON veto (not in the resolver). Declared in augment →
    # naming it as corroboration must now be caught as a disjointness VIOLATION.
    _mk(
        tmp_path,
        resolvers={"sel": {"default": "x", "resolve": [{"when_fired": "r1", "verdict": "v"}]}},
        rules=[{"rule_id": "r1", "when": {"card_id": "verdict-card"}, "signals": {}}],
        manifest={
            "corroboration_by_gate": {"sel": ["window-card"]},
            "verdict_precedence_augment": {"sel": ["window-card"]},
        },
    )
    errors = vcd.validate(tmp_path)
    assert any("DISJOINTNESS VIOLATION" in e and "window-card" in e for e in errors), errors


def test_no_resolver_gate_with_augment_is_checked_not_errored(tmp_path):
    # inline-verdict gate (no resolver) + augment precedence; corroborator disjoint from it → clean.
    _mk(
        tmp_path,
        resolvers={},
        rules=[],
        manifest={
            "corroboration_by_gate": {"presence": ["corrob-card"]},
            "verdict_precedence_augment": {"presence": ["verdict-card-a", "verdict-card-b"]},
        },
    )
    assert vcd.validate(tmp_path) == []


def test_no_resolver_gate_without_augment_errors(tmp_path):
    _mk(tmp_path, resolvers={}, rules=[], manifest={"corroboration_by_gate": {"presence": ["corrob-card"]}})
    errors = vcd.validate(tmp_path)
    assert any("no verdict_precedence_augment" in e for e in errors), errors
