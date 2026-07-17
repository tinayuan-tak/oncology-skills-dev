"""Tests for the deterministic recommendation gate in target-profile/run.py.

The gate forces overall_recommendation from killer sub-verdicts regardless of
what the LLM chose. These tests exercise the pure `_gate_recommendation` helper
(no Bedrock) + the clamp semantics.

Key correctness property (from the KRAS×COADREAD golden): modality-scoped killers
(surface neither_viable, degrader expression killers) must NOT force a blanket
veto — KRAS hits those yet is a correct `nominate` via small molecule.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load_run_module():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load_run_module()


def _sub(short, verdict, rule="some-rule"):
    return {short: {"verdict": (verdict, rule) if verdict else None}}


def _merge(*dicts):
    out = {}
    for d in dicts:
        out.update(d)
    return out


def test_pan_essential_killer_forces_veto():
    subs = _sub("dependency", "pan_essential_killer", "pan-essential-killer")
    forced, hits = tp._gate_recommendation(subs)
    assert forced == "veto"
    assert len(hits) == 1 and hits[0]["short"] == "dependency"
    assert hits[0]["driving_rule_id"] == "pan-essential-killer"


def test_non_dependent_forces_veto():
    forced, hits = tp._gate_recommendation(_sub("dependency", "non_dependent", "non-dependent-killer"))
    assert forced == "veto"


def test_safety_concern_forces_hold_not_veto():
    forced, hits = tp._gate_recommendation(
        _sub("safety", "highly_constrained_safety_concern", "highly-constrained-safety-warning"))
    assert forced == "hold"


def test_kras_pattern_no_override():
    """KRAS: dependency=lineage_selective (not a killer), surface=neither_viable
    (modality-scoped, excluded). The gate must NOT fire — LLM's nominate stands."""
    subs = _merge(
        _sub("dependency", "lineage_selective", "lineage-selective-supportive"),
        _sub("surface_modality", "neither_viable", "neither-viable-killer"),
        _sub("expression", "broadly_low_expression", "expression-broadly-low-degrader-killer"),
    )
    forced, hits = tp._gate_recommendation(subs)
    assert forced is None
    assert hits == []


def test_veto_dominates_hold_when_both_fire():
    subs = _merge(
        _sub("dependency", "pan_essential_killer", "pan-essential-killer"),
        _sub("safety", "highly_constrained_safety_concern", "highly-constrained-safety-warning"),
    )
    forced, hits = tp._gate_recommendation(subs)
    assert forced == "veto"
    assert len(hits) == 2


def test_no_verdict_and_none_verdict_ignored():
    subs = _merge(
        {"selectivity": {"verdict": None}},          # sub-skill with no verdict fn
        _sub("dependency", "concordant_dependent"),  # supportive, not a gate
    )
    forced, hits = tp._gate_recommendation(subs)
    assert forced is None and hits == []


def test_loader_reads_vocab_when_present(tmp_path):
    """_load_gate_verdicts reads the target-contracts vocab and returns source='vocab'."""
    vocab_dir = tmp_path / "vocabularies"; vocab_dir.mkdir()
    (vocab_dir / "nomination_verdict_gate.yaml").write_text(
        "gates:\n"
        "  - {sub_skill: dependency, verdict: pan_essential_killer, action: veto}\n"
        "  - {sub_skill: safety, verdict: highly_constrained_safety_concern, action: hold}\n"
    )
    mapping, source = tp._load_gate_verdicts(contracts_repo=tmp_path)
    assert source == "vocab"
    assert mapping[("dependency", "pan_essential_killer")] == "veto"
    assert mapping[("safety", "highly_constrained_safety_concern")] == "hold"


def test_loader_falls_back_conservatively_on_missing_vocab(tmp_path):
    """SAFETY: a missing vocab returns the hardcoded conservative set, NOT empty."""
    mapping, source = tp._load_gate_verdicts(contracts_repo=tmp_path / "nonexistent")
    assert source == "fallback"
    assert mapping == tp._FALLBACK_GATE_VERDICTS
    # the pan-essential veto MUST survive the fallback (never permissive)
    assert mapping[("dependency", "pan_essential_killer")] == "veto"


def test_loader_falls_back_on_malformed_vocab(tmp_path):
    vocab_dir = tmp_path / "vocabularies"; vocab_dir.mkdir()
    (vocab_dir / "nomination_verdict_gate.yaml").write_text("gates: []\n")  # empty → invalid
    mapping, source = tp._load_gate_verdicts(contracts_repo=tmp_path)
    assert source == "fallback"
    assert ("dependency", "pan_essential_killer") in mapping


