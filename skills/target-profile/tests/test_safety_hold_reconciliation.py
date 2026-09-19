"""CASE-015: signal<->verdict reconciliation note (VERDICT-INERT).

`_safety_hold_reconciliation` surfaces the divergence when a constrained-gene safety hold is
the deciding call while the dependency axis reads AFFIRMATIVELY favorable. It reads the
already-resolved gate state and forces NOTHING -- these tests pin both halves: it fires on the
real divergence (through the actual `_gate_recommendation` path, not a hand-built hit list), it
stays silent on every near-miss, and it never perturbs the forced action.

Design contract (docs/UNIFIED_OUTPUT_CONTRACT.md, signal<->verdict reconciliation):
  * the verdict is AUTHORITATIVE and unchanged; the note is explicitly subordinate;
  * "favorable" means the framework's OWN positive_map (nomination_verdict_gate.yaml), not
    merely non-veto -- `insufficient`/`non_dependent`/`broadly_dependent` are non-veto but NOT
    favorable, and labelling them favorable would be a self-contradictory consumer claim.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run")


def _sub(short, verdict, rule="some-rule"):
    return {short: {"verdict": (verdict, rule) if verdict else None}}


def _merge(*dicts):
    out = {}
    for d in dicts:
        out.update(d)
    return out


_CONSTRAINED = "highly_constrained_safety_concern"
# A representative affirmatively-favorable dependency verdict (in the framework's positive_map).
_FAVORABLE_DEP = "partner_conditional_dependent"


def _favorable_dependency_verdicts():
    pos_map, _c, _cfg, _s = tp._load_positive_signals()
    return {v for (s, v) in pos_map if s == "dependency"}


# --- FIRES: the genuine CASE-015 divergence ---------------------------------


def test_fires_on_constrained_safety_hold_vs_favorable_dependency():
    subs = _merge(_sub("safety", _CONSTRAINED, "hc"), _sub("dependency", _FAVORABLE_DEP, "dep"))
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert forced == "hold"  # safety hold is the deciding call, no veto dominates
    note = tp._safety_hold_reconciliation(forced, hits, subs)
    assert note is not None
    assert note["kind"] == "conservative_safety_hold_vs_favorable_dependency"
    assert note["authoritative"] == "verdict"  # verdict stays authoritative
    assert note["held_verdicts"] == [_CONSTRAINED]
    assert note["divergent_signal"] == {"axis": "dependency", "verdict": _FAVORABLE_DEP}
    assert note["unmodeled"] == "context_conditional_normal_tissue_tolerance"
    assert note["would_lift"] == "demonstrated_selectivity_or_context_window"
    # the note names the lift path and does not contradict the hold
    assert "authoritative and unchanged" in note["note"]
    assert _FAVORABLE_DEP in note["note"]


def test_fires_on_every_framework_favorable_dependency_verdict():
    """Anti-vacuity + faithfulness: fires for the WHOLE favorable set, and ONLY that set."""
    favorable = _favorable_dependency_verdicts()
    assert favorable, "positive_map yielded no favorable dependency verdicts (load regression)"
    fired = set()
    for dv in tp._RECOGNIZED_GATING_VERDICTS.get("dependency", frozenset()):
        subs = _merge(_sub("safety", _CONSTRAINED, "hc"), _sub("dependency", dv, "dep"))
        forced, hits, _sup = tp._gate_recommendation(subs)
        if tp._safety_hold_reconciliation(forced, hits, subs) is not None:
            fired.add(dv)
    # exactly the framework's favorable set that is ALSO gate-recognized and non-gating
    assert fired == {v for v in favorable if v in tp._RECOGNIZED_GATING_VERDICTS.get("dependency", frozenset())}


def test_fires_for_all_constrained_gene_safety_concerns():
    """Every member of _SAFETY_WT_LOSS_CONCERNS that forces a hold must be annotatable."""
    for concern in tp._SAFETY_WT_LOSS_CONCERNS:
        subs = _merge(_sub("safety", concern, "sc"), _sub("dependency", _FAVORABLE_DEP, "dep"))
        forced, hits, _sup = tp._gate_recommendation(subs)
        if forced == "hold" and any(h["short"] == "safety" for h in hits):
            note = tp._safety_hold_reconciliation(forced, hits, subs)
            assert note is not None, f"no note for surviving constrained concern {concern}"
            assert concern in note["held_verdicts"]


# --- DOES NOT FIRE: every near-miss -----------------------------------------


def test_no_note_when_dependency_veto_dominates():
    """A dominating veto is NOT a conservative hold -> never annotate as 'a window would lift'."""
    subs = _merge(_sub("safety", _CONSTRAINED, "hc"), _sub("dependency", "non_dependent", "nd"))
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert forced == "veto"
    assert tp._safety_hold_reconciliation(forced, hits, subs) is None


def test_no_note_when_dependency_insufficient():
    """`insufficient` is underpowered, NOT favorable -> no false 'favorable' claim."""
    subs = _merge(_sub("safety", _CONSTRAINED, "hc"), _sub("dependency", "insufficient", "ins"))
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert forced == "hold"
    assert tp._safety_hold_reconciliation(forced, hits, subs) is None


def test_no_note_when_dependency_broadly_dependent():
    """`broadly_dependent` is a CONTRADICTION (broad essentiality = liability), not favorable."""
    subs = _merge(_sub("safety", _CONSTRAINED, "hc"), _sub("dependency", "broadly_dependent", "bd"))
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert tp._safety_hold_reconciliation(forced, hits, subs) is None


def test_no_note_when_dependency_blind():
    """A coverage gap is not a favorable read -- do not manufacture a divergence from absence."""
    subs = _merge(_sub("safety", _CONSTRAINED, "hc"), {"dependency": {"verdict": None}})
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert tp._safety_hold_reconciliation(forced, hits, subs) is None
    # dependency axis entirely absent
    subs2 = _sub("safety", _CONSTRAINED, "hc")
    forced2, hits2, _s2 = tp._gate_recommendation(subs2)
    assert tp._safety_hold_reconciliation(forced2, hits2, subs2) is None


def test_no_note_when_hold_is_not_a_constrained_gene_safety_concern():
    """A subtype-fit hold is not a WT-loss safety concern -> not this note's subject."""
    subs = _merge(
        _sub("subtype_fit", "subtype_specific_non_dependence", "sf"),
        _sub("dependency", _FAVORABLE_DEP, "dep"),
    )
    forced, hits, _sup = tp._gate_recommendation(subs)
    if forced == "hold":
        assert tp._safety_hold_reconciliation(forced, hits, subs) is None


# --- VERDICT-INERTNESS: forces nothing --------------------------------------


def test_note_never_changes_forced_action():
    """The note is a pure read of gate state: computing it must not alter `forced`."""
    for dv in tp._RECOGNIZED_GATING_VERDICTS.get("dependency", frozenset()):
        subs = _merge(_sub("safety", _CONSTRAINED, "hc"), _sub("dependency", dv, "dep"))
        forced_before, hits, _sup = tp._gate_recommendation(subs)
        tp._safety_hold_reconciliation(forced_before, hits, subs)
        forced_after, _h2, _s2 = tp._gate_recommendation(subs)
        assert forced_before == forced_after
