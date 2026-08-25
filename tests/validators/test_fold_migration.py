"""M3 completion guard — every resolver is folded (match_all_reduce with unique per-rung priorities),
so the interpreter's first_match path is retired to a test oracle and cannot silently regress."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validators"))
import validate_fold_migration as vfm  # noqa: E402


def test_all_resolvers_are_folded():
    ok, errs = vfm.validate(ROOT / "resolvers")
    assert ok, "Fold migration regressed:\n  " + "\n  ".join(errs)


def test_guard_catches_a_first_match_regression(tmp_path):
    (tmp_path / "x.resolver.yaml").write_text(
        "gate: x\nversion: 1.0.0\nresolve:\n  - {verdict: a, when_fired: r}\ndefault: none\n")
    ok, errs = vfm.validate(tmp_path)
    assert not ok and any("match_all_reduce" in e for e in errs)


def test_guard_catches_duplicate_priority(tmp_path):
    (tmp_path / "x.resolver.yaml").write_text(
        "gate: x\nversion: 1.0.0\nevaluation: match_all_reduce\nresolve:\n"
        "  - {verdict: a, when_fired: r1, priority: 0}\n"
        "  - {verdict: b, when_fired: r2, priority: 0}\ndefault: none\n")
    ok, errs = vfm.validate(tmp_path)
    assert not ok and any("duplicate" in e.lower() for e in errs)
