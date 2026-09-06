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


def test_subtype_fit_emitter_tokens_are_recognized_and_declared_in_vocab():
    """Close the ONE seam the other coupling guards miss: the subtype_fit EMITTER.

    subtype_fit is a GATING axis with NO resolver — its verdict is emitted in-code by
    tp_fanout._subtype_verdict, so target-contracts' validate_verdict_tokens skips it, and the tests
    above only scan the vocab↔tp_gates coupling. Nothing cross-checks the *emitter's* actual tokens.
    An emitter-only rename (e.g. subtype_specific_non_dependence → a new spelling) that misses
    _RECOGNIZED_GATING_VERDICTS would make the recommendation gate read the live token as UNRECOGNIZED
    and fail-close to `hold` — silently disabling the subtype-specific-non-dependence HOLD for a target
    with a measured subtype dependency gap. This guards the emitter against exactly that drift.

    Drive the emitter with synthetic fired-sets so the tokens are its ACTUAL output (ground truth),
    then assert every emitted token is (1) in _RECOGNIZED_GATING_VERDICTS[subtype_fit] and (2) declared
    somewhere in the gate vocab (gates / kill_capable_verdicts / positive_signals / veto_suppressors)."""
    import tp_fanout  # noqa: E402  (SCRIPTS already on sys.path)

    hold = tp_fanout._subtype_verdict(
        [{"tier": "subtype", "signals": {"subtype_fit_genomic": "opposing"}, "rule_id": "r-neg"}])
    positive = tp_fanout._subtype_verdict(
        [{"tier": "subtype", "signals": {"subtype_fit_genomic": "supportive"}, "rule_id": "r-pos"}])
    assert hold and positive, "emitter did not produce both subtype_fit tokens — stale test fixture"
    emitted = {hold[0], positive[0]}
    short = tp_fanout.SUBTYPE_SHORT  # "subtype_fit"

    # (1) emitter ↔ recognized set (pure skills; no vocab needed)
    recognized = tp_gates._RECOGNIZED_GATING_VERDICTS.get(short, frozenset())
    assert emitted <= recognized, (
        f"tp_fanout._subtype_verdict emits {sorted(emitted - recognized)} NOT in "
        f"_RECOGNIZED_GATING_VERDICTS[{short!r}] — the recommendation gate will fail-close (hold) on it. "
        f"Update tp_gates.py to match the emitter.")

    # (2) emitter ↔ gate vocab: every emitted token must be declared for this axis somewhere.
    v = _vocab()
    declared: set[str] = set()
    for g in (v.get("gates") or []):
        if g.get("sub_skill") == short and g.get("verdict"):
            declared.add(g["verdict"])
    for e in ((v.get("kill_capable_verdicts") or {}).get(short) or []):
        if isinstance(e, dict) and e.get("verdict"):
            declared.add(e["verdict"])
    for block in ("positive_signals", "positive_signals_modality_scoped"):
        for e in (v.get(block) or []):
            if isinstance(e, dict) and e.get("sub_skill") == short and e.get("verdict"):
                declared.add(e["verdict"])
    for s in (v.get("veto_suppressors") or []):
        for wp in (s.get("when_present") or []):
            if isinstance(wp, dict) and wp.get("sub_skill") == short and wp.get("verdict"):
                declared.add(wp["verdict"])
    missing = emitted - declared
    assert not missing, (
        f"tp_fanout._subtype_verdict emits {sorted(missing)} that the gate vocab never declares for "
        f"{short!r} (gates/kill_capable_verdicts/positive_signals/veto_suppressors) — an emitted token no "
        f"gate rule references. Add it to nomination_verdict_gate.yaml or fix the emitter.")
