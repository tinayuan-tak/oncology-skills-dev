"""Guard for the nomination-gate VOCAB ↔ skills gating-constants coupling (arch-review R6 + R7).

tp_gates.py hardcodes three gating constants — _GATING_AXES, _RECOGNIZED_GATING_VERDICTS,
_GATING_AXIS_FAILCLOSED_ACTION — plus _GATE_ACTION_RANK. Adding a NEW veto/hold gate (or a new gating
verdict) to target-contracts/vocabularies/nomination_verdict_gate.yaml therefore requires a coordinated
hardcoded skills edit; if that edit is forgotten, the fail-closed guard silently degrades:

  R6: a vocab veto/hold whose sub_skill ∉ _GATING_AXES is NOT fail-closed-guarded — an unknown/renamed
      verdict on it returns a SILENT PERMISSIVE PASS (the exact failure §6.6 fail-closed was built to kill).
  R7: _GATE_ACTION_RANK duplicates the vocab's owner-editable `action_precedence`; a silent drift would
      change veto-vs-hold precedence without anyone noticing.

These tests make both couplings CI-enforced (fail on drift → conscious update). Verdict-inert (checks
only; no runtime change). The follow-on the review notes (have the loader READ action_precedence rather
than duplicate it) is optional — this guard makes the duplication safe until then.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import tp_gates  # noqa: E402

_VOCAB = tp_gates._CONTRACTS_REPO / "vocabularies" / "nomination_verdict_gate.yaml"


def _vocab() -> dict:
    return yaml.safe_load(_VOCAB.read_text())


def test_every_vocab_veto_hold_gate_is_in_skills_gating_constants():
    """R6: every vocab `gates` entry with action ∈ {veto, hold} must have its sub_skill in _GATING_AXES,
    its verdict in _RECOGNIZED_GATING_VERDICTS[sub_skill], and a fail-closed action — else an unknown
    verdict on that axis is a silent permissive pass."""
    gates = _vocab().get("gates", [])
    problems = []
    for g in gates:
        if g.get("action") not in ("veto", "hold"):
            continue
        ss, v = g["sub_skill"], g["verdict"]
        if ss not in tp_gates._GATING_AXES:
            problems.append(f"sub_skill {ss!r} (verdict {v!r}, action {g['action']}) NOT in _GATING_AXES")
            continue
        if v not in tp_gates._RECOGNIZED_GATING_VERDICTS.get(ss, frozenset()):
            problems.append(f"verdict {v!r} NOT in _RECOGNIZED_GATING_VERDICTS[{ss!r}]")
        if ss not in tp_gates._GATING_AXIS_FAILCLOSED_ACTION:
            problems.append(f"sub_skill {ss!r} has no _GATING_AXIS_FAILCLOSED_ACTION")
    assert not problems, (
        "vocab veto/hold gates drifted from the skills gating constants (add the missing sub_skill/verdict "
        "to tp_gates.py — a vocab-only gate is NOT fail-closed-guarded):\n  " + "\n  ".join(problems))


def test_gate_action_rank_matches_vocab_action_precedence():
    """R7: _GATE_ACTION_RANK is now LOADED from the vocab's owner-editable action_precedence (R7 follow-on),
    so the effective value must equal the vocab. AND the conservative _FALLBACK (used when the vocab is
    unreadable) must itself match the vocab — else a real vocab edit would silently diverge from the
    fallback-of-record that guards veto>hold when the file can't be read."""
    vocab_prec = {str(k): int(v) for k, v in (_vocab().get("action_precedence", {}) or {}).items()}
    assert dict(tp_gates._GATE_ACTION_RANK) == vocab_prec, (
        f"tp_gates._GATE_ACTION_RANK {dict(tp_gates._GATE_ACTION_RANK)} != vocab {vocab_prec} — the loader "
        f"did not pick up the vocab.")
    assert dict(tp_gates._FALLBACK_GATE_ACTION_RANK) == vocab_prec, (
        f"_FALLBACK_GATE_ACTION_RANK {dict(tp_gates._FALLBACK_GATE_ACTION_RANK)} drifted from vocab "
        f"{vocab_prec} — update the fallback so an unreadable-vocab run still ranks veto>hold correctly.")


def test_gating_constants_are_internally_complete():
    """Every _GATING_AXES member has both a recognized-verdicts set AND a fail-closed action (no half-
    declared gating axis that would KeyError or read an empty recognized set at runtime)."""
    for ax in tp_gates._GATING_AXES:
        assert ax in tp_gates._RECOGNIZED_GATING_VERDICTS, f"{ax} missing from _RECOGNIZED_GATING_VERDICTS"
        assert ax in tp_gates._GATING_AXIS_FAILCLOSED_ACTION, f"{ax} missing from _GATING_AXIS_FAILCLOSED_ACTION"
