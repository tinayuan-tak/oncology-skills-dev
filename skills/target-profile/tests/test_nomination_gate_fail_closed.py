"""Regression fixtures for the FAIL-CLOSED, GATE-COMPLETE nomination gate (roadmap §6.6).

The gate previously (a) FAILED OPEN — an unknown/renamed/malformed verdict on a veto-capable
axis returned None → a silent permissive pass; and (b) was not gate-complete — kill verdicts
outside the two vetoes were silently ignored. These tests pin the fix:

  * a RENAMED veto verdict on dependency no longer fails open — it routes to veto (least-permissive).
  * an UNKNOWN token on safety / subtype_fit aborts to the axis's least-permissive HOLD, never None.
  * a MALFORMED verdict tuple on a gating axis fails closed the same way (not a silent continue).
  * recognized benign verdicts (moderate safety, insufficient, positives) still return None.
  * an unknown token on a NON-gating axis (selectivity/surface/tractability) does NOT over-veto
    (F1-safe — those axes never force the recommendation).
  * the KRAS×COADREAD guard: a modality-scoped surface kill still does NOT blanket-veto.
  * the active veto set stays EXACTLY 2 (fallback registry) — no new vetoes were added.
  * the hard_gates status block enumerates the COMPLETE declared kill set with per-gate status.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_failclosed", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _sub(short, verdict, rule="some-rule"):
    return {short: {"verdict": (verdict, rule) if verdict else None}}


# --- (a) fail-OPEN is fixed: renamed / unknown / malformed never returns a silent None ---

def test_renamed_dependency_veto_does_not_fail_open():
    """A renamed veto token (`not_dependent` for the real `non_dependent`) must NOT slip through
    as a silent permissive pass — it routes to the dependency axis's least-permissive action: veto."""
    forced, hits, _sup = tp._gate_recommendation(_sub("dependency", "not_dependent"))
    assert forced == "veto"
    assert any(h.get("_fail_closed") and h["fail_closed_reason"] == "unrecognized_verdict"
               for h in hits)


def test_unknown_safety_token_routes_to_least_permissive_hold():
    forced, hits, _sup = tp._gate_recommendation(_sub("safety", "totally_new_safety_verdict"))
    assert forced == "hold"           # never None
    assert any(h.get("_fail_closed") for h in hits)


def test_unknown_subtype_token_routes_to_hold():
    forced, hits, _sup = tp._gate_recommendation(_sub("subtype_fit", "unheard_of_subtype_verdict"))
    assert forced == "hold"
    assert any(h.get("_fail_closed") for h in hits)


def test_malformed_verdict_tuple_on_gating_axis_fails_closed():
    # A bare string (not a (verdict, rule) tuple) on dependency → veto, not a silent continue.
    forced, hits, _sup = tp._gate_recommendation({"dependency": {"verdict": "a-bare-string"}})
    assert forced == "veto"
    assert any(h.get("_fail_closed") and h["fail_closed_reason"] == "malformed_verdict"
               for h in hits)
    # A dict-shaped garbled verdict on safety → hold.
    forced2, _h, _s = tp._gate_recommendation({"safety": {"verdict": {"oops": 1}}})
    assert forced2 == "hold"


# --- recognized benign verdicts still return None (no over-veto) ---

def test_recognized_benign_verdicts_do_not_fail_closed():
    assert tp._gate_recommendation(_sub("safety", "moderately_constrained_safety"))[0] is None
    assert tp._gate_recommendation(_sub("dependency", "insufficient"))[0] is None
    assert tp._gate_recommendation(_sub("dependency", "lineage_selective"))[0] is None
    assert tp._gate_recommendation(_sub("dependency", "non_dependent_paralog_buffered"))[0] is None


def test_empty_verdict_on_gating_axis_is_blind_not_failclosed():
    """An ABSENT verdict is a coverage gap, not a kill — must NOT be clamped (else every blind
    axis would veto)."""
    assert tp._gate_recommendation(_sub("dependency", None))[0] is None
    assert tp._gate_recommendation({"safety": {}})[0] is None


