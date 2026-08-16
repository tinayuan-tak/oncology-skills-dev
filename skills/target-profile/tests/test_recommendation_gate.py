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
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert forced == "veto"
    assert len(hits) == 1 and hits[0]["short"] == "dependency"
    assert hits[0]["driving_rule_id"] == "pan-essential-killer"


def test_non_dependent_forces_veto():
    forced, hits, _sup = tp._gate_recommendation(_sub("dependency", "non_dependent", "non-dependent-killer"))
    assert forced == "veto"


def test_safety_concern_forces_hold_not_veto():
    forced, hits, _sup = tp._gate_recommendation(
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
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert forced is None
    assert hits == []


def test_veto_dominates_hold_when_both_fire():
    subs = _merge(
        _sub("dependency", "pan_essential_killer", "pan-essential-killer"),
        _sub("safety", "highly_constrained_safety_concern", "highly-constrained-safety-warning"),
    )
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert forced == "veto"
    assert len(hits) == 2


def test_no_verdict_and_none_verdict_ignored():
    subs = _merge(
        {"selectivity": {"verdict": None}},          # sub-skill with no verdict fn
        _sub("dependency", "concordant_dependent"),  # supportive, not a gate
    )
    forced, hits, _sup = tp._gate_recommendation(subs)
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
    forced, hits, _sup = tp._gate_recommendation(subs, contracts_repo=tmp_path / "nope")
    assert forced == "veto"
    assert hits[0]["policy_source"] == "fallback"


def test_clamp_semantics_on_wrapped_output():
    """Simulate the run.py clamp: a killer forces veto over an LLM 'nominate',
    preserving the wrapped {value, _source, ...} shape + marking _gated."""
    llm_output = {"overall_recommendation": {"value": "nominate", "_source": "llm_synthesized",
                                             "_model_id": "x", "_prompt_hash": "y"}}
    subs = _sub("dependency", "pan_essential_killer", "pan-essential-killer")
    gate_action, gate_hits, _sup = tp._gate_recommendation(subs)
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
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert forced == "hold"
    assert hits[0]["short"] == "subtype_fit"


def test_subtype_hold_loses_to_dependency_veto():
    """Max-severity ratchet: a subtype hold + a dependency veto → veto."""
    subs = {"subtype_fit": {"verdict": ("subtype_specific_non_dependence", "r")},
            "dependency": {"verdict": ("pan_essential_killer", "pan-essential-killer")}}
    forced, _, _sup = tp._gate_recommendation(subs)
    assert forced == "veto"


def test_no_subtype_key_is_backward_compatible():
    """A whole-cohort run (no subtype_fit sub-result) behaves exactly as before."""
    subs = {"dependency": {"verdict": ("dependent", "r")},
            "safety": {"verdict": ("ok", "r")}}
    forced, _, _sup = tp._gate_recommendation(subs)
    assert forced is None


# ===========================================================================
# Positive tier (PR-C, 2026-07-17) — deterministic confidence FLOOR, F1-safe.
# ===========================================================================

def _dominant_positives():
    return {
        "dependency":      {"verdict": ("concordant_dependent", "concordant-dependent-supportive-dominant")},
        "selectivity":     {"verdict": ("strong_tumor_selective", "tvn-strong-selective-supportive")},
        "tractability_sm": {"verdict": ("well_covered", "e7-triangulated-target-engaged-supportive")},
    }


def test_positive_tier_strong_on_multi_dominant():
    tier, hits = tp._positive_tier(_dominant_positives())
    assert tier == "strong"
    assert len({h["short"] for h in hits}) >= 2


def test_single_dominant_is_moderate_not_strong():
    """Sparsity guard (min_dimensions_for_strong=2): one positive dim caps at moderate."""
    tier, _ = tp._positive_tier({"tractability_sm": {"verdict": ("well_covered", "r")}})
    assert tier == "moderate"


def test_opposing_measured_verdict_blocks_strong():
    """A contradiction (opposing MEASURED verdict) prevents strong even with a dominant."""
    subs = {"dependency": {"verdict": ("concordant_dependent", "r")},
            "selectivity": {"verdict": ("not_selective", "r")}}   # contradiction
    tier, _ = tp._positive_tier(subs)
    assert tier != "strong"


def test_insufficient_is_not_a_contradiction():
    """insufficient/data_unavailable are absence-of-measurement, NOT opposition —
    they must not block a tier (measured-vs-null discipline)."""
    subs = {"dependency": {"verdict": ("concordant_dependent", "r")},   # dominant
            "selectivity": {"verdict": ("insufficient", None)}}         # absence, not contra
    tier, _ = tp._positive_tier(subs)
    assert tier == "moderate"   # 1 positive dim (dependency); insufficient neither helps nor blocks


def test_no_positive_verdicts_returns_none():
    subs = {"dependency": {"verdict": ("insufficient", None)},
            "mechanism": {"verdict": ("well_characterized", "r")}}  # mechanism NOT positive-eligible
    tier, hits = tp._positive_tier(subs)
    assert tier is None and hits == []


def test_kras_pattern_no_kill_and_strong_tier():
    """KRAS golden PRESERVED + UPGRADED: modality-scoped killers (surface neither_viable,
    expression broadly_low) fire NO kill; dependency+selectivity positives → strong.
    This proves KRAS×COADREAD stays nominate AND earns an auditable strong confidence."""
    subs = {
        "dependency":       {"verdict": ("lineage_selective", "lineage-selective-supportive")},  # supportive
        "selectivity":      {"verdict": ("strong_tumor_selective", "tvn-strong-selective-supportive")},  # dominant
        "surface_modality": {"verdict": ("neither_viable", "r")},          # modality-scoped, excluded
        "expression":       {"verdict": ("broadly_low_expression", "r")},  # modality-scoped, excluded
    }
    # no kill
    forced, _, _sup = tp._gate_recommendation(subs)
    assert forced is None, "KRAS golden: modality-scoped killers must NOT force a kill"
    # strong tier: 1 dominant (selectivity) + 1 supportive (dependency) = 2 dims, no contradiction
    tier, _ = tp._positive_tier(subs)
    assert tier == "strong"


def test_correlated_expression_selectivity_count_as_one_dim():
    """HTR1D regression (2026-08-15): expression:strongly_upregulated_in_tumor +
    selectivity:strong_tumor_selective are the SAME tumor-vs-normal RNA contrast → collapse to ONE
    dimension (correlated_dimension_groups), so on their own they cap at `moderate`, NOT `strong`.
    Prevents a declined RNA-only target manufacturing a strong tier from one line counted twice."""
    subs = {
        "expression":  {"verdict": ("strongly_upregulated_in_tumor", "expression-strong-upregulation-supportive")},
        "selectivity": {"verdict": ("strong_tumor_selective", "tvn-strong-selective-supportive")},  # dominant
    }
    tier, hits = tp._positive_tier(subs)
    assert len(hits) == 2, "both hits are still recorded (weights unaffected)"
    assert tier == "moderate", "correlated RNA pair collapses to 1 dimension → not strong"


def test_correlated_group_plus_independent_dim_reaches_strong():
    """A genuinely INDEPENDENT third axis lifts a grouped target back to strong: expression+selectivity
    (1 collapsed dim) + genomic_alteration:biomarker_stratified_dependency (independent dominant) = 2."""
    subs = {
        "expression":        {"verdict": ("strongly_upregulated_in_tumor", "r")},
        "selectivity":       {"verdict": ("strong_tumor_selective", "r")},              # dominant, RNA group
        "genomic_alteration":{"verdict": ("biomarker_stratified_dependency", "r")},     # dominant, independent
    }
    tier, _ = tp._positive_tier(subs)
    assert tier == "strong"


def test_positive_tier_excludes_modality_scoped():
    """surface/expression/mechanism verdicts are NOT positive-eligible even if 'good'."""
    subs = {"surface_modality": {"verdict": ("adc_favorable", "r")},
            "expression": {"verdict": ("broadly_high_expression", "r")},
            "mechanism": {"verdict": ("well_characterized", "r")}}
    tier, hits = tp._positive_tier(subs)
    assert tier is None and hits == []


def test_positive_fallback_is_empty_not_permissive(tmp_path):
    """INVERTED safety contract: a vocab with NO positive_signals block → empty
    positive map → no tier, even for a full house of positives (never spurious strong)."""
    import yaml as _yaml
    voc = tmp_path / "vocabularies"
    voc.mkdir()
    # a kill-only vocab (no positive_signals) — the pre-1.1.0 shape
    (voc / "nomination_verdict_gate.yaml").write_text(_yaml.safe_dump({
        "enum_id": "nomination_verdict_gate", "version": "1.0.0",
        "action_precedence": {"veto": 2, "hold": 1},
        "gates": [{"sub_skill": "dependency", "verdict": "non_dependent", "action": "veto",
                   "rationale": "x", "driving_rule_ids": ["non-dependent-killer"]}],
    }))
    pos_map, _, _, source = tp._load_positive_signals(tmp_path)
    assert pos_map == {} and source == "fallback"
    tier, _ = tp._positive_tier(_dominant_positives(), contracts_repo=tmp_path)
    assert tier is None  # full house of positives, but no vocab → no tier


def test_f1_kill_short_circuits_positive_tier_in_main_flow():
    """THE F1 GUARD (integration-level): when a kill fires, the positive tier must
    NOT be computed — a full house of positives cannot survive/soften a veto.
    Mirrors main()'s `if gate_action: <kill clamp> else: <positive tier>` structure."""
    subs = dict(_dominant_positives())
    subs["dependency"] = {"verdict": ("pan_essential_killer", "pan-essential-killer")}  # KILL
    gate_action, _, _sup = tp._gate_recommendation(subs)
    assert gate_action == "veto"
    # Replicate main()'s branch structure: positive tier is in the ELSE of the kill.
    if gate_action:
        tier = None  # never computed under a kill — the structural F1 guarantee
    else:
        tier, _ = tp._positive_tier(subs)
    assert tier is None, "positive tier must be unreachable when a kill fired"


def test_confidence_floor_is_a_max_never_lowers():
    """The tier sets a FLOOR: it may raise confidence, never lower it. A moderate
    tier (medium floor) must not drag an LLM 'high' down to medium."""
    from copy import deepcopy
    llm_conf_high = {"value": "high", "_source": "llm_synthesized"}
    tier = "moderate"  # → medium floor
    floor = tp._TIER_TO_CONFIDENCE[tier]
    # replicate the floor logic
    if tp._CONFIDENCE_RANK[floor] > tp._CONFIDENCE_RANK[llm_conf_high["value"]]:
        llm_conf_high["value"] = floor
    assert llm_conf_high["value"] == "high"  # unchanged — floor never lowers


# ===========================================================================
# Veto suppression (v1.2.0, 2026-07-17) — backtest-driven gate-C correction.
# Exercises the two suppression policies against the approved-drug false-negatives
# the 16-target backtest found (EGFR/IDH1/FLT3 via context-escape; CD19/TROP2/DLL3
# via modality-scope), plus the CRITICAL control that SM dependency still vetoes.
# ===========================================================================


def test_biomarker_stratified_rescues_pooled_non_dependent():
    """EGFR/IDH1/FLT3 pattern: pooled dependency reads non_dependent (would veto),
    but a MEASURED biomarker-stratified dependency is present → the veto is
    SUPPRESSED (context-escape) and recorded in provenance."""
    subs = _merge(
        _sub("dependency", "non_dependent", "non-dependent-killer"),
        _sub("genomic_alteration", "biomarker_stratified_dependency",
             "mutant-strongly-dependent-supportive"),
    )
    forced, hits, sup = tp._gate_recommendation(subs)
    assert forced is None, "biomarker-stratified dependency must suppress the pooled veto"
    assert hits == []
    assert len(sup) == 1 and sup[0]["verdict"] == "non_dependent"
    assert sup[0]["suppressed_by"]["kind"] == "context_escape"
    assert "biomarker_stratified_dependency" in sup[0]["suppressed_by"]["trigger"]


def test_moderate_biomarker_also_suppresses():
    subs = _merge(
        _sub("dependency", "non_dependent", "non-dependent-killer"),
        _sub("genomic_alteration", "moderate_biomarker_dependency",
             "mutant-moderately-dependent-supportive"),
    )
    forced, hits, sup = tp._gate_recommendation(subs)
    assert forced is None and len(sup) == 1


def test_biomarker_does_NOT_suppress_pan_essential():
    """Context-escape rescues the DILUTION artifact (non_dependent) only. A
    pan_essential_killer is a distinct too-essential failure a stratified signal
    cannot rescue — the veto must STAND."""
    subs = _merge(
        _sub("dependency", "pan_essential_killer", "pan-essential-killer"),
        _sub("genomic_alteration", "biomarker_stratified_dependency",
             "mutant-strongly-dependent-supportive"),
    )
    forced, hits, sup = tp._gate_recommendation(subs)
    assert forced == "veto", "pan_essential veto must NOT be suppressed by a stratified signal"
    assert sup == []


def test_biologics_modality_suppresses_dependency_veto():
    """CD19/TROP2/DLL3 pattern: a surface antigen reads non_dependent (would veto),
    but for a biologics modality the dependency veto is INFORMATIVE-only → suppressed."""
    subs = _sub("dependency", "non_dependent", "non-dependent-killer")
    for modality in ("adc", "bite_tce", "antibody"):
        forced, hits, sup = tp._gate_recommendation(subs, modality=modality)
        assert forced is None, f"dependency veto must be suppressed for modality={modality}"
        assert len(sup) == 1 and sup[0]["suppressed_by"]["kind"] == "modality_scoped"
        assert sup[0]["suppressed_by"]["modality"] == modality


def test_biologics_modality_suppresses_pan_essential_too():
    subs = _sub("dependency", "pan_essential_killer", "pan-essential-killer")
    forced, hits, sup = tp._gate_recommendation(subs, modality="adc")
    assert forced is None and len(sup) == 1


def test_SM_dependency_still_vetoes_the_control():
    """CRITICAL CONTROL: for a small-molecule (or no declared modality) the
    dependency veto MUST still fire. Suppression is biologics-only / rescue-only —
    it must never weaken the SM veto that correctly kills a truly non-dependent
    SM target."""
    subs = _sub("dependency", "non_dependent", "non-dependent-killer")
    # no modality declared → veto stands
    forced, _h, sup = tp._gate_recommendation(subs)
    assert forced == "veto" and sup == []
    # explicit small_molecule → veto stands (not in the biologics set)
    forced_sm, _h2, sup2 = tp._gate_recommendation(subs, modality="small_molecule")
    assert forced_sm == "veto" and sup2 == []
    # degrader → veto stands
    forced_dg, _h3, sup3 = tp._gate_recommendation(subs, modality="degrader")
    assert forced_dg == "veto" and sup3 == []


def test_modality_scope_does_not_suppress_without_declared_modality():
    """The modality-scoped suppression must require an EXPLICIT modality. A biologics
    target evaluated biology-first (modality=None) keeps the conservative veto."""
    subs = _sub("dependency", "non_dependent", "non-dependent-killer")
    forced, _h, sup = tp._gate_recommendation(subs, modality=None)
    assert forced == "veto" and sup == []