def test_gate_uses_fallback_when_vocab_absent(tmp_path):
    """End-to-end: with no vocab, the gate still vetoes a pan-essential killer."""
    subs = _sub("dependency", "pan_essential_killer", "pan-essential-killer")
    forced, hits = tp._gate_recommendation(subs, contracts_repo=tmp_path / "nope")
    assert forced == "veto"
    assert hits[0]["policy_source"] == "fallback"


def test_clamp_semantics_on_wrapped_output():
    """Simulate the run.py clamp: a killer forces veto over an LLM 'nominate',
    preserving the wrapped {value, _source, ...} shape + marking _gated."""
    llm_output = {"overall_recommendation": {"value": "nominate", "_source": "llm_synthesized",
                                             "_model_id": "x", "_prompt_hash": "y"}}
    subs = _sub("dependency", "pan_essential_killer", "pan-essential-killer")
    gate_action, gate_hits = tp._gate_recommendation(subs)
    assert gate_action == "veto"
    # replicate the clamp block
    rec = llm_output["overall_recommendation"]
    llm_value = rec["value"]
    rec["value"] = gate_action
    rec["_gated"] = True
    assert llm_output["overall_recommendation"]["value"] == "veto"
    assert llm_output["overall_recommendation"]["_gated"] is True
    assert llm_value == "nominate"  # original preserved for the override record


# ---------------------------------------------------------------------------
# Verdict-affecting subtype tier (2026-07-17)
# ---------------------------------------------------------------------------

def _dep_card(rows):
    """A synthetic subgroup-stratified-dependency card_output carrying rows."""
    return [{"card_id": "subgroup-stratified-dependency",
             "summary": {"per_subgroup_metrics": rows},
             "interpretation_call": "x"}]


_MEASURED_NONDEP = {"stratum": "SUBTYPE_A", "class": "not_dependent",
                    "evidence_state": "measured", "subgroup_n": 50,
                    "subgroup_n_floor_met": True, "median_chronos": -0.1}
_UNDERPOWERED_NONDEP = {"stratum": "SUBTYPE_A", "class": "not_dependent",
                        "evidence_state": "underpowered", "subgroup_n": 17,
                        "subgroup_n_floor_met": False, "median_chronos": -0.1}
_MEASURED_STRONG = {"stratum": "SUBTYPE_B", "class": "strong_dependency",
                    "evidence_state": "measured", "subgroup_n": 60,
                    "subgroup_n_floor_met": True, "median_chronos": -1.3}


def _fire(rows):
    from _skills_common import fired_rules
    return fired_rules(_dep_card(rows), axis="intracellular_intrinsic",
                       card_id_filter=["subgroup-stratified-dependency"])


def test_measured_nondependent_subtype_rule_fires_and_names_stratum():
    fired = _fire([_MEASURED_NONDEP, _MEASURED_STRONG])
    subtype = [f for f in fired if f.get("tier") == "subtype"]
    assert subtype, "measured not-dependent stratum should fire the subtype rule"
    assert subtype[0]["matched_stratum"] == "SUBTYPE_A"
    assert tp._subtype_verdict(fired) == ("subtype_specific_non_dependence",
                                          "subtype-non-dependence-opposing")


def test_underpowered_subtype_row_is_inadmissible():
    """The F4/admissibility guard: an underpowered row cannot fire the rule."""
    fired = _fire([_UNDERPOWERED_NONDEP])
    assert [f for f in fired if f.get("tier") == "subtype"] == []
    assert tp._subtype_verdict(fired) is None


def test_strong_dependency_subtype_does_not_fire():
    """A positive subtype finding produces no verdict — gate is one-directional."""
    fired = _fire([_MEASURED_STRONG])
    assert tp._subtype_verdict(fired) is None


def test_subtype_nondependence_forces_hold():
    subs = {"subtype_fit": {"verdict": ("subtype_specific_non_dependence",
                                        "subtype-non-dependence-opposing")}}
    forced, hits = tp._gate_recommendation(subs)
    assert forced == "hold"
    assert hits[0]["short"] == "subtype_fit"


def test_subtype_hold_loses_to_dependency_veto():
    """Max-severity ratchet: a subtype hold + a dependency veto → veto."""
    subs = {"subtype_fit": {"verdict": ("subtype_specific_non_dependence", "r")},
            "dependency": {"verdict": ("pan_essential_killer", "pan-essential-killer")}}
    forced, _ = tp._gate_recommendation(subs)
    assert forced == "veto"


def test_no_subtype_key_is_backward_compatible():
    """A whole-cohort run (no subtype_fit sub-result) behaves exactly as before."""
    subs = {"dependency": {"verdict": ("dependent", "r")},
            "safety": {"verdict": ("ok", "r")}}
    forced, _ = tp._gate_recommendation(subs)
    assert forced is None
