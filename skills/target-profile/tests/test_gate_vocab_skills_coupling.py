"""Guard for the nomination-gate VOCAB ↔ skills gating-constants coupling.

tp_gates.py hardcodes three gating constants — _GATING_AXES, _RECOGNIZED_GATING_VERDICTS,
_GATING_AXIS_FAILCLOSED_ACTION — plus _GATE_ACTION_RANK. Adding a NEW veto/hold gate (or a new gating
verdict) to target-contracts/vocabularies/nomination_verdict_gate.yaml therefore requires a coordinated
hardcoded skills edit; if that edit is forgotten, the fail-closed guard silently degrades:

  A vocab veto/hold whose sub_skill ∉ _GATING_AXES is NOT fail-closed-guarded — an unknown/renamed
      verdict on it returns a SILENT PERMISSIVE PASS (the exact failure fail-closed was built to kill).
  _GATE_ACTION_RANK duplicates the vocab's owner-editable `action_precedence`; a silent drift would
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
    """Every vocab `gates` entry with action ∈ {veto, hold} must have its sub_skill in _GATING_AXES,
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
    """_GATE_ACTION_RANK is now LOADED from the vocab's owner-editable action_precedence,
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


def test_gating_axis_supportive_and_suppressor_verdicts_are_recognized():
    """A gating axis (subtype_fit/dependency/safety) can legitimately emit not only its veto/hold gate
    verdicts but also SUPPORTIVE positives and veto-SUPPRESSOR verdicts declared elsewhere in the vocab
    (positive_signals[_modality_scoped], veto_suppressors.when_present). Those must ALSO live in
    _RECOGNIZED_GATING_VERDICTS[axis] — otherwise the fail-closed recommendation gate reads a legitimate
    positive as an UNRECOGNIZED verdict and forces the axis's least-permissive action. This is the
    KRAS/COADREAD --subtypes regression (2026-09-02): subtype_fit:subtype_restricted_dependency (a
    supportive positive + veto-suppressor, NOT in the gates block) was absent from the recognized set,
    so every subtype-tier positive fail-closed to `hold`. The pre-existing coupling test only scanned
    the `gates` block, so it could not catch a non-gate verdict."""
    v = _vocab()
    gating = tp_gates._GATING_AXES
    referenced: set[tuple[str, str]] = set()
    for block in ("positive_signals", "positive_signals_modality_scoped"):
        for e in (v.get(block) or []):
            if isinstance(e, dict) and e.get("sub_skill") in gating and e.get("verdict"):
                referenced.add((e["sub_skill"], e["verdict"]))
    for s in (v.get("veto_suppressors") or []):
        for wp in (s.get("when_present") or []):
            if isinstance(wp, dict) and wp.get("sub_skill") in gating and wp.get("verdict"):
                referenced.add((wp["sub_skill"], wp["verdict"]))
    missing = [f"{ss}:{vd}" for (ss, vd) in sorted(referenced)
               if vd not in tp_gates._RECOGNIZED_GATING_VERDICTS.get(ss, frozenset())]
    assert not missing, (
        "vocab declares supportive/suppressor verdicts for gating axes that are NOT in "
        "_RECOGNIZED_GATING_VERDICTS — the recommendation gate will fail-closed (force hold/veto) on "
        "them (add each to tp_gates.py):\n  " + "\n  ".join(missing))


def test_gating_constants_are_internally_complete():
    """Every _GATING_AXES member has both a recognized-verdicts set AND a fail-closed action (no half-
    declared gating axis that would KeyError or read an empty recognized set at runtime)."""
    for ax in tp_gates._GATING_AXES:
        assert ax in tp_gates._RECOGNIZED_GATING_VERDICTS, f"{ax} missing from _RECOGNIZED_GATING_VERDICTS"
        assert ax in tp_gates._GATING_AXIS_FAILCLOSED_ACTION, f"{ax} missing from _GATING_AXIS_FAILCLOSED_ACTION"