# --- (b) non-gating axes never force (F1-safe) ---

def test_unknown_token_on_non_gating_axis_does_not_over_veto():
    for axis in ("selectivity", "surface_modality", "tractability_sm", "genomic_alteration",
                 "mechanism", "expression"):
        forced, _h, _s = tp._gate_recommendation(_sub(axis, "some_brand_new_token"))
        assert forced is None, f"non-gating axis {axis} must not force a recommendation"


# --- the two real vetoes + KRAS guard still hold ---

def test_real_vetoes_still_fire():
    assert tp._gate_recommendation(_sub("dependency", "pan_essential_killer",
                                        "pan-essential-killer"))[0] == "veto"
    assert tp._gate_recommendation(_sub("dependency", "non_dependent",
                                        "non-dependent-killer"))[0] == "veto"


def test_real_safety_hold_still_fires():
    assert tp._gate_recommendation(_sub("safety", "highly_constrained_safety_concern"))[0] == "hold"


def test_kras_guard_modality_scoped_surface_kill_does_not_veto():
    """KRAS×COADREAD: a modality-scoped surface kill (neither_viable) alongside a real positive
    dependency must NOT blanket-veto — it forecloses a modality, not the target."""
    sr = {**_sub("dependency", "concordant_dependent", "concordant-dependent-supportive-dominant"),
          **_sub("surface_modality", "neither_viable", "s")}
    forced, _h, _s = tp._gate_recommendation(sr)
    assert forced is None


def test_veto_set_is_exactly_two_in_fallback_registry():
    """No new veto was introduced. The fallback (used when the vocab can't load) is the
    conservative-and-complete source of record — its veto arms are exactly the two killers."""
    veto = {k for k, action in tp._FALLBACK_GATE_VERDICTS.items() if action == "veto"}
    assert veto == {("dependency", "pan_essential_killer"), ("dependency", "non_dependent")}
    reg_veto = {k for k, disp in tp._FALLBACK_KILL_CAPABLE_VERDICTS.items()
                if disp == "gated" and tp._FALLBACK_GATE_VERDICTS.get(k) == "veto"}
    assert reg_veto == veto


# --- hard_gates: complete declared set with per-gate status ---

def test_hard_gates_enumerates_complete_declared_set_with_status():
    sr = {**_sub("dependency", "pan_essential_killer", "pan-essential-killer"),
          **_sub("safety", "moderately_constrained_safety"),
          **_sub("surface_modality", "neither_viable", "s")}
    action, hits, supp = tp._gate_recommendation(sr)
    hg = tp._hard_gates_status(sr, hits, supp)
    by_pair = {(r["short"], r["verdict"]): r for r in hg}
    # the whole fallback declared set is present (gate-complete)
    assert set(by_pair) >= set(tp._FALLBACK_KILL_CAPABLE_VERDICTS)
    # statuses are correct for this run
    assert by_pair[("dependency", "pan_essential_killer")]["status"] == "fired"
    assert by_pair[("surface_modality", "neither_viable")]["status"] == "excluded"
    # a declared gate on an axis with no verdict this run → blind (never silently dropped)
    assert by_pair[("subtype_fit", "subtype_specific_non_dependence")]["status"] == "blind"
    # a declared gate whose axis emitted a DIFFERENT verdict → latent (evaluated, dormant)
    assert by_pair[("safety", "highly_constrained_safety_concern")]["status"] == "latent"
    assert {r["status"] for r in hg} <= {"fired", "suppressed", "excluded", "opposing",
                                         "blind", "latent"}


def test_hard_gates_flags_fail_closed_fire():
    forced, hits, supp = tp._gate_recommendation(_sub("dependency", "renamed_token"))
    hg = tp._hard_gates_status(_sub("dependency", "renamed_token"), hits, supp)
    # the fail-closed clamp is recorded as a hit and forced the recommendation
    assert forced == "veto"
    assert any(h.get("_fail_closed") for h in hits)
