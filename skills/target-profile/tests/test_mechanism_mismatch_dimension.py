"""CASE-018 / CASE-027-D1 (veto half): the dependency-axis mechanism_mismatch DIMENSION.

`_mechanism_mismatch_dimension` names -- VERDICT-INERT -- that a whole-gene-KO dependency scalar
is the wrong estimator for this target's mechanism class, when the gate has ALREADY dropped a
dependency veto as irrelevant to the thesis (thesis_irrelevant_axis, Step 2b). It reads the
resolved suppression state and forces nothing.

These pin both halves, driving through the REAL `_gate_recommendation` (not a hand-built
suppression list, which would be a tautology):
  * FIRES exactly when the gate judged dependency irrelevant to the thesis (faithfulness);
  * for EVERY thesis the vocab drops the dependency veto for -- and never invents one where the
    veto stood (oncogene_addiction / no thesis);
  * NEVER silent on a real drop (an unmapped thesis still gets an honest generic note);
  * touches no forced action (verdict-inert).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run")

# The canonical theses this dimension names, with their expected mechanism-class label.
_MAPPED = {
    "antigen_driven": "surface_antigen_engagement",
    "tme_io": "tumor_microenvironment_immune_modulation",
    "neomorphic_gof": "neomorphic_gain_of_function",
    "partner_conditional_sl": "synthetic_lethal_partner_conditional",
}


def _dep(verdict, rule="dep-rule"):
    return {"dependency": {"verdict": (verdict, rule)}}


def _theses_that_drop_dependency():
    """The theses the LIVE vocab (thesis_axis_relevance) drops a dependency veto for -- the exact
    population this dimension must name. Read dynamically so the test tracks the contract."""
    rel = tp._load_thesis_axis_relevance()
    return {th for th, pairs in rel.items() if any(s == "dependency" for (s, _v) in pairs)}


# --- FIRES: through the real gate -------------------------------------------


def test_fires_on_a_thesis_dropped_dependency_veto():
    subs = _dep("non_dependent")
    forced, _hits, sup = tp._gate_recommendation(subs, thesis="antigen_driven")
    assert forced is None  # the veto was DROPPED as irrelevant -> no forced decline
    dim = tp._mechanism_mismatch_dimension(sup, "antigen_driven")
    assert dim is not None
    assert dim["kind"] == "dependency_axis_mechanism_mismatch"
    assert dim["authoritative"] == "verdict"
    assert dim["axis"] == "dependency"
    assert dim["estimator"] == "whole_gene_ko_dependency_scalar"
    assert dim["thesis"] == "antigen_driven"
    assert dim["mechanism_class"] == "surface_antigen_engagement"
    assert dim["dropped_verdicts"] == ["non_dependent"]
    assert dim["adjudicated_on"]
    assert "WRONG ESTIMATOR" in dim["note"]
    assert "authoritative and unchanged" in dim["note"]


def test_fires_for_every_vocab_dropped_thesis_and_is_never_silent():
    """Anti-vacuity + faithfulness: the dimension fires for the WHOLE vocab drop-set, and every
    fire carries a non-empty note (never silent on a real drop, even for an unmapped thesis)."""
    drop_theses = _theses_that_drop_dependency()
    assert drop_theses, "vocab yielded no dependency-dropping theses (load regression)"
    for th in drop_theses:
        forced, _hits, sup = tp._gate_recommendation(_dep("non_dependent"), thesis=th)
        assert forced is None, f"{th}: veto not dropped"
        dim = tp._mechanism_mismatch_dimension(sup, th)
        assert dim is not None, f"{th}: dimension did not fire on a real drop"
        assert dim["note"], f"{th}: empty note"
        assert dim["thesis"] == th
        # the 4 canonical theses map to their specific mechanism-class label
        if th in _MAPPED:
            assert dim["mechanism_class"] == _MAPPED[th], f"{th}: wrong class"


def test_fires_on_indication_conditioned_drop():
    """thesis_axis_relevance also drops `not_dependent_in_indication` -- the dimension names it too."""
    forced, _hits, sup = tp._gate_recommendation(_dep("not_dependent_in_indication"), thesis="neomorphic_gof")
    if not sup:  # vocab may not carry the in-indication grain in this checkout -> nothing to name
        return
    assert forced is None
    dim = tp._mechanism_mismatch_dimension(sup, "neomorphic_gof")
    assert dim is not None
    assert "not_dependent_in_indication" in dim["dropped_verdicts"]


# --- SILENT: no mismatch to name --------------------------------------------


def test_silent_when_the_veto_survives():
    """oncogene_addiction is NOT in the drop-set -> dependency DID adjudicate -> no mismatch."""
    forced, _hits, sup = tp._gate_recommendation(_dep("non_dependent"), thesis="oncogene_addiction")
    assert forced == "veto"
    assert tp._mechanism_mismatch_dimension(sup, "oncogene_addiction") is None


def test_silent_when_no_thesis():
    forced, _hits, sup = tp._gate_recommendation(_dep("non_dependent"), thesis=None)
    assert forced == "veto"
    assert tp._mechanism_mismatch_dimension(sup, None) is None


def test_silent_when_dependency_is_favorable_no_veto_fired():
    """A favorable dependency read fires no veto, so there is no drop to name."""
    _forced, _hits, sup = tp._gate_recommendation(_dep("partner_conditional_dependent"), thesis="antigen_driven")
    assert tp._mechanism_mismatch_dimension(sup, "antigen_driven") is None


def test_silent_on_a_non_thesis_suppression():
    """A suppression of a DIFFERENT kind (e.g. modality_scoped) is not a mechanism mismatch."""
    sup = [{"short": "dependency", "verdict": "non_dependent", "suppressed_by": {"kind": "modality_scoped"}}]
    assert tp._mechanism_mismatch_dimension(sup, "antigen_driven") is None


# --- ROBUSTNESS + never-silent fallback -------------------------------------


def test_unmapped_thesis_still_emits_an_honest_generic_note():
    """A thesis dropped by the vocab but absent from _THESIS_MECHANISM_CLASS must NOT go silent:
    it emits a generic note keyed on the thesis name (the never-silent fallback)."""
    sup = [
        {
            "short": "dependency",
            "verdict": "non_dependent",
            "suppressed_by": {"kind": "thesis_irrelevant_axis", "thesis": "some_future_thesis"},
        }
    ]
    dim = tp._mechanism_mismatch_dimension(sup, "some_future_thesis")
    assert dim is not None
    assert dim["thesis"] == "some_future_thesis"
    assert dim["mechanism_class"] == "some_future_thesis"  # falls back to the thesis name
    assert dim["adjudicated_on"]  # generic currency phrase, non-empty
    assert dim["note"]


def test_robust_to_malformed_suppression_records():
    """A garbled suppression must not crash the dimension (fail-closed)."""
    for bad in ([{"short": "dependency"}], [{"suppressed_by": "not-a-dict"}], [{}], ["bare-string"]):
        assert tp._mechanism_mismatch_dimension(bad, "antigen_driven") is None


def test_reads_thesis_off_the_record_when_arg_absent():
    """The recorded thesis on the drop is authoritative; the dimension resolves it even if the
    caller does not thread the thesis argument."""
    sup = [
        {
            "short": "dependency",
            "verdict": "non_dependent",
            "suppressed_by": {"kind": "thesis_irrelevant_axis", "thesis": "antigen_driven"},
        }
    ]
    dim = tp._mechanism_mismatch_dimension(sup, None)
    assert dim is not None
    assert dim["thesis"] == "antigen_driven"
    assert dim["mechanism_class"] == "surface_antigen_engagement"


def test_does_not_mutate_the_suppressions_input():
    subs = _dep("non_dependent")
    _forced, _hits, sup = tp._gate_recommendation(subs, thesis="antigen_driven")
    before = [dict(s) for s in sup]
    tp._mechanism_mismatch_dimension(sup, "antigen_driven")
    assert sup == before  # pure read, no mutation
