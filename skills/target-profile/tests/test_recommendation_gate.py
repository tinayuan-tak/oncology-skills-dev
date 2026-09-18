"""Tests for the deterministic recommendation gate in target-profile/run.py.

The gate forces overall_recommendation from killer sub-verdicts regardless of
what the LLM chose. These tests exercise the pure `_gate_recommendation` helper
(no Bedrock) + the clamp semantics.

Key correctness property (from the KRAS×COADREAD golden): modality-scoped killers
(surface neither_viable, degrader expression killers) must NOT force a blanket
veto — KRAS hits those yet is a correct `nominate` via small molecule.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run")


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
        _sub("safety", "highly_constrained_safety_concern", "highly-constrained-safety-warning")
    )
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
        {"selectivity": {"verdict": None}},  # sub-skill with no verdict fn
        _sub("dependency", "concordant_dependent"),  # supportive, not a gate
    )
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert forced is None and hits == []


def test_loader_reads_vocab_when_present(tmp_path):
    """_load_gate_verdicts reads the target-contracts vocab and returns source='vocab'."""
    vocab_dir = tmp_path / "vocabularies"
    vocab_dir.mkdir()
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
    vocab_dir = tmp_path / "vocabularies"
    vocab_dir.mkdir()
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
    llm_output = {
        "overall_recommendation": {
            "value": "nominate",
            "_source": "llm_synthesized",
            "_model_id": "x",
            "_prompt_hash": "y",
        }
    }
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
# Abstention LOWER-BOUND guard (2026-09-11) — the missing pessimism half of the clamp.
# When the gate abstains (no veto/hold rule fired), an LLM-authored negative (veto/hold) has no rule
# behind it and collapses to insufficient_evidence. Nominate/insufficient stand.
# ---------------------------------------------------------------------------


def test_abstention_lower_bound_clamps_veto_and_hold():
    for neg in ("veto", "hold"):
        clamped, record = tp.abstention_lower_bound_clamp(neg)
        assert clamped == "insufficient_evidence"
        assert record["applied"] is True and record["llm_recommendation"] == neg
        assert record["clamped_to"] == "insufficient_evidence"


def test_abstention_lower_bound_leaves_positive_and_insufficient():
    # a nominate is not a negative → stands (still bounded ABOVE by the kill gate elsewhere);
    # insufficient_evidence is already the floor; unknown/None → no clamp.
    for keep in ("nominate", "insufficient_evidence", None, "something_else"):
        clamped, record = tp.abstention_lower_bound_clamp(keep)
        assert clamped is None and record is None


def test_abstention_clamp_semantics_on_wrapped_output():
    """Simulate run.py's else-branch clamp: with the gate abstaining, an LLM 'veto' becomes
    insufficient_evidence, the wrapped {value,_source,...} shape is preserved, and the value is marked
    _gated + _lower_bound_clamped (rule-bounded, not free LLM choice)."""
    llm_output = {
        "overall_recommendation": {"value": "veto", "_source": "llm_synthesized", "_model_id": "x", "_prompt_hash": "y"}
    }
    # no kill fired → the gate abstains
    gate_action, _hits, _sup = tp._gate_recommendation(_sub("dependency", "concordant_dependent", "some-rule"))
    assert not gate_action
    rec = llm_output["overall_recommendation"]
    clamped_to, clamp_record = tp.abstention_lower_bound_clamp(rec["value"])
    # replicate the run.py clamp block
    assert clamped_to == "insufficient_evidence"
    rec["value"] = clamped_to
    rec["_gated"] = True
    rec["_lower_bound_clamped"] = True
    assert llm_output["overall_recommendation"]["value"] == "insufficient_evidence"
    assert clamp_record["llm_recommendation"] == "veto"  # original preserved for the audit record


# ---------------------------------------------------------------------------
# Verdict-affecting subtype tier (2026-07-17)
# ---------------------------------------------------------------------------


def _dep_card(rows):
    """A synthetic subgroup-stratified-dependency card_output carrying rows."""
    return [
        {
            "card_id": "subgroup-stratified-dependency",
            "summary": {"per_subgroup_metrics": rows},
            "interpretation_call": "x",
        }
    ]


_MEASURED_NONDEP = {
    "stratum": "SUBTYPE_A",
    "class": "not_dependent",
    "evidence_state": "measured",
    "subgroup_n": 50,
    "subgroup_n_floor_met": True,
    "median_chronos": -0.1,
}
_UNDERPOWERED_NONDEP = {
    "stratum": "SUBTYPE_A",
    "class": "not_dependent",
    "evidence_state": "underpowered",
    "subgroup_n": 17,
    "subgroup_n_floor_met": False,
    "median_chronos": -0.1,
}
_MEASURED_STRONG = {
    "stratum": "SUBTYPE_B",
    "class": "strong_dependency",
    "evidence_state": "measured",
    "subgroup_n": 60,
    "subgroup_n_floor_met": True,
    "median_chronos": -1.3,
}
# Part-8 Step-3 (POU2F3/SCLC-P): intrinsically-small (n<30, underpowered) but effect-admissible
# (subgroup_effect_admissible: an effect-size gate, per depmap_chronos) → the SAME positive channel.
_UNDERPOWERED_STRONG_ADMISSIBLE = {
    "stratum": "SCLC_P",
    "class": "strong_dependency",
    "evidence_state": "underpowered",
    "subgroup_n": 5,
    "subgroup_n_floor_met": False,
    "subgroup_effect_admissible": True,
    "median_chronos": -1.53,
}


def _fire(rows):
    from _skills_common import fired_rules

    return fired_rules(
        _dep_card(rows), axis="intracellular_intrinsic", card_id_filter=["subgroup-stratified-dependency"]
    )


def test_measured_nondependent_subtype_rule_fires_and_names_stratum():
    fired = _fire([_MEASURED_NONDEP, _MEASURED_STRONG])
    subtype = [f for f in fired if f.get("tier") == "subtype"]
    assert subtype, "measured not-dependent stratum should fire the subtype rule"
    assert subtype[0]["matched_stratum"] == "SUBTYPE_A"
    assert tp._subtype_verdict(fired) == ("subtype_specific_non_dependence", "subtype-non-dependence-opposing")


def test_underpowered_subtype_row_is_inadmissible():
    """The F4/admissibility guard: an underpowered row cannot fire the rule."""
    fired = _fire([_UNDERPOWERED_NONDEP])
    assert [f for f in fired if f.get("tier") == "subtype"] == []
    assert tp._subtype_verdict(fired) is None


def test_strong_dependency_subtype_fires_supportive():
    """A measured, floor-cleared STRONG subtype dependency fires the POSITIVE subtype
    channel (subtype_restricted_dependency) — the gate is now bi-directional (#445 gate +
    this PR's _subtype_verdict). Supersedes the old one-directional expectation: a strong
    subtype dependency is a genuine (supportive) cross-target signal, not a no-op."""
    fired = _fire([_MEASURED_STRONG])
    assert tp._subtype_verdict(fired) == ("subtype_restricted_dependency", "subtype-restricted-dependency-supportive")


def test_underpowered_effect_admissible_strong_fires_supportive():
    """Part-8 Step-3 (POU2F3/SCLC-P): a small-but-tight strong dependency — underpowered
    (n<30) yet subgroup_effect_admissible — fires the SAME positive channel via the
    effect-gated rule (disjoint from the floor-cleared `measured` rule). This is the case
    a hard n>=30 floor would have silently discarded."""
    fired = _fire([_UNDERPOWERED_STRONG_ADMISSIBLE])
    subtype = [f for f in fired if f.get("tier") == "subtype"]
    assert subtype, "effect-admissible underpowered strong stratum should fire the subtype rule"
    assert subtype[0]["matched_stratum"] == "SCLC_P"
    assert tp._subtype_verdict(fired) == (
        "subtype_restricted_dependency",
        "subtype-restricted-dependency-underpowered-supportive",
    )


def test_subtype_nondependence_forces_hold():
    subs = {"subtype_fit": {"verdict": ("subtype_specific_non_dependence", "subtype-non-dependence-opposing")}}
    forced, hits, _sup = tp._gate_recommendation(subs)
    assert forced == "hold"
    assert hits[0]["short"] == "subtype_fit"


def test_subtype_hold_loses_to_dependency_veto():
    """Max-severity ratchet: a subtype hold + a dependency veto → veto."""
    subs = {
        "subtype_fit": {"verdict": ("subtype_specific_non_dependence", "r")},
        "dependency": {"verdict": ("pan_essential_killer", "pan-essential-killer")},
    }
    forced, _, _sup = tp._gate_recommendation(subs)
    assert forced == "veto"


def test_no_subtype_key_is_backward_compatible():
    """A whole-cohort run (no subtype_fit sub-result) behaves exactly as before. Uses REAL
    recognized-but-non-gating verdicts (a positive dependency + a neutral safety band): neither
    forces a gate → None. (The former placeholder tokens `dependent`/`ok` were not real resolver
    verdicts; post fail-closed hardening an unrecognized token on a veto-capable axis is clamped,
    so the intent — 'no gate fires' — is expressed with real benign verdicts.)"""
    subs = {
        "dependency": {"verdict": ("concordant_dependent", "r")},
        "safety": {"verdict": ("moderately_constrained_safety", "r")},
    }
    forced, _, _sup = tp._gate_recommendation(subs)
    assert forced is None


# ===========================================================================
# Positive tier (PR-C, 2026-07-17) — deterministic confidence FLOOR, F1-safe.
# ===========================================================================


def _dominant_positives():
    return {
        "dependency": {"verdict": ("concordant_dependent", "concordant-dependent-supportive-dominant")},
        "selectivity": {"verdict": ("strong_tumor_selective", "tvn-strong-selective-supportive")},
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


def test_differentiation_strong_mutex_supportive_grouped_with_genomic():
    """gate v1.11.0 (BACKTEST): differentiation:strong_mutually_exclusive is a SUPPORTIVE positive that
    floors confidence but is GROUPED with genomic_alteration+cis_coherence, so it can NEVER be the 2nd
    independent dimension that manufactures `strong` (it re-reads the driver-hood genomic already counts —
    anti-double-count). Skips until the contracts-first vocab change lands."""
    pos_map, _contra, cfg, _src = tp._load_positive_signals()
    if ("differentiation", "strong_mutually_exclusive") not in pos_map:
        pytest.skip("gate vocab predates the differentiation positive (land contracts-first)")
    # (1) supportive, not dominant
    assert pos_map[("differentiation", "strong_mutually_exclusive")] == "supportive"
    # (2) correlated-grouped with genomic_alteration
    grp = next((g for g in (cfg.get("correlated_dimension_groups") or []) if "differentiation" in g), None)
    assert grp and "genomic_alteration" in grp, "differentiation must be correlated-grouped with genomic_alteration"
    # (3) ANTI-DOUBLE-COUNT: genomic dominant biomarker + differentiation strong_mutex collapse to ONE
    #     dimension → moderate, NOT strong (a single grouped dimension can't meet min_dimensions_for_strong=2)
    subs = {
        "genomic_alteration": {"verdict": ("biomarker_stratified_dependency", "r")},
        "differentiation": {"verdict": ("strong_mutually_exclusive", "r")},
    }
    assert tp._positive_tier(subs)[0] == "moderate"
    # (4) differentiation ALONE caps at moderate (supportive, 1 dim) — never mints a nomination
    assert tp._positive_tier({"differentiation": {"verdict": ("strong_mutually_exclusive", "r")}})[0] == "moderate"
    # (5) it does NOT block an independently-strong target (adds a grouped dim, doesn't subtract)
    subs2 = _merge(_dominant_positives(), {"differentiation": {"verdict": ("strong_mutually_exclusive", "r")}})
    assert tp._positive_tier(subs2)[0] == "strong"


def test_opposing_measured_verdict_blocks_strong():
    """A contradiction (opposing MEASURED verdict) prevents strong even with a dominant."""
    subs = {
        "dependency": {"verdict": ("concordant_dependent", "r")},
        "selectivity": {"verdict": ("not_selective", "r")},
    }  # contradiction
    tier, _ = tp._positive_tier(subs)
    assert tier != "strong"


def test_selectivity_clamp_kill_blocks_strong():
    """gate v1.10.0: a POST-RESOLVER selectivity clamp KILL (selective_but_broadly_normal — a broadly-
    normal / no-window target like GAPDH) is now a positive_contradiction, so it blocks `strong` in a
    composed profile even alongside dominant positives on other axes — closing the advisory→silent-
    degradation gap where a selectivity KILL used to contribute nothing to the spine.

    _positive_tier reads positive_contradictions from the gate vocab dynamically, so this asserts the
    contracts-first gate-v1.10.0 change is live; skip until it has landed (lockstep window)."""
    _, contra_set, _, _ = tp._load_positive_signals()
    if ("selectivity", "selective_but_broadly_normal") not in contra_set:
        pytest.skip("gate vocab predates the selectivity clamp-KILL contradictions (land contracts-first)")
    subs = _merge(
        _dominant_positives(),
        {"selectivity": {"verdict": ("selective_but_broadly_normal", "tvn-no-therapeutic-window-veto")}},
    )
    tier, _ = tp._positive_tier(subs)
    assert tier != "strong"
    # the INT-axis clamp KILL is equally a contradiction
    subs2 = _merge(
        _dominant_positives(),
        {"selectivity": {"verdict": ("selective_but_stromal_confound", "tvn-stromal-confound-veto")}},
    )
    assert tp._positive_tier(subs2)[0] != "strong"
    # but the PRESERVING liability verdict is NOT a contradiction → strong still reachable
    subs3 = _merge(
        _dominant_positives(),
        {"selectivity": {"verdict": ("selective_with_normal_liability", "tvn-sc-normal-critical-organ-veto")}},
    )
    assert tp._positive_tier(subs3)[0] == "strong"


def test_insufficient_is_not_a_contradiction():
    """insufficient/data_unavailable are absence-of-measurement, NOT opposition —
    they must not block a tier (measured-vs-null discipline)."""
    subs = {
        "dependency": {"verdict": ("concordant_dependent", "r")},  # dominant
        "selectivity": {"verdict": ("insufficient", None)},
    }  # absence, not contra
    tier, _ = tp._positive_tier(subs)
    assert tier == "moderate"  # 1 positive dim (dependency); insufficient neither helps nor blocks


def test_no_positive_verdicts_returns_none():
    subs = {
        "dependency": {"verdict": ("insufficient", None)},
        "mechanism": {"verdict": ("well_characterized", "r")},
    }  # mechanism NOT positive-eligible
    tier, hits = tp._positive_tier(subs)
    assert tier is None and hits == []


def test_kras_pattern_no_kill_and_strong_tier():
    """KRAS golden PRESERVED + UPGRADED: modality-scoped killers (surface neither_viable,
    expression broadly_low) fire NO kill; dependency+selectivity positives → strong.
    This proves KRAS×COADREAD stays nominate AND earns an auditable strong confidence."""
    subs = {
        "dependency": {"verdict": ("lineage_selective", "lineage-selective-supportive")},  # supportive
        "selectivity": {"verdict": ("strong_tumor_selective", "tvn-strong-selective-supportive")},  # dominant
        "surface_modality": {"verdict": ("neither_viable", "r")},  # modality-scoped, excluded
        "expression": {"verdict": ("broadly_low_expression", "r")},  # modality-scoped, excluded
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
        "expression": {"verdict": ("strongly_upregulated_in_tumor", "expression-strong-upregulation-supportive")},
        "selectivity": {"verdict": ("strong_tumor_selective", "tvn-strong-selective-supportive")},  # dominant
    }
    tier, hits = tp._positive_tier(subs)
    assert len(hits) == 2, "both hits are still recorded (weights unaffected)"
    assert tier == "moderate", "correlated RNA pair collapses to 1 dimension → not strong"


def test_correlated_group_plus_independent_dim_reaches_strong():
    """A genuinely INDEPENDENT third axis lifts a grouped target back to strong: expression+selectivity
    (1 collapsed dim) + genomic_alteration:biomarker_stratified_dependency (independent dominant) = 2."""
    subs = {
        "expression": {"verdict": ("strongly_upregulated_in_tumor", "r")},
        "selectivity": {"verdict": ("strong_tumor_selective", "r")},  # dominant, RNA group
        "genomic_alteration": {"verdict": ("biomarker_stratified_dependency", "r")},  # dominant, independent
    }
    tier, _ = tp._positive_tier(subs)
    assert tier == "strong"


def test_positive_tier_excludes_modality_scoped():
    """surface/expression/mechanism verdicts are NOT positive-eligible even if 'good'."""
    subs = {
        "surface_modality": {"verdict": ("adc_favorable", "r")},
        "expression": {"verdict": ("broadly_high_expression", "r")},
        "mechanism": {"verdict": ("well_characterized", "r")},
    }
    tier, hits = tp._positive_tier(subs)
    assert tier is None and hits == []


def test_positive_fallback_is_empty_not_permissive(tmp_path):
    """INVERTED safety contract: a vocab with NO positive_signals block → empty
    positive map → no tier, even for a full house of positives (never spurious strong)."""
    import yaml as _yaml

    voc = tmp_path / "vocabularies"
    voc.mkdir()
    # a kill-only vocab (no positive_signals) — the pre-1.1.0 shape
    (voc / "nomination_verdict_gate.yaml").write_text(
        _yaml.safe_dump(
            {
                "enum_id": "nomination_verdict_gate",
                "version": "1.0.0",
                "action_precedence": {"veto": 2, "hold": 1},
                "gates": [
                    {
                        "sub_skill": "dependency",
                        "verdict": "non_dependent",
                        "action": "veto",
                        "rationale": "x",
                        "driving_rule_ids": ["non-dependent-killer"],
                    }
                ],
            }
        )
    )
    pos_map, _, _, source = tp._load_positive_signals(tmp_path)
    assert pos_map == {} and source == "fallback"
    tier, _ = tp._positive_tier(_dominant_positives(), contracts_repo=tmp_path)
    assert tier is None  # full house of positives, but no vocab → no tier


def test_f1_kill_reports_tier_but_never_floors_confidence():
    """THE F1 GUARD (integration-level): when a kill fires, a full house of positives
    cannot survive/soften the veto NOR raise its confidence. Since 2026-09-11 (CDH3
    review) the positive tier + hits ARE computed on gated runs so confidence_tier
    carries an identical {tier, hits} shape in both branches (confidence and
    recommendation are orthogonal) — but the confidence FLOOR is applied ONLY on
    abstention. This asserts both halves: the tier is reported, and the recommendation
    stays the veto with no confidence-raise. Mirrors main()'s branch structure."""
    subs = dict(_dominant_positives())
    subs["dependency"] = {"verdict": ("pan_essential_killer", "pan-essential-killer")}  # KILL
    gate_action, _, _sup = tp._gate_recommendation(subs)
    assert gate_action == "veto"
    # The positive tier is now resolved unconditionally (reporting-symmetric shape)...
    tier, pos_hits = tp._positive_tier(subs)
    confidence_tier = {"tier": tier, "hits": pos_hits}
    assert "hits" in confidence_tier, "hits key present in BOTH branches (shape symmetry)"
    # ...but the confidence FLOOR lives in the ELSE (abstention) branch only: a kill is
    # never confidence-RAISED, and the forced recommendation stays the veto.
    floored = False
    if not gate_action and tier:
        floored = True
    assert not floored, "a killed target's confidence must never be floored-up by a positive tier"


def test_confidence_floor_is_a_max_never_lowers():
    """The tier sets a FLOOR: it may raise confidence, never lower it. A moderate
    tier (medium floor) must not drag an LLM 'high' down to medium."""
    llm_conf_high = {"value": "high", "_source": "llm_synthesized"}
    tier = "moderate"  # → medium floor
    floor = tp._TIER_TO_CONFIDENCE[tier]
    # replicate the floor logic
    if tp._CONFIDENCE_RANK[floor] > tp._CONFIDENCE_RANK[llm_conf_high["value"]]:
        llm_conf_high["value"] = floor
    assert llm_conf_high["value"] == "high"  # unchanged — floor never lowers


# ===========================================================================
# POSITIVE NOMINATION (A1, 2026-09-11, gate vocab 1.18.0)
#
# Before this, the gate could ONLY veto/hold — measured on the known-target panel: 10 hold,
# 2 veto, 17 abstain, ZERO nominate, with ERBB2/BRCA sitting at `strong` on 3 hits (all 3
# `dominant`) and still resolving to no recommendation. Every `nominate` was LLM-authored,
# which is what made the panel's specificity arm (must_not_nominate + 2 decoys) vacuous.
# ===========================================================================


def _vocab_with(tmp_path, **positive_cfg):
    """Write a minimal gate vocab into tmp_path/vocabularies and return the repo root.
    Mirrors test_positive_tier_absent_from_vocab_yields_no_tier's fixture shape."""
    import yaml as _yaml

    voc = tmp_path / "vocabularies"
    voc.mkdir(exist_ok=True)
    (voc / "nomination_verdict_gate.yaml").write_text(
        _yaml.safe_dump(
            {
                "enum_id": "nomination_verdict_gate",
                "version": "1.18.0",
                "action_precedence": {"veto": 2, "hold": 1},
                "positive_signals": [
                    {"sub_skill": "dependency", "verdict": "selective_dependency", "weight": "dominant"},
                ],
                "positive_contradictions": [],
                "positive_tier_config": {"min_dimensions_for_strong": 2, "require_dominant_for_strong": True}
                | positive_cfg,
                "gates": [
                    {
                        "sub_skill": "dependency",
                        "verdict": "non_dependent",
                        "action": "veto",
                        "rationale": "x",
                        "driving_rule_ids": ["non-dependent-killer"],
                    }
                ],
            }
        )
    )
    return tmp_path


def test_positive_tier_nominates_reads_the_threshold_from_the_vocab(tmp_path):
    """The nomination bar is POLICY, not code: it comes from
    positive_tier_config.forces_nominate_at_tier so a product owner can move it without a code
    change, exactly like the veto/hold policy."""
    repo = _vocab_with(tmp_path, forces_nominate_at_tier="strong")
    assert tp._positive_tier_nominates("strong", contracts_repo=repo) is True
    # `moderate` is reachable on a SINGLE supportive hit — it must never mint a GO.
    assert tp._positive_tier_nominates("moderate", contracts_repo=repo) is False
    assert tp._positive_tier_nominates(None, contracts_repo=repo) is False


def test_positive_tier_nominates_fails_closed_without_the_key(tmp_path):
    """FAIL-CLOSED and backward-compatible: a vocab with no forces_nominate_at_tier (every version
    before 1.18.0) nominates nothing, reproducing pre-A1 behaviour. This is the INVERTED fallback of
    the kill path — a broken kill vocab must still FIRE vetoes, a broken positive vocab must never
    MINT a GO. Non-vacuous by construction: the sibling test above proves the True branch exists."""
    repo = _vocab_with(tmp_path)  # no forces_nominate_at_tier
    assert tp._positive_tier_nominates("strong", contracts_repo=repo) is False
    assert tp._positive_tier_nominates("moderate", contracts_repo=repo) is False


def test_forced_nominate_is_not_a_gate_action():
    """The nomination is deliberately NOT in action_precedence. That map is the key function of a
    `max()` over the FIRED KILL hits, so a positive token in it could be ranked against — and
    tie-break with — a veto/hold. `nominate` therefore lives in its own branch, reachable only on
    abstention, and can never appear as a _gate_recommendation action."""
    import tp_gates

    assert "nominate" not in tp_gates._GATE_ACTION_RANK, tp_gates._GATE_ACTION_RANK
    assert "nominate" not in tp_gates._FALLBACK_GATE_ACTION_RANK
    subs = dict(_dominant_positives())
    gate_action, hits, _sup = tp._gate_recommendation(subs)
    assert gate_action is None, "a full house of positives must not produce a GATE action"
    assert all(h["action"] != "nominate" for h in hits)


def test_f1_forced_nominate_unreachable_when_a_kill_fired():
    """THE F1 GUARD for the positive half: the nomination branch is inside the ELSE of
    `if gate_action:`, so a full house of positives (strong tier, all dominant) cannot mint a
    nominate over a fired veto. Mirrors main()'s branch structure, like its confidence-floor
    sibling above."""
    subs = dict(_dominant_positives())
    subs["dependency"] = {"verdict": ("pan_essential_killer", "pan-essential-killer")}  # KILL
    gate_action, _, _sup = tp._gate_recommendation(subs)
    assert gate_action == "veto"
    tier, _ = tp._positive_tier(subs)
    nominated = (not gate_action) and tp._positive_tier_nominates(tier)
    assert not nominated, "a vetoed target was nominated by the positive tier"


def test_the_llm_authored_negative_interlock_is_wired_to_the_real_decision():
    """THE INTERLOCK, tested against the code that implements it.

    This test was previously VACUOUS: it computed `withheld = clamped_to is not None` and then
    asserted that local variable, so it passed identically under EITHER policy and could never fail.
    It re-derived main()'s branch instead of calling it — which is why the two nominate paths could
    diverge on this exact question without a single test going red. Now it calls the one decision
    point, so the assertion is falsifiable.

    Policy as settled 2026-09-11: a fired deterministic conjunction DOES nominate over a rule-less
    LLM negative (the clamp exists to floor exactly such a negative; a fired conjunction is the rule
    it was waiting for), and the resulting value/narrative disagreement is recorded explicitly."""
    clamped_to, _clamp_rec = tp.abstention_lower_bound_clamp("veto")
    assert clamped_to == "insufficient_evidence", "clamp precondition (a) must fire on an LLM veto"
    value, patch = tp.reconcile_positive_nomination(
        thesis_action=None,
        thesis_record=None,
        tier="strong",
        tier_nominates=True,
        pos_hits=[{"short": "dependency", "verdict": "selectively_dependent", "weight": "dominant"}],
        clamped=clamped_to is not None,
        llm_value="veto",
    )
    assert value == "nominate", "a rule-bearing conjunction must outrank a rule-less LLM negative"
    assert patch["nominated_over_llm_negative"]["llm_recommendation"] == "veto"
    # Control: a non-negative LLM value does NOT clamp, and then there is no disagreement to record.
    assert tp.abstention_lower_bound_clamp("nominate")[0] is None


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
        _sub("genomic_alteration", "biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"),
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
        _sub("genomic_alteration", "moderate_biomarker_dependency", "mutant-moderately-dependent-supportive"),
    )
    forced, hits, sup = tp._gate_recommendation(subs)
    assert forced is None and len(sup) == 1


def test_biomarker_does_NOT_suppress_pan_essential():
    """Context-escape rescues the DILUTION artifact (non_dependent) only. A
    pan_essential_killer is a distinct too-essential failure a stratified signal
    cannot rescue — the veto must STAND."""
    subs = _merge(
        _sub("dependency", "pan_essential_killer", "pan-essential-killer"),
        _sub("genomic_alteration", "biomarker_stratified_dependency", "mutant-strongly-dependent-supportive"),
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


# ===========================================================================
# Card-field veto-suppressor trigger (2026-08-21) — the SL rescue after the
# synthetic_lethal_partners short consolidated into the GATELESS
# combination_vulnerability sub-skill (verdict=None). The old verdict-tuple trigger
# could never match; the signal now lives on the synthetic-lethal-partners CARD field.
# ===========================================================================


def _sub_with_card(short, verdict, card_id, summary):
    """A sub-result carrying a composed card (for card-field suppressor triggers)."""
    return {short: {"verdict": (verdict if verdict else None), "cards": [{"card_id": card_id, "summary": summary}]}}


def test_sl_card_field_suppresses_pooled_non_dependent():
    """SMARCA2←SMARCA4 pattern: pooled dependency reads non_dependent (would veto), but the
    synthetic-lethal-partners card — composed under the GATELESS combination_vulnerability
    sub-skill — carries sl_partner_class=has_experimental_sl_partner → the veto is SUPPRESSED
    via the CARD-FIELD context-escape trigger. Guards the consolidation orphan: the old
    {sub_skill: synthetic_lethal_partners, verdict: ...} trigger silently went dead when the
    short was retired 2026-08-20."""
    subs = _merge(
        _sub("dependency", "non_dependent", "non-dependent-killer"),
        _sub_with_card(
            "combination_vulnerability",
            None,
            "synthetic-lethal-partners",
            {"sl_partner_class": "has_experimental_sl_partner"},
        ),
    )
    forced, hits, sup = tp._gate_recommendation(subs)
    assert forced is None, "an experimental SL partner (card field) must suppress the pooled veto"
    assert hits == []
    assert len(sup) == 1 and sup[0]["verdict"] == "non_dependent"
    assert sup[0]["suppressed_by"]["kind"] == "context_escape"
    assert sup[0]["suppressed_by"]["trigger"] == (
        "synthetic-lethal-partners.sl_partner_class=has_experimental_sl_partner"
    )


def test_sl_computational_partner_does_not_suppress():
    """ONLY the experimental tier rescues — a computational-only prediction is too weak to
    override a measured pooled negative (vocab: has_experimental_sl_partner only)."""
    subs = _merge(
        _sub("dependency", "non_dependent", "non-dependent-killer"),
        _sub_with_card(
            "combination_vulnerability",
            None,
            "synthetic-lethal-partners",
            {"sl_partner_class": "has_computational_sl_partner"},
        ),
    )
    forced, _h, sup = tp._gate_recommendation(subs)
    assert forced == "veto" and sup == []


def test_sl_card_field_does_not_suppress_pan_essential():
    """Card-field escape rescues the DILUTION artifact (non_dependent) only — a
    pan_essential_killer is a distinct failure an SL partner cannot rescue."""
    subs = _merge(
        _sub("dependency", "pan_essential_killer", "pan-essential-killer"),
        _sub_with_card(
            "combination_vulnerability",
            None,
            "synthetic-lethal-partners",
            {"sl_partner_class": "has_experimental_sl_partner"},
        ),
    )
    forced, _h, sup = tp._gate_recommendation(subs)
    assert forced == "veto" and sup == []


def test_veto_suppressor_triggers_reference_live_shorts_or_composed_cards():
    """CONSOLIDATION-ORPHAN GUARD: every veto_suppressor `when_present` trigger must reference
    EITHER a live fan-out short (verdict-tuple form) OR a card composed in some SUB_SKILL_CARDS
    entry (card-field form). A retired short / dropped card silently disables a suppressor — this
    is exactly how the SL rescue went dead when synthetic_lethal_partners was consolidated. This
    guard fails loudly the next time a consolidation orphans a trigger."""
    supps, _msvs, _bavd, _gdvd, src = tp._load_veto_suppressors()
    assert src == "vocab", "guard needs the real sibling-contracts vocab"
    live_shorts = {sh for _sd, sh in tp.SUB_SKILLS} | {tp.SUBTYPE_SHORT}
    composed_cards = {cid for cards in tp.SUB_SKILL_CARDS.values() for cid in cards} | set(tp.SUBTYPE_CARDS)
    for s in supps:
        for w in s["when_present"]:
            if "verdict" in w:
                assert w["sub_skill"] in live_shorts, (
                    f"veto-suppressor verdict-trigger sub_skill {w['sub_skill']!r} is not a live "
                    f"fan-out short (consolidation orphan — the suppressor can never fire)"
                )
            else:
                assert w["card_id"] in composed_cards, (
                    f"veto-suppressor card-field trigger card_id {w['card_id']!r} is not composed "
                    f"in any SUB_SKILL_CARDS entry (the suppressor can never fire)"
                )


# --- PR-4b: biology-axis-scoped dependency-veto DOWNGRADE (2026-08-24) ---


def _surface_antigen_subs(surface_verdict="adc_preferred_tce_unsafe"):
    """A DLL3-shaped fired set: pooled non_dependent (would veto) + a FAVORABLE surface fit."""
    return _merge(
        _sub("dependency", "non_dependent", "non-dependent-killer"),
        _sub("surface_modality", surface_verdict, "adc-tce-fit"),
    )


def test_biology_axis_downgrades_surface_antigen_veto_to_hold():
    """DLL3-class: surface_intrinsic axis + favorable surface fit → the dependency non_dependent VETO
    is DOWNGRADED to hold (surfaces the target, doesn't force-decline it on an irrelevant criterion)."""
    forced, hits, sup = tp._gate_recommendation(_surface_antigen_subs(), biology_axis="surface_intrinsic")
    assert forced == "hold", (forced, hits)
    # the dependency hit survives as a hold (downgraded), recorded in suppressions.
    dep_hit = next(h for h in hits if h["short"] == "dependency")
    assert dep_hit["action"] == "hold" and dep_hit.get("_downgraded_from") == "veto"
    assert any(s["suppressed_by"]["kind"] == "biology_axis_downgrade" for s in sup)


def test_biology_axis_downgrade_requires_favorable_surface():
    """Guard: a surface axis with NO viable arm (neither_viable) still VETOES — the favorable-surface
    co-condition prevents rescuing surface-junk."""
    forced, _hits, _sup = tp._gate_recommendation(
        _surface_antigen_subs("neither_viable"), biology_axis="surface_intrinsic"
    )
    assert forced == "veto"


def test_biology_axis_downgrade_only_for_surface_axis():
    """Guard: an intracellular target with the same fired set still VETOES (downgrade is surface-only)."""
    forced, _hits, _sup = tp._gate_recommendation(_surface_antigen_subs(), biology_axis="intracellular_intrinsic")
    assert forced == "veto"


def test_biology_axis_downgrade_absent_axis_is_backward_compatible():
    """No biology_axis (default None) → veto stands, exactly as before the downgrade existed."""
    forced, _hits, _sup = tp._gate_recommendation(_surface_antigen_subs())
    assert forced == "veto"


# --- T2b (2026-08-25): DATA-DRIVEN downgrade for UNCURATED surface antigens ---
# The downgrade rescued only the 22 CURATED surface_intrinsic targets; an uncurated approved antigen
# (TROP2/TACSTD2, NECTIN4, CD19, FOLR1 ...) resolves to biology_axis=unknown and was force-VETOED on a
# default run (round-1 5/5). Adding `unknown` to when_biology_axis_in makes the downgrade key on the
# FAVORABLE fit_class (real surface evidence) instead of the curation. These use a SYNTHETIC vocab so
# the mechanism is proven independent of the companion contracts vocab merge (target-contracts #546).


def _vocab_with_unknown(tmp_path):
    """A minimal gate vocab whose downgrade admits biology_axis=unknown (the post-#546 shape)."""
    voc = tmp_path / "vocabularies"
    voc.mkdir()
    (voc / "nomination_verdict_gate.yaml").write_text(
        "gates:\n"
        "  - {sub_skill: dependency, verdict: non_dependent, action: veto}\n"
        "biology_axis_scoped_veto_downgrade:\n"
        "  - downgrades: {sub_skill: dependency, verdict: non_dependent}\n"
        "    to_action: hold\n"
        "    when_biology_axis_in: [surface_intrinsic, unknown]\n"
        "    when_surface_verdict_in: [both_viable, adc_preferred, tce_preferred, "
        "adc_preferred_tce_unsafe, adc_preferred_tce_escape_risk, surface_viable_density_caveated]\n"
    )
    return tmp_path


def test_uncurated_surface_antigen_downgrades_to_hold(tmp_path):
    """TROP2/NECTIN4/CD19 pattern: an UNCURATED antigen (biology_axis=unknown) with a favorable surface
    fit has its pooled non_dependent VETO downgraded to hold — data-driven off the fit_class, not the
    curated lookup. This is the round-1 T2b fix."""
    forced, hits, sup = tp._gate_recommendation(
        _surface_antigen_subs(), contracts_repo=_vocab_with_unknown(tmp_path), biology_axis="unknown"
    )
    assert forced == "hold", (forced, hits)
    dep_hit = next(h for h in hits if h["short"] == "dependency")
    assert dep_hit["action"] == "hold" and dep_hit.get("_downgraded_from") == "veto"
    assert any(s["suppressed_by"]["kind"] == "biology_axis_downgrade" for s in sup)


def test_uncurated_requires_favorable_surface(tmp_path):
    """Guard preserved for the unknown axis: an uncurated target with NO viable surface arm
    (neither_viable) still VETOES — the favorable-surface co-condition prevents rescuing surface-junk."""
    forced, _hits, _sup = tp._gate_recommendation(
        _surface_antigen_subs("neither_viable"), contracts_repo=_vocab_with_unknown(tmp_path), biology_axis="unknown"
    )
    assert forced == "veto"


def test_intracellular_still_vetoes_even_with_unknown_admitted(tmp_path):
    """CRITICAL guard: adding `unknown` must NOT loosen the intracellular exclusion — an
    explicitly-classified intracellular_intrinsic target with a favorable surface signal still VETOES
    (an intracellular oncogene with an incidental surface signal is not a surface antigen)."""
    forced, _hits, _sup = tp._gate_recommendation(
        _surface_antigen_subs(), contracts_repo=_vocab_with_unknown(tmp_path), biology_axis="intracellular_intrinsic"
    )
    assert forced == "veto"


# --- 2026-09-08: EXTRINSIC / MIXED axis admitted (immune-checkpoint FN, CD274/PD-L1) ---
# A curated extrinsic (TME/immune/stromal) or mixed target engaged by antibody BLOCKADE (PD-L1=mixed,
# PD-1/CTLA4=extrinsic) is orthogonal to a tumor-intrinsic non_dependent, exactly like a surface antigen.
# Fixes a CURATION PENALTY: an uncurated checkpoint (unknown) already downgraded, but a curated one
# (mixed/extrinsic) was locked out. Synthetic vocab so the mechanism is proven independent of the
# companion contracts merge (target-contracts #694).


def _vocab_with_extrinsic(tmp_path):
    """A minimal gate vocab whose downgrade admits extrinsic + mixed (the post-#694 shape)."""
    voc = tmp_path / "vocabularies"
    voc.mkdir()
    (voc / "nomination_verdict_gate.yaml").write_text(
        "gates:\n"
        "  - {sub_skill: dependency, verdict: non_dependent, action: veto}\n"
        "biology_axis_scoped_veto_downgrade:\n"
        "  - downgrades: {sub_skill: dependency, verdict: non_dependent}\n"
        "    to_action: hold\n"
        "    when_biology_axis_in: [surface_intrinsic, unknown, extrinsic, mixed]\n"
        "    when_surface_verdict_in: [both_viable, adc_preferred, tce_preferred, "
        "adc_preferred_tce_unsafe, adc_preferred_tce_escape_risk, surface_viable_density_caveated]\n"
    )
    return tmp_path


def test_mixed_axis_checkpoint_downgrades_to_hold(tmp_path):
    """CD274/PD-L1 pattern: a curated `mixed` checkpoint with a favorable surface fit has its pooled
    non_dependent VETO downgraded to hold (engaged by antibody blockade, not a tumor-intrinsic
    dependency) — the curation-penalty fix."""
    forced, hits, sup = tp._gate_recommendation(
        _surface_antigen_subs(), contracts_repo=_vocab_with_extrinsic(tmp_path), biology_axis="mixed"
    )
    assert forced == "hold", (forced, hits)
    dep_hit = next(h for h in hits if h["short"] == "dependency")
    assert dep_hit["action"] == "hold" and dep_hit.get("_downgraded_from") == "veto"
    assert any(s["suppressed_by"]["kind"] == "biology_axis_downgrade" for s in sup)


def test_extrinsic_axis_checkpoint_downgrades_to_hold(tmp_path):
    """PD-1/CTLA4 pattern: a curated `extrinsic` checkpoint with a favorable surface fit downgrades too."""
    forced, _hits, _sup = tp._gate_recommendation(
        _surface_antigen_subs(), contracts_repo=_vocab_with_extrinsic(tmp_path), biology_axis="extrinsic"
    )
    assert forced == "hold"


def test_extrinsic_requires_favorable_surface(tmp_path):
    """Bound intact: an extrinsic target with NO viable surface arm (a secreted ligand → neither_viable)
    still VETOES — the favorable-surface co-condition is unchanged."""
    forced, _hits, _sup = tp._gate_recommendation(
        _surface_antigen_subs("neither_viable"),
        contracts_repo=_vocab_with_extrinsic(tmp_path),
        biology_axis="extrinsic",
    )
    assert forced == "veto"


def test_intracellular_still_vetoes_with_extrinsic_admitted(tmp_path):
    """CRITICAL guard: admitting extrinsic/mixed must NOT loosen the intracellular exclusion."""
    forced, _hits, _sup = tp._gate_recommendation(
        _surface_antigen_subs(), contracts_repo=_vocab_with_extrinsic(tmp_path), biology_axis="intracellular_intrinsic"
    )
    assert forced == "veto"


# --- Round-2 (2026-08-25): GoF-DRIVER-scoped dependency-veto downgrade (neomorphic GoF, e.g. IDH1) ---
# The neomorphic/intracellular slice the surface downgrade can't reach: a confirmed GoF driver
# (alteration-role GoF) with a pooled non_dependent read should HOLD, not VETO — whole-gene KO !=
# mutant-selective inhibition. Keyed on the GENOMIC sub-verdict; synthetic vocab so it's independent of
# the companion contracts block.


def _vocab_with_gof(tmp_path):
    voc = tmp_path / "vocabularies"
    voc.mkdir()
    (voc / "nomination_verdict_gate.yaml").write_text(
        "gates:\n"
        "  - {sub_skill: dependency, verdict: non_dependent, action: veto}\n"
        "  - {sub_skill: dependency, verdict: pan_essential_killer, action: veto}\n"
        "gof_driver_scoped_veto_downgrade:\n"
        "  - downgrades: {sub_skill: dependency, verdict: non_dependent}\n"
        "    to_action: hold\n"
        "    when_genomic_verdict_in: [confirmed_driver, multi_class_driver]\n"
    )
    return tmp_path


def _gof_subs(dep="non_dependent", genomic="confirmed_driver"):
    return _merge(
        _sub("dependency", dep, "non-dependent-killer"),
        _sub("genomic_alteration", genomic, "alteration-role-gof-driver-supportive"),
    )


def test_gof_driver_downgrades_non_dependent_veto_to_hold(tmp_path):
    """IDH1 R132 shape: non_dependent + confirmed_driver (GoF) → the veto is DOWNGRADED to hold."""
    forced, hits, sup = tp._gate_recommendation(_gof_subs(), contracts_repo=_vocab_with_gof(tmp_path))
    assert forced == "hold", (forced, hits)
    dep_hit = next(h for h in hits if h["short"] == "dependency")
    assert dep_hit["action"] == "hold" and dep_hit.get("_downgraded_from") == "veto"
    assert any(s["suppressed_by"]["kind"] == "gof_driver_downgrade" for s in sup)


def test_multi_class_driver_also_downgrades(tmp_path):
    forced, _h, _s = tp._gate_recommendation(
        _gof_subs(genomic="multi_class_driver"), contracts_repo=_vocab_with_gof(tmp_path)
    )
    assert forced == "hold"


def test_non_driver_genomic_still_vetoes(tmp_path):
    """GLS/LUAD guard: non_dependent + a NON-driver genomic read (missense_dominant_pattern) still
    VETOES — the downgrade is scoped to GoF-driver verdicts only."""
    forced, _h, _s = tp._gate_recommendation(
        _gof_subs(genomic="missense_dominant_pattern"), contracts_repo=_vocab_with_gof(tmp_path)
    )
    assert forced == "veto"


def test_lof_driver_still_vetoes(tmp_path):
    """TSG guard: a LoF driver (confirmed_lof_driver) is NOT a mutant-selective GoF target → veto stands."""
    forced, _h, _s = tp._gate_recommendation(
        _gof_subs(genomic="confirmed_lof_driver"), contracts_repo=_vocab_with_gof(tmp_path)
    )
    assert forced == "veto"


def test_gof_downgrade_does_not_touch_pan_essential(tmp_path):
    """MYC guard: pan_essential_killer + confirmed_driver still VETOES (the downgrade targets the
    non_dependent verdict only, never the pan-essential killer)."""
    forced, _h, _s = tp._gate_recommendation(
        _gof_subs(dep="pan_essential_killer"), contracts_repo=_vocab_with_gof(tmp_path)
    )
    assert forced == "veto"


def test_contradiction_reconciler_drops_amp_conditional_selectivity_kill(monkeypatch):
    """Cross-axis reconciler (IDAS/ERBB2 selectivity FN): a genomic biomarker_stratified_dependency
    RECONCILES (drops) the selectivity selective_but_broadly_normal CONTRADICTION — the no-window KILL is
    bulk-RNA÷critical-organ, which dilutes an amp-selected window (HER2/ERBB2, FGFR2). Hermetic: inject the
    reconciler config so the test does not depend on the live vocab."""
    import tp_gates as tpg  # the reconciler helpers live in tp_gates (run.py does not re-export them)

    cfg = [
        {
            "reconciles": {"sub_skill": "selectivity", "verdict": "selective_but_broadly_normal"},
            "when_present": [{"sub_skill": "genomic_alteration", "verdict": "biomarker_stratified_dependency"}],
        }
    ]
    monkeypatch.setattr(tpg, "_load_contradiction_reconcilers", lambda *a, **k: cfg)
    amp = _merge(
        _sub("selectivity", "selective_but_broadly_normal"),
        _sub("genomic_alteration", "biomarker_stratified_dependency"),
    )
    assert tpg._reconciled_contradiction_keys(amp) == {("selectivity", "selective_but_broadly_normal")}
    # no amp trigger → the contradiction STANDS (true-housekeeping KILL preserved: TROP2/GAPDH)
    noamp = _merge(
        _sub("selectivity", "selective_but_broadly_normal"), _sub("genomic_alteration", "missense_dominant_pattern")
    )
    assert tpg._reconciled_contradiction_keys(noamp) == set()
    # reconciled selectivity verdict absent → nothing to reconcile
    clean = _merge(
        _sub("selectivity", "strong_tumor_selective"), _sub("genomic_alteration", "biomarker_stratified_dependency")
    )
    assert tpg._reconciled_contradiction_keys(clean) == set()


def test_surface_fit_reconciles_no_window_selectivity_kill(monkeypatch):
    """Surface-fit reconciler (IDAS ERBB3/TACSTD2/MUC17 FN): a FAVORABLE surface_modality fit RECONCILES
    (drops) the selectivity selective_but_broadly_normal KILL — for an ADC/TCE surface antigen the window
    is modality-engineered, NOT the bulk tumor÷normal-organ RNA ratio. Distinct from the amp trigger: these
    carry a nomination-INERT confirmed_driver genomic verdict, so reconciler (1) does not reach them."""
    import tp_gates as tpg

    cfg = [
        {
            "reconciles": {"sub_skill": "selectivity", "verdict": "selective_but_broadly_normal"},
            "when_present": [
                {"sub_skill": "surface_modality", "verdict": "adc_preferred"},
                {"sub_skill": "surface_modality", "verdict": "adc_preferred_tce_unsafe"},
            ],
        }
    ]
    monkeypatch.setattr(tpg, "_load_contradiction_reconcilers", lambda *a, **k: cfg)
    # favorable surface fit (ERBB3/LUAD = adc_preferred_tce_unsafe) → reconciled, even though genomic is
    # the nomination-inert confirmed_driver family (not biomarker_stratified → amp trigger would NOT fire).
    adc = _merge(
        _sub("selectivity", "selective_but_broadly_normal"),
        _sub("surface_modality", "adc_preferred_tce_unsafe"),
        _sub("genomic_alteration", "confirmed_driver"),
    )
    assert tpg._reconciled_contradiction_keys(adc) == {("selectivity", "selective_but_broadly_normal")}
    # secreted/intracellular target (VEGFA/CDK2) → surface arm NOT viable → KILL correctly STANDS
    novia = _merge(_sub("selectivity", "selective_but_broadly_normal"), _sub("surface_modality", "neither_viable"))
    assert tpg._reconciled_contradiction_keys(novia) == set()


def test_hard_gates_status_reconciled_not_opposing(monkeypatch):
    """Regression for the #1206 gap: _hard_gates_status (the LLM-facing hard-gate view) must mark a
    reconciled contradiction `reconciled`, NOT `opposing` — otherwise the scorecard/positive-tier (which
    subtract the reconciled set) disagree with the hard-gate view and the LLM still reads it as opposing."""
    import tp_gates as tpg

    monkeypatch.setattr(
        tpg,
        "_load_contradiction_reconcilers",
        lambda *a, **k: [
            {
                "reconciles": {"sub_skill": "selectivity", "verdict": "selective_but_broadly_normal"},
                "when_present": [{"sub_skill": "surface_modality", "verdict": "adc_preferred"}],
            }
        ],
    )
    monkeypatch.setattr(
        tpg,
        "_load_kill_capable_verdicts",
        lambda *a, **k: ({("selectivity", "selective_but_broadly_normal"): "contradiction"}, "test"),
    )
    subs = _merge(_sub("selectivity", "selective_but_broadly_normal"), _sub("surface_modality", "adc_preferred"))
    rows = {(r["short"], r["verdict"]): r["status"] for r in tpg._hard_gates_status(subs, [], [])}
    assert rows[("selectivity", "selective_but_broadly_normal")] == "reconciled"
    # no favorable surface → the same contradiction reads `opposing`
    subs2 = _merge(_sub("selectivity", "selective_but_broadly_normal"), _sub("surface_modality", "neither_viable"))
    rows2 = {(r["short"], r["verdict"]): r["status"] for r in tpg._hard_gates_status(subs2, [], [])}
    assert rows2[("selectivity", "selective_but_broadly_normal")] == "opposing"


# ---------------------------------------------------------------------------
# Thesis routing (Step 2b, v1.17.0) — a dependency `non_dependent` veto is IRRELEVANT for theses whose
# biology does not live on the dependency axis. Verified hermetically (no Bedrock, no packages) against
# the governed nomination_verdict_gate.thesis_axis_relevance block. Skips until contracts 2b lands.
# ---------------------------------------------------------------------------
_CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
_HAS_THESIS_ROUTING = bool(tp._load_thesis_axis_relevance(_CONTRACTS))
_thesis_skip = pytest.mark.skipif(
    not _HAS_THESIS_ROUTING, reason="contracts thesis_axis_relevance absent (land 2b-contracts)"
)


@_thesis_skip
def test_antigen_driven_makes_dependency_nondependent_irrelevant():
    """The 0/14-surface fix: an antigen_driven target's pooled non_dependent VETO is DROPPED (not just
    held) → the gate does not force a veto; it is recorded as a thesis suppression (never silent)."""
    subs = _sub("dependency", "non_dependent", "non-dependent-killer")
    action, hits, supps = tp._gate_recommendation(subs, thesis="antigen_driven")
    assert action is None, "antigen_driven: dependency non_dependent must not force a veto"
    assert any(s["suppressed_by"].get("kind") == "thesis_irrelevant_axis" for s in supps)
    # today's behaviour without the thesis (unresolved) — the veto STILL fires
    assert tp._gate_recommendation(subs, thesis="unresolved")[0] == "veto"
    assert tp._gate_recommendation(subs)[0] == "veto"  # no thesis passed → today's gate


@_thesis_skip
def test_thesis_routing_never_drops_pan_essential_killer():
    """SAFETY-CRITICAL: pan_essential_killer (broad-tox) still VETOes even for antigen_driven — the
    vocab lists only non_dependent as irrelevant."""
    subs = _sub("dependency", "pan_essential_killer", "pan-essential-killer")
    assert tp._gate_recommendation(subs, thesis="antigen_driven")[0] == "veto"
    assert tp._gate_recommendation(subs, thesis="tme_io")[0] == "veto"


@_thesis_skip
def test_thesis_routing_never_touches_safety_hold():
    """A safety concern still HOLDs regardless of thesis; only the dependency veto is dropped, so a
    surface antigen with a safety liability is still surfaced-with-hold, not a false GO."""
    subs = _merge(
        _sub("dependency", "non_dependent", "non-dependent-killer"),
        _sub("safety", "highly_constrained_safety_concern", "highly-constrained-safety-warning"),
    )
    action, hits, supps = tp._gate_recommendation(subs, thesis="antigen_driven")
    assert action == "hold", "safety hold must survive; only the dependency veto is dropped"
    assert {h["short"] for h in hits} == {"safety"}


@_thesis_skip
def test_oncogene_addiction_keeps_dependency_veto():
    """oncogene_addiction is where the dependency axis legitimately decides → the veto is UNCHANGED
    (the KRAS-class guardrail: routing must not soften the addiction thesis)."""
    subs = _sub("dependency", "non_dependent", "non-dependent-killer")
    assert tp._gate_recommendation(subs, thesis="oncogene_addiction")[0] == "veto"


@_thesis_skip
def test_tme_io_and_partner_conditional_and_neomorphic_drop_nondependent():
    for th in ("tme_io", "neomorphic_gof", "partner_conditional_sl"):
        subs = _sub("dependency", "non_dependent", "non-dependent-killer")
        assert tp._gate_recommendation(subs, thesis=th)[0] is None, f"{th}: non_dependent should be irrelevant"


# ---------------------------------------------------------------------------
# Thesis DECIDING axis (Step 3, vocab 1.21.0) — the framework's FIRST deterministic `nominate`.
#
# Verified HERMETICALLY on purpose. The eval scorecard panel reads COMMITTED packages (dated
# 2026-09-02), so it cannot show a verdict MOVE made today; a verdict-move claim has to be proven
# against the live policy + the live sub-verdict shapes, which is what these do. Each target's
# sub-verdicts + density card values below are the MEASURED values from a fresh Step-2 re-emit, not
# invented fixtures — so a test that says "FOLR1 nominates" is a claim about the real signal set.
# ---------------------------------------------------------------------------
_CONTRACTS_ENV = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
_HAS_DECIDERS = bool(tp._load_thesis_deciding_axes(_CONTRACTS_ENV)[0])
_decider_skip = pytest.mark.skipif(
    not _HAS_DECIDERS, reason="contracts thesis_deciding_axes absent (land Step-3 contracts first)"
)


def _density(value):
    """A surface-abundance-density card carrying a `density_floor_verdict`, hung off the selectivity
    sub-result (where the tumor-selectivity skill actually composes it)."""
    return {"cards": [{"card_id": "surface-abundance-density", "summary": {"density_floor_verdict": value}}]}


def _antigen(
    surface="adc_preferred_tce_unsafe",
    selectivity="selective_with_normal_liability",
    expression="tumor_broadly_expressed",
    density="above_adc_high_payload_floor",
    extra=None,
):
    subs = _merge(
        _sub("surface_modality", surface),
        _sub("selectivity", selectivity),
        _sub("expression", expression),
        extra or {},
    )
    if density is not None:
        subs["selectivity"].update(_density(density))
    return subs


def _nominate(subs, thesis="antigen_driven"):
    """Run the gate then the decider exactly as run.py's abstention branch does."""
    action, hits, _sup = tp._gate_recommendation(subs, thesis=thesis)
    if action:  # a kill fired → the decider is unreachable
        return action, None
    dec_action, rec = tp.thesis_nomination(subs, thesis, hits, contracts_repo=_CONTRACTS_ENV)
    return dec_action, rec


@_decider_skip
def test_folr1_dll3_msln_reach_nominate():
    """THE HEADLINE: the framework's first non-zero nominate count. All three are APPROVED-drug surface
    antigens (mirvetuximab / tarlatamab / the MSLN class) that previously landed at
    insufficient_evidence — the gate abstained (Step 2b dropped the false non_dependent veto) and the
    lower-bound clamp floored them, because nothing made surface a POSITIVE decider."""
    folr1 = _antigen(density="above_adc_high_payload_floor")
    msln = _antigen(density="above_adc_high_payload_floor")  # 50k copies/cell, grade B
    # DLL3 is the load-bearing case: 608 copies/cell = BELOW the soluble-TCE floor, yet tarlatamab is
    # APPROVED. The conjunct is MEASUREDNESS, not a floor value — the card itself documents
    # below_tce_floor as "a MODALITY caveat, NOT a target killer (CD19 = 110/cell...)", so gating on
    # the value would have the framework overrule an approved drug.
    dll3 = _antigen(density="below_tce_floor")
    for name, subs in (("FOLR1", folr1), ("MSLN", msln), ("DLL3", dll3)):
        action, rec = _nominate(subs)
        assert action == "nominate", f"{name} must reach nominate, got {action} ({rec})"
        assert rec["applied"] is True
        assert rec["deciding"]["short"] == "surface_modality"
        assert {c["short"] for c in rec["corroborating"]} == {"selectivity", "expression"}
        assert rec["measured_conjuncts"][0]["field"] == "density_floor_verdict"


@_decider_skip
def test_unmeasured_density_blocks_nominate_the_anti_blind_bound():
    """MUC13/CRC — favorable surface AND a surviving selectivity window, but density grade E
    (`unmeasured`). It must stay insufficient: the thesis's own ground-truth deciding sub-question was
    never measured, so nominating would be a GO invented by routing. This is the conjunct that keeps
    the panel's `framework_abstains_correctly` cases correct once the gate can mint a positive."""
    action, rec = _nominate(_antigen(density="unmeasured"))
    assert action is None
    assert any(u.startswith("unmeasured(surface-abundance-density.density_floor_verdict") for u in rec["unsatisfied"])


@_decider_skip
def test_absent_density_card_blocks_nominate():
    """Stronger form of the same bound: the card did not compose AT ALL. Absence of measurement is
    never evidence — a missing card must be UNSATISFIED, never neutral-and-therefore-passed."""
    action, rec = _nominate(_antigen(density=None))
    assert action is None
    assert any("unmeasured(" in u for u in rec["unsatisfied"])


@_decider_skip
def test_no_selectivity_window_blocks_nominate():
    """TACSTD2/BRCA (not_informative) and NECTIN4/BLCA (selective_but_broadly_normal): an antigen with
    no measured tumor-vs-normal window is not a nomination at any density. NECTIN4 is doubly blocked —
    selective_but_broadly_normal is also a positive_contradiction (a MEASURED opposing read)."""
    a, rec_a = _nominate(_antigen(selectivity="not_informative"))
    assert a is None and any(u.startswith("requires(selectivity=") for u in rec_a["unsatisfied"])
    b, rec_b = _nominate(_antigen(selectivity="selective_but_broadly_normal"))
    assert b is None
    # NOTE it is the `requires` conjunct that blocks it, NOT the opposing-verdict check: a favorable
    # surface verdict RECONCILES the selectivity contradiction (pre-existing contradiction_reconcilers
    # — the bulk-RNA no-window read is measured on the wrong basis for an antigen). Two independent
    # bounds is the point; asserting the reconciled one would encode a false mechanism.
    assert any(u.startswith("requires(selectivity=") for u in rec_b["unsatisfied"])


@_decider_skip
def test_a_measured_contradiction_on_any_other_axis_blocks_nominate():
    """The opposing-verdict bound, exercised on axes a favorable surface verdict does NOT reconcile.
    Same `positive_contradictions` load and same reconcilers `_positive_tier` uses — not the same set,
    since the tier blocks `strong` on the union with `positive_uncorroborated` and the decider on
    contradictions alone. Both verdicts below are LISTED contradictions, so for THESE the decider
    blocks and the scorecard reads `opposing` — the two surfaces agree. Scoped deliberately: the
    general claim ("the decider can never nominate what the scorecard reads as `opposing`") was FALSE
    when this test was written, refuted by `dependency: non_dependent` under a thesis that declares
    the axis irrelevant. It now holds FOR A CALLER THAT THREADS `thesis` — and still not for
    `thesis=None`, which is why the scoping stays explicit here rather than being assumed; see
    `test_decider_and_scorecard_agree_where_the_thesis_is_threaded`."""
    for short, verdict in (("cis_coherence", "expressed_cis_coupled_inert"), ("dependency", "broadly_dependent")):
        action, rec = _nominate(_antigen(extra=_sub(short, verdict)))
        assert action is None, f"{short}:{verdict} is a MEASURED opposing read — must block"
        assert any(f"opposing_measured_verdict({short}:{verdict})" in u for u in rec["unsatisfied"])


@_decider_skip
def test_v1200_uncorroborated_relabelling_moved_exactly_one_key_on_this_thesis():
    """PINS the vocab-1.20.0 interaction the 1.21.0 reland note records as CORRECT-BY-INTENT.

    GUARD 4 reads `positive_contradictions` ALONE (`_load_positive_signals`) and never unions in
    `positive_uncorroborated` — while tp_gates.py's own splitter warns in-source that "Callers that
    need the strong-block must use the union, never `contra` alone." This block is such a caller. So
    when v1.20.0 moved (dependency, discordant) and (selectivity, discordant_across_comparators) OUT
    of `positive_contradictions`, the set that blocks a nomination shrank by exactly those two keys.

    Measured PER THESIS, because set membership is not yet a behaviour:
      * (selectivity, discordant_across_comparators) is INERT — but the complete reason is three
        branches, not the one first recorded here ("`verdict_in` excludes it"). The selectivity
        resolver's `post_resolver_clamp` can rewrite this verdict before the gate ever sees it, so
        the reachable branches are: (i) the evidence-gated UPGRADE fires and the gate sees
        `field_effect_tumor_selective`; (ii) a downgrade veto fires and it sees
        `selective_with_normal_liability`; (iii) no clamp fires and the `requires` conjunct's
        `verdict_in` refuses it. In every branch the key is either clamped away or excluded, so the
        conclusion holds — but only branch (iii) is the one `verdict_in` explains;
      * (dependency, discordant) is LIVE — `dependency` appears NOWHERE in the antigen_driven block
        (not `deciding`, not in `requires`), so nothing else catches it.

    Pinned as correct-by-intent rather than fixed: `discordant` means THE AXIS'S OWN ARMS DISAGREED,
    i.e. the axis resolved nothing, and declining to block on an unresolved axis is the same
    correction this block already makes BY HAND via `irrelevant_contradiction_axes` for
    tractability_sm (the FOLR1/OV case), reached from the other direction. If a future change unions
    `positive_uncorroborated` into GUARD 4, the first assertion reds and forces that decision to be
    taken deliberately instead of arriving silently.
    """
    # LIVE — the one key whose blocking behaviour v1.20.0 actually changed.
    action, rec = _nominate(_antigen(extra=_sub("dependency", "discordant")))
    assert action == "nominate", f"dependency:discordant must not block after v1.20.0, got {action} ({rec})"

    # INERT — also out of the contradiction set, but the `requires` conjunct still refuses it. Assert
    # WHICH bound blocks: asserting the opposing one would encode the mechanism this pin denies.
    action, rec = _nominate(_antigen(selectivity="discordant_across_comparators"))
    assert action is None
    assert any(u.startswith("requires(selectivity=") for u in rec["unsatisfied"])
    assert not any("opposing_measured_verdict" in u for u in rec["unsatisfied"])

    # The set-membership facts both behaviours rest on, asserted directly so that a vocabulary move
    # is diagnosed as a vocabulary move and not as a mysterious behaviour change.
    _pos, contra, _cfg, _s = tp._load_positive_signals(_CONTRACTS_ENV)
    uncorr, _s2 = tp._load_positive_uncorroborated(_CONTRACTS_ENV)
    for key in (("dependency", "discordant"), ("selectivity", "discordant_across_comparators")):
        assert key not in contra, f"{key} is back in positive_contradictions — v1.20.0 regressed"
        assert key in uncorr, f"{key} is missing from positive_uncorroborated"

    # The guardrails that DO survive, measured on THIS thesis rather than inferred from the general
    # `gated`-disposition rule — which is what falsified the note's first draft. v1.17.0's
    # thesis_axis_relevance drops the non_dependent veto for antigen_driven by design (the
    # 0/14-surface fix), so `non_dependent` reaches the decider and nominates; the surviving refusals
    # are pan_essential_killer (the veto v1.17.0 never drops) and broadly_dependent (still listed).
    action, rec = _nominate(_antigen(extra=_sub("dependency", "pan_essential_killer")))
    assert action == "veto" and rec is None, "pan_essential_killer must keep the decider unreachable"
    action, rec = _nominate(_antigen(extra=_sub("dependency", "broadly_dependent")))
    assert action is None
    assert any("opposing_measured_verdict(dependency:broadly_dependent)" in u for u in rec["unsatisfied"])
    action, _rec = _nominate(_antigen(extra=_sub("dependency", "non_dependent")))
    assert action == "nominate", "v1.17.0 makes non_dependent irrelevant HERE; this is not v1.20.0's doing"


@_decider_skip
def test_decider_and_scorecard_agree_where_the_thesis_is_threaded():
    """PINS the decider x scorecard table on `dependency`, and the CLOSURE of its one disagreement.

    REPLACES `test_decider_and_scorecard_agree_except_where_thesis_scoping_is_invisible_to_the_scorecard`,
    which pinned the defect OPEN on purpose — its last assertion was
    `"thesis" not in signature(_gate_scorecard).parameters`, so closing the hole could not be done
    silently. This change falsifies that assertion by design; the guard did its job and is retired
    rather than relaxed. (A pin whose subject gets FIXED must be rewritten, not deleted: deleting it
    loses the record that the state was once real, and relaxing it is how a pin goes vacuous.)

    Two surfaces read the same 7-key `positive_contradictions` block and must not drift apart
    silently: `thesis_nomination` GUARD 4 decides block-vs-nominate, `_gate_scorecard._status`
    decides the WORD a reader sees on that axis's row. Both are asserted here from ONE
    `sub_results`, because reading them from two fixtures would let a fixture difference
    masquerade as a surface disagreement (it already did once during this change: a hand-rolled
    `_density` stand-in that omitted the density CARD made every row read `block`).

    WHAT WAS WRONG: `thesis_axis_relevance` (v1.17.0 / Step-2b) drops the `non_dependent` veto for
    `antigen_driven` by design — 0 of 14 surface antigens had ever been adjudicated on surface
    biology before it. `_gate_recommendation` and `_hard_gates_status` applied that scoping;
    `_gate_scorecard` took `modality` but no `thesis`, so it classified `non_dependent` through
    `kill_map` and said `opposing`. Per the same 0/14 rationale a surface antigen measuring
    `non_dependent` is the TYPICAL case, so a single `nomination.json` asserted both "veto
    suppressed because the thesis makes this axis irrelevant" and "this axis is opposing evidence".

    TWO REACHES, MEASURED, because the mislabel contradicted two surfaces with two denominators
    (asserted below rather than narrated): `thesis_axis_relevance` holds 4 of the 5 canonical theses
    and all four drop this key, so the ARTIFACT self-contradiction (hard_gates `suppressed` vs
    scorecard `opposing`) had reach 4/5; `thesis_deciding_axes` holds 1 (`antigen_driven`), and an
    unregistered thesis hits GUARD 3 and cannot nominate at all, so the DECIDER-side divergence had
    reach 1/5. Both are closed here.

    Note what this does NOT say: the v1.20.0 `uncorroborated` relabel introduced NO divergence. On
    both relabelled keys the surfaces agree (`coverage_gap`), because `_status` tests
    `uncorroborated` before the kill/contradiction test.
    """
    import inspect

    # The fix's own preconditions, asserted first so a signature drift reads as a signature failure
    # rather than as a mysterious table failure twenty lines down.
    params = inspect.signature(tp._gate_scorecard).parameters
    assert "thesis" in params, "_gate_scorecard no longer takes a thesis — the divergence below reopens"
    assert params["thesis"].default is None, (
        "the `thesis` default is no longer None; a non-None default would change output for every "
        "existing caller that passes no thesis"
    )

    # (verdict, decider action, scorecard status WITH the thesis threaded, scorecard status WITHOUT)
    # MEASURED, not derived: vocab 1.21.0 as read from contracts c88c6e04, the tree
    # skills-validate.yml actually pins.
    EXPECTED = [
        ("pan_essential_killer", "veto", "opposing", "opposing"),  # kill: decider never reached
        ("non_dependent", "nominate", "neutral", "opposing"),  # ⚠️ THE FIX: was `opposing` both ways
        ("broadly_dependent", None, "opposing", "opposing"),  # listed contradiction: both block
        ("discordant", "nominate", "coverage_gap", "coverage_gap"),  # v1.20.0: surfaces already agreed
    ]
    for verdict, want_action, want_status, want_unthreaded in EXPECTED:
        subs = _antigen(extra=_sub("dependency", verdict))
        action, _rec = _nominate(subs)
        rows = tp._gate_scorecard(subs, contracts_repo=_CONTRACTS_ENV, thesis="antigen_driven")
        status = next(r["status"] for r in rows if r["short"] == "dependency")
        assert action == want_action, f"dependency:{verdict} decider: want {want_action}, got {action}"
        assert status == want_status, f"dependency:{verdict} scorecard: want {want_status}, got {status}"
        # THE INVARIANT ITSELF, stated as the implication it actually is rather than as a table
        # coincidence: a nomination must never sit beside an `opposing` label for the same axis.
        assert not (action == "nominate" and status == "opposing"), (
            f"dependency:{verdict} — decider nominates while the scorecard calls the same axis "
            "opposing; that is the self-contradiction this test exists to prevent"
        )
        # BACKWARD COMPATIBILITY, asserted per row: with no thesis the OLD label stands. This is the
        # half that makes `thesis=None` safe for every caller that has not been updated, and it is
        # asserted rather than assumed because "the default is None" does not by itself prove the
        # None path is unchanged.
        unthreaded = next(
            r["status"] for r in tp._gate_scorecard(subs, contracts_repo=_CONTRACTS_ENV) if r["short"] == "dependency"
        )
        assert unthreaded == want_unthreaded, (
            f"dependency:{verdict} unthreaded scorecard: want {want_unthreaded}, got {unthreaded}"
        )

    # ── the two denominators, asserted (they are what makes the reach claim above checkable) ──────
    relevance = tp._load_thesis_axis_relevance(_CONTRACTS_ENV)
    decider_theses = {b.get("thesis") for b in tp._load_thesis_deciding_axes(_CONTRACTS_ENV)[0]}
    DROPPING = ("antigen_driven", "tme_io", "neomorphic_gof", "partner_conditional_sl")
    for t in DROPPING:
        assert ("dependency", "non_dependent") in relevance.get(t, set()), (
            f"{t} no longer drops the non_dependent veto — the divergence this test closes had a "
            "different cause than it documents; re-derive rather than re-pinning"
        )
    # `oncogene_addiction` is the CONTROL, and it is the assertion that makes the fix two-sided: it
    # is ABSENT from the relevance map, so the veto stands, `forced` stays `veto`, and the scorecard
    # must STILL read `opposing`. A blanket `if verdict == "non_dependent": return "neutral"` would
    # pass every assertion above and red here.
    assert ("dependency", "non_dependent") not in relevance.get("oncogene_addiction", set()), (
        "oncogene_addiction now drops the non_dependent veto; this test's control is no longer a control"
    )
    subs = _antigen(extra=_sub("dependency", "non_dependent"))
    forced, hits, sup = tp._gate_recommendation(subs, thesis="oncogene_addiction")
    assert forced == "veto", f"oncogene_addiction must keep the non_dependent veto, got {forced}"
    control = next(
        r["status"]
        for r in tp._gate_scorecard(subs, contracts_repo=_CONTRACTS_ENV, thesis="oncogene_addiction")
        if r["short"] == "dependency"
    )
    assert control == "opposing", (
        f"a thesis that does NOT declare the axis irrelevant must still read opposing, got {control} — "
        "the guard is relabelling on the verdict alone instead of on the thesis's declared scope"
    )

    # ── FAIL-CLOSED on an unknown thesis: an unregistered name must drop NOTHING ───────────────────
    # Mirrors `thesis_nomination`'s GUARD 3. Compared as whole row LISTS, not one status, so a future
    # change that quietly moves some other row under an unknown thesis also reds.
    assert tp._gate_scorecard(subs, contracts_repo=_CONTRACTS_ENV, thesis="not_a_registered_thesis") == (
        tp._gate_scorecard(subs, contracts_repo=_CONTRACTS_ENV)
    ), "an unregistered thesis changed the scorecard; unknown scoping must be inert, not permissive"

    # ── PAIR A: the ARTIFACT self-contradiction, across all four dropping theses ───────────────────
    # This is the 4/5 reach. `hard_gates[].status` and `gate_scorecard[].status` are emitted into the
    # SAME nomination.json, so they are read side by side by definition; asserting them from one
    # `sub_results` is what makes the comparison meaningful.
    for t in DROPPING:
        forced, hits, sup = tp._gate_recommendation(subs, thesis=t)
        assert forced is None, f"{t} should drop the non_dependent veto, got forced={forced}"
        hg = tp._hard_gates_status(subs, hits, sup)
        hg_status = next(
            e["status"] for e in hg if (e.get("short"), e.get("verdict")) == ("dependency", "non_dependent")
        )
        sc_status = next(
            r["status"]
            for r in tp._gate_scorecard(subs, contracts_repo=_CONTRACTS_ENV, thesis=t)
            if r["short"] == "dependency"
        )
        assert hg_status == "suppressed", f"{t}: hard_gates should read suppressed, got {hg_status}"
        assert not (hg_status == "suppressed" and sc_status == "opposing"), (
            f"{t}: hard_gates says the veto was SUPPRESSED because the thesis makes this axis "
            f"irrelevant, while the scorecard calls the same axis opposing ({sc_status}) — one "
            "artifact contradicting itself"
        )
        # PAIR B is vacuous for three of the four (GUARD 3 → the decider cannot nominate), and that
        # is asserted rather than skipped so the 1/5-vs-4/5 distinction cannot rot into "4/5" twice.
        if t not in decider_theses:
            action, rec = tp.thesis_nomination(subs, t, hits, contracts_repo=_CONTRACTS_ENV)
            assert action is None, f"{t} is not in thesis_deciding_axes; GUARD 3 must return None, got {action}"

    # The AGREEING half, on the other relabelled axis: selectivity's uncorroborated verdict blocks on
    # a `requires` conjunct (not on the opposing bound) and reads `coverage_gap`, not `opposing`.
    subs = _antigen(selectivity="discordant_across_comparators")
    action, rec = _nominate(subs)
    rows = tp._gate_scorecard(subs, contracts_repo=_CONTRACTS_ENV, thesis="antigen_driven")
    assert action is None
    assert next(r["status"] for r in rows if r["short"] == "selectivity") == "coverage_gap"
    assert not any("opposing_measured_verdict" in u for u in rec["unsatisfied"])

    # AND THE FIXED STATE OCCURRED IN REAL DATA, so this was not a constructed edge case: the frozen
    # 629-row polarity projection (37 pairs run 2026-09-08/09) carries (`non_dependent`, `opposing`)
    # on 24 of its 37 dependency rows -- the DOMINANT dependency state.
    # ⚠️ THE FIXTURE IS DELIBERATELY NOT REGENERATED, and it is now stale for TWO independent reasons
    # that look identical from inside this file: it is pre-1.20.0 (the `uncorroborated` relabel) AND
    # pre-2026-09-15 (this fix). Its 24 rows are what a run WITHOUT a threaded thesis produced. Left
    # frozen because the fixture's job is to record what the surfaces DID emit: re-freezing it would
    # erase the only durable evidence that the divergence was real and POPULOUS rather than
    # constructed, which is exactly the evidence a future reader needs to judge whether this guard
    # still earns its place.
    # PINNED AS A PROPERTY (>= 1), NOT AS THE COUNT: 24 is this vintage's measurement of a fixture
    # this test does not own, so `== 24` would red on any legitimate re-freeze and get re-pinned,
    # which is how a count-pin goes vacuous.
    projection = Path(__file__).resolve().parent / "fixtures" / "polarity_surface_projection.json"
    if projection.is_file():  # fail-soft: this test's subject is the gate, not the fixture's presence
        proj_rows = json.loads(projection.read_text())["rows"]
        dep_rows = [r for r in proj_rows if r.get("axis") == "dependency"]
        assert dep_rows, "projection carries no dependency rows -- the corpus claim cannot be checked"
        live = [
            r for r in dep_rows if (r.get("sub_verdict"), r.get("scorecard_status")) == ("non_dependent", "opposing")
        ]
        assert live, (
            f"0 of {len(dep_rows)} frozen dependency rows read (non_dependent, opposing); measured 24 of 37 on "
            "2026-09-15 -- the fixture may have been regenerated post-fix, which DELETES the evidence that this "
            "divergence was real; recover the vintage rather than deleting this assertion"
        )


@_decider_skip
def test_annotation_only_and_no_viable_arm_surface_verdicts_block_nominate():
    """The 2d bound, admissibility half: 'routing must never invent a GO — admissibility of
    surface-as-decider is co-conditioned on a FAVORABLE MEASURED verdict.' An annotation-only or
    no-viable-arm surface read is not a favorable measured verdict. `surface_annotation_only_unconfirmed`
    is the DECOY shape (a gene called a surface protein by annotation alone)."""
    for verdict in (
        "neither_viable",
        "shed_dominant_opposed",
        "tce_unsafe_normal_liability",
        "surface_annotation_only_unconfirmed",
        "pmhc_tce_supported",  # STEAP1/PRAD — single-axis IEDB support, only ever `supportive`
    ):
        action, rec = _nominate(_antigen(surface=verdict))
        assert action is None, f"surface={verdict} must not decide a nomination"
        assert any(u.startswith("deciding(surface_modality=") for u in rec["unsatisfied"])


@_decider_skip
def test_a_surviving_kill_makes_the_decider_unreachable():
    """F1 SAFETY BY CONTROL FLOW, the load-bearing design property. The decider lives in the
    else-branch of the kill gate, so any surviving veto/hold means it never runs. Asserted BOTH ways:
    via the caller pattern (a fired action short-circuits) AND by calling thesis_nomination directly
    with non-empty `hits` (its own GUARD 1), so the safety does not depend on caller discipline."""
    # pan_essential_killer survives thesis routing (it is broad-tox, real regardless of thesis)
    killed = _antigen(extra=_sub("dependency", "pan_essential_killer", "pan-essential-killer"))
    action, rec = _nominate(killed)
    assert action == "veto" and rec is None
    # a surviving HOLD also short-circuits. subtype_fit is used rather than a safety hold on purpose —
    # see test_safety_holds_on_an_adc_viable_antigen_are_lifted_by_exists_safe_modality below.
    held = _antigen(extra=_sub("subtype_fit", "subtype_specific_non_dependence", "subtype-non-dependence"))
    assert _nominate(held)[0] == "hold"
    # GUARD 1 directly: even handed a perfectly satisfying signal set, a non-empty hits list refuses
    assert tp.thesis_nomination(_antigen(), "antigen_driven", [{"short": "safety", "action": "hold"}]) == (None, None)


@_decider_skip
def test_safety_holds_on_an_adc_viable_antigen_are_lifted_by_exists_safe_modality():
    """★PINNED CONSEQUENCE, measured not assumed. All FOUR safety holds are members of
    `_SAFETY_WT_LOSS_CONCERNS`, and the pre-existing `exists_safe_modality` suppressor lifts a WT-loss
    hold when a biologics arm is viable ("an ADC/TCE does not deplete WT protein"). Before Step 3 that
    suppression could only ever yield ABSTENTION; now it yields a GO — so the consequence is pinned
    here rather than discovered in production.

    It is NOT tightened, because the measured cohort says tightening costs more than it saves:
    FOLR1/OV (APPROVED, mirvetuximab) fires `normal_tissue_protein_safety_concern` and DLL3/SCLC
    (APPROVED, tarlatamab) fires `human_genetics_safety_concern`, whereas the phase-3 FAILURE CEACAM5
    fires NO safety hold at all (`tolerant_reduced_safety_risk`). Making these non-suppressible would
    block both approved drugs and still nominate CEACAM5 — strictly worse. The honest reading is that
    the safety axis over-calls on this cohort; the RESIDUAL RISK is that
    `normal_tissue_protein_safety_concern` is not really a WT-loss liability at all (an ADC against a
    normal-tissue-expressed antigen is the on-target/off-tumor risk, which a biologic makes WORSE, not
    n/a) — tracked with the same-organ-normal-liability gap, not fixed here."""
    for verdict in (
        "highly_constrained_safety_concern",
        "human_genetics_safety_concern",
        "pan_essential_broad_tox_concern",
        "normal_tissue_protein_safety_concern",
    ):
        subs = _antigen(extra=_sub("safety", verdict, "some-safety-rule"))
        gate_action, _hits, supps = tp._gate_recommendation(subs, thesis="antigen_driven")
        assert gate_action is None, f"{verdict}: expected the WT-loss suppressor to lift the hold"
        assert any(s["suppressed_by"].get("kind") == "exists_safe_modality" for s in supps), (
            f"{verdict}: the hold must be RECORDED as suppressed, never silently absent"
        )
        assert _nominate(subs)[0] == "nominate"
    # THE GUARDRAIL that keeps this from being a blanket defeat: the suppressor needs a VIABLE
    # biologics arm. With an UNFAVORABLE surface verdict (the decoy / GRIN2D shape) the hold STANDS.
    unfavorable = _antigen(surface="tce_unsafe_normal_liability", selectivity="not_informative")
    unfavorable.update(_sub("safety", "highly_constrained_safety_concern", "hc"))
    assert tp._gate_recommendation(unfavorable, thesis="antigen_driven")[0] == "hold"


@_decider_skip
def test_decoys_never_reach_the_decider():
    """ACTB / GAPDH housekeeping decoys. Two independent blocks: the gate fires a HOLD on them
    (broadly_high_expression normal-tissue liability / no window), so the stage is unreachable; and
    even with the gate forced to abstain their surface read is annotation-only and their density
    unmeasured. `broadly_high_expression` is deliberately EXCLUDED from the expression requirement so
    a housekeeping gene can never satisfy the presence conjunct."""
    decoy = _antigen(
        surface="surface_annotation_only_unconfirmed",
        selectivity="not_selective",
        expression="broadly_high_expression",
        density="unmeasured",
    )
    action, rec = _nominate(decoy)
    assert action != "nominate"
    if rec is not None:  # gate abstained → every conjunct must independently fail
        assert len(rec["unsatisfied"]) >= 3, rec["unsatisfied"]


@_decider_skip
def test_adar1_the_pinned_false_positive_stays_blocked():
    """ADAR1 — a pinned dangerous_false_positive (declined). Blocked on FOUR conjuncts at once
    (surface insufficient, selectivity data_unavailable, no measured density, and no favorable
    decider), which is why it is robust rather than luckily-excluded."""
    action, rec = _nominate(
        _antigen(surface="insufficient", selectivity="data_unavailable", expression="insufficient", density=None)
    )
    assert action is None
    assert len(rec["unsatisfied"]) >= 3


@_decider_skip
def test_only_the_antigen_driven_thesis_can_nominate():
    """BLAST-RADIUS pin, and the KRAS/oncogene_addiction golden. An unregistered thesis reproduces the
    previous behaviour EXACTLY: no record at all, so nothing downstream can change. Handing the same
    perfect antigen signal set to every other thesis must nominate NOTHING."""
    subs = _antigen()
    for th in ("oncogene_addiction", "unresolved", "tme_io", "neomorphic_gof", "partner_conditional_sl", None):
        assert tp.thesis_nomination(subs, th, [], contracts_repo=_CONTRACTS_ENV) == (None, None), th


@_decider_skip
def test_inverted_fallback_a_broken_policy_nominates_nothing(tmp_path):
    """The 4th fail-closed path. For a KILL loader 'fail closed' means conservative-and-complete; for a
    loader that can mint a GO it must mean EMPTY. An absent or malformed vocab must nominate NOTHING —
    the opposite of the kill-gate convention, and the reason this loader is separate."""
    # (i) the whole vocab file is MISSING → fallback, empty
    assert tp._load_thesis_deciding_axes(tmp_path) == ([], "fallback")
    assert tp.thesis_nomination(_antigen(), "antigen_driven", [], contracts_repo=tmp_path) == (None, None)
    vocab = tmp_path / "vocabularies"
    vocab.mkdir()
    # (ii) the file parses but the BLOCK is absent (a pre-Step-3 contracts checkout) → empty, and
    # reported as `vocab` rather than `fallback` because nothing failed: there is simply no policy.
    gate = vocab / "nomination_verdict_gate.yaml"
    gate.write_text("enum_id: nomination_verdict_gate\ngates: []\n")
    assert tp._load_thesis_deciding_axes(tmp_path) == ([], "vocab")
    assert tp.thesis_nomination(_antigen(), "antigen_driven", [], contracts_repo=tmp_path) == (None, None)
    # (iii) the file is MALFORMED → fallback, empty (never permissive)
    gate.write_text("{[not: valid: yaml")
    assert tp._load_thesis_deciding_axes(tmp_path) == ([], "fallback")
    assert tp.thesis_nomination(_antigen(), "antigen_driven", [], contracts_repo=tmp_path) == (None, None)
    # (iv) a block that OMITS its corroboration/measured conjuncts must not become a bare
    # decider-is-sufficient rule even though the contracts tests forbid authoring one.
    gate.write_text(
        "enum_id: nomination_verdict_gate\nthesis_deciding_axes:\n"
        "  - thesis: antigen_driven\n    action: nominate\n    rationale: x\n"
        "    deciding: {sub_skill: surface_modality, favorable_verdicts: [adc_preferred_tce_unsafe]}\n"
    )
    action, rec = tp.thesis_nomination(_antigen(), "antigen_driven", [], contracts_repo=tmp_path)
    assert action is None
    assert any(u.startswith("malformed_block") for u in rec["unsatisfied"])


@_decider_skip
def test_ceacam5_is_the_known_false_positive_this_ships_with():
    """★KNOWN LIMITATION, asserted rather than hidden. CEACAM5/LUAD is a phase-3 FAILURE that SATISFIES
    the conjunction — and reads BETTER than the approved FOLR1 on every wired axis
    (strong_tumor_selective vs selective_with_normal_liability; strongly_upregulated_in_tumor vs
    tumor_broadly_expressed; 76k copies/cell at grade B). Pinned as a test so the FP is a tracked,
    visible cost with a named owner (known_gap_watchlist.same_organ_normal_liability), and so that
    wiring the same-organ-normal-liability discriminator has a test to flip."""
    action, rec = _nominate(_antigen(selectivity="strong_tumor_selective", expression="strongly_upregulated_in_tumor"))
    assert action == "nominate", "if this stops nominating, flip CEACAM5 back to validated_lane in contracts"
    assert rec["applied"] is True


@_decider_skip
def test_deciding_axis_router_attributes_the_nomination_to_surface():
    """The axis-attribution metric this arc exists to move: the surface cohort measured 0.0 because
    every surface target attributed to `abstention_coverage_gaps` (in default biology-first mode DLL3
    carries ZERO positive hits — surface positives are excluded_positive_modality_scoped unless a
    --modality is declared, so the positive tier could not carry the attribution either)."""
    subs = _antigen()
    action, rec = _nominate(subs)
    assert action == "nominate"
    da = tp._deciding_axis(subs, None, [], positive_hits=[], thesis_record=rec)
    assert da["basis"] == "thesis_decider"
    assert da["deciding_axis"]["short"] == "surface_modality"
    assert da["deciding_axis"]["framework_can_evidence"] == "captured"
    # a DECLINED record must NOT claim an attribution — the framework did not decide
    _a, declined = _nominate(_antigen(density="unmeasured"))
    assert tp._deciding_axis(subs, None, [], positive_hits=[], thesis_record=declined)["basis"] != "thesis_decider"


@_decider_skip
def test_value_in_card_field_trigger_form():
    """The `value_in` trigger form Step 3 added to _trigger_label (a graded enum needed one policy
    entry, not one per admissible token). Fail-closed on the shapes that must never match."""
    subs = _antigen(density="above_tce_floor_below_adc")
    card, field = "surface-abundance-density", "density_floor_verdict"
    assert tp._trigger_label({"card_id": card, "field": field, "value_in": ["above_tce_floor_below_adc"]}, set(), subs)
    assert tp._trigger_label({"card_id": card, "field": field, "value_in": ["below_tce_floor"]}, set(), subs) is None
    assert tp._trigger_label({"card_id": card, "field": field}, set(), subs) is None  # vacuous → never matches
    assert tp._trigger_label({"card_id": card, "field": field, "value_in": "notalist"}, set(), subs) is None
    assert tp._trigger_label({"card_id": card, "field": field, "value": "above_tce_floor_below_adc"}, set(), subs)


@_decider_skip
def test_small_molecule_chemistry_discord_does_not_block_an_antibody_thesis():
    """FOUND BY A GROUNDED RUN, not by inspection. The real FOLR1/OV profile reads
    `tractability_sm: discordant` — a positive_contradiction — and the opposing-verdict bound was
    therefore blocking the nomination of an APPROVED ADC target on a SMALL-MOLECULE-CHEMISTRY
    disagreement. That is the ontology defect this whole remediation removes (ANY-OF axis read as a
    dependency-AND), reappearing inside my own new guard.

    The fix is GOVERNED, not a code special-case: `irrelevant_contradiction_axes` in the thesis's
    vocab block, bounded by contracts tests (may not name a kill-capable axis, may not name an axis
    in the thesis's own conjunction, must actually carry a contradiction). Scope check, so this is
    not an overfit: `tractability_sm: discordant` is the measured read on FOLR1, NECTIN4 and TACSTD2
    (all APPROVED) plus CEACAM5 — it is the cohort-wide read for antibody targets, not a FOLR1
    quirk. A contradiction on an axis NOT whitelisted still blocks (asserted below)."""
    action, rec = _nominate(_antigen(extra=_sub("tractability_sm", "discordant")))
    assert action == "nominate", f"an antibody thesis must not be blocked by SM chemistry: {rec}"
    # the whitelist is per-axis, not a blanket amnesty: another axis's contradiction still blocks,
    # and it blocks even when co-present with the whitelisted one.
    action, rec = _nominate(
        _antigen(
            extra=_merge(_sub("tractability_sm", "discordant"), _sub("cis_coherence", "expressed_cis_coupled_inert"))
        )
    )
    assert action is None
    assert any("cis_coherence:expressed_cis_coupled_inert" in u for u in rec["unsatisfied"])
    assert not any("tractability_sm" in u for u in rec["unsatisfied"])


# ---------------------------------------------------------------------------
# Reconciling the TWO deterministic nominate paths (positive tier + thesis decider).
# These were only assertable once the decision was hoisted out of run.py's main() into a pure
# function — inline, the two writers could only be checked by re-implementing them in the test,
# which is how the divergences below survived being written twice.
# ---------------------------------------------------------------------------

_TR = {"thesis": "antigen_driven", "deciding": {"short": "surface_modality", "verdict": "adc_preferred_tce_unsafe"}}
_HIT = {"short": "dependency", "verdict": "selectively_dependent", "weight": "dominant"}


def _rec(**kw):
    base = dict(
        thesis_action=None,
        thesis_record=None,
        tier=None,
        tier_nominates=False,
        pos_hits=[],
        clamped=False,
        llm_value="insufficient_evidence",
    )
    base.update(kw)
    return tp.reconcile_positive_nomination(**base)


def test_reconciler_never_writes_fired():
    """THE defect worth a dedicated test. `recommendation_gate["fired"]` means "a RESTRAINT gate
    fired" to two consumers: tp_facets silences the DISSENT record when an evidence-band block
    co-occurs with `fired` (hiding the disagreement most worth surfacing), and cross-evidence-
    hypothesis maps fired+no-suppression to `declined` — INVERTING a nomination into a kill. One of
    the two independently-written nominate paths set it. No combination may."""
    for kw in (
        dict(thesis_action="nominate", thesis_record=_TR),
        dict(tier="strong", tier_nominates=True, pos_hits=[_HIT]),
        dict(thesis_action="nominate", thesis_record=_TR, tier="strong", tier_nominates=True, pos_hits=[_HIT]),
        dict(thesis_action="nominate", thesis_record=_TR, clamped=True),
    ):
        _v, patch = _rec(**kw)
        assert "fired" not in patch, f"{kw} wrote `fired` — inverts a nomination into a kill"


def test_reconciler_is_a_no_op_when_neither_path_fires():
    assert _rec() == (None, {})
    # a tier that exists but does not reach the nominating bar is NOT a nomination
    assert _rec(tier="moderate", tier_nominates=False, pos_hits=[_HIT]) == (None, {})


def test_thesis_decider_wins_the_attribution_when_both_paths_fire():
    """The write collision: both paths minted the same VALUE but the later writer relabelled WHICH
    axis carried the target. Precedence goes to the thesis decider because it is the strictly more
    specific claim (a named deciding axis + a necessity conjunction + a measuredness conjunct, versus
    a thesis-agnostic count of independent dimensions). Agreement is recorded, not discarded."""
    value, patch = _rec(
        thesis_action="nominate", thesis_record=_TR, tier="strong", tier_nominates=True, pos_hits=[_HIT]
    )
    assert value == "nominate"
    assert patch["forced_by"] == "thesis_decider"
    assert patch["also_reached_by"]["paths"] == ["positive_tier"]
    assert "positive tier reached `strong`" in patch["also_reached_by"]["detail"]
    # the losing path's agreement must not be silently dropped, and must not overwrite triggered_by
    assert patch["triggered_by"] == []  # the thesis record's corroborators, not the tier's hits


def test_either_path_alone_still_forces_and_names_itself():
    value, patch = _rec(thesis_action="nominate", thesis_record=_TR)
    assert (value, patch["forced_by"]) == ("nominate", "thesis_decider")
    assert "also_reached_by" not in patch
    value, patch = _rec(tier="strong", tier_nominates=True, pos_hits=[_HIT])
    assert (value, patch["forced_by"]) == ("nominate", "positive_tier")
    assert patch["triggered_by"][0]["policy_source"] == "positive_tier"
    assert patch["triggered_by"][0]["action"] == "nominate"


_INTERLOCK_CASES = (
    dict(thesis_action="nominate", thesis_record=_TR),
    dict(tier="strong", tier_nominates=True, pos_hits=[_HIT]),
    dict(thesis_action="nominate", thesis_record=_TR, tier="strong", tier_nominates=True, pos_hits=[_HIT]),
)


def test_a_fired_conjunction_nominates_over_an_llm_authored_negative():
    """The SETTLED policy (2026-09-11), and it is ONE answer for BOTH paths — the third divergence was
    that they answered differently, so the framework's most consequential output depended on which path
    happened to fire.

    Why override: the #1291 clamp exists to floor an LLM negative with NO RULE behind it. A fired
    conjunction is the rule it was waiting for, so deferring to the LLM here inverts the clamp's own
    purpose. MEASURED on the grounded full-LLM FOLR1/OV run (APPROVED — mirvetuximab): the LLM authored
    `hold`, the clamp demoted it, and the conjunction was fully satisfied. Withholding would have
    suppressed an approved drug on a rule-less opinion."""
    for kw in _INTERLOCK_CASES:
        value, patch = _rec(clamped=True, llm_value="hold", **kw)
        assert value == "nominate", f"{kw} deferred to a rule-less LLM negative"
        assert "nominate_withheld" not in patch
        assert patch["overridden"] is True  # the LLM said hold; the rule overrode it


def test_nominating_over_a_negative_narrative_records_the_disagreement():
    """The PRICE of the override, made explicit. The report now carries a positive VALUE beside prose
    arguing the negative; that disagreement is the most decision-relevant thing on the page, so it is
    emitted as a first-class record rather than left for a reader to infer. Absent when no clamp
    fired — it must not decorate the ordinary agreeing case."""
    for kw in _INTERLOCK_CASES:
        _v, patch = _rec(clamped=True, llm_value="hold", **kw)
        rec = patch["nominated_over_llm_negative"]
        assert rec["llm_recommendation"] == "hold"
        assert rec["forced"] == "nominate"
        assert rec["path"] in {"thesis_decider", "positive_tier"}
        assert "standing dissent" in rec["detail"]
        _v2, patch2 = _rec(**kw)  # no clamp
        assert "nominated_over_llm_negative" not in patch2


def test_the_interlock_can_be_restored_to_withhold_for_both_paths_at_once():
    """Whichever way the policy lands it must land for BOTH paths — the point of the single flag. Pins
    that the withhold reading is still reachable in one place, and that it RECORDS the near-miss."""
    for kw in _INTERLOCK_CASES:
        value, patch = _rec(clamped=True, llm_value="hold", allow_over_llm_authored_negative=False, **kw)
        assert value is None
        assert patch["nominate_withheld"]["reason"] == "llm_authored_negative"
        assert patch["nominate_withheld"]["llm_recommendation"] == "hold"
        assert "forced_recommendation" not in patch
        assert patch["nominate_withheld"]["path"] in {"thesis_decider", "positive_tier"}


# ---------------------------------------------------------------------------
# The anti-blind bound is a CROSS-PATH invariant, not a thesis-path-only one.
# The thesis decider carries `requires_measured_card_field` and REFUSES to nominate a surface antigen
# whose deciding-axis ground-truth field (surface-abundance-density.density_floor_verdict) is
# `unmeasured`. The positive tier has no such conjunct. Under `--modality` the favorable surface
# verdicts become tier-eligible, so a surface antigen the decider refused FOR BLINDNESS could still
# nominate via the tier — the framework minting a GO on a target it cannot see the deciding axis of
# (the "nominate while blind" the release scope forbids). MUC13/COADREAD is the live case:
# `forced=nominate by=positive_tier density=unmeasured` while the decider's unsatisfied list carried
# `unmeasured(surface-abundance-density.density_floor_verdict=unmeasured)`. The existing anti-blind
# test only asserts the THESIS path returns None; it never asserted the COMPOSED outcome, so the leak
# survived green.
# ---------------------------------------------------------------------------

# A thesis record shaped exactly as `thesis_nomination` emits one when the anti-blind conjunct fails:
# an action-less decline whose `unsatisfied` names the unmeasured deciding-axis field (MUC13's shape).
_BLIND_TR = {
    "thesis": "antigen_driven",
    "deciding": {"short": "surface_modality", "verdict": "adc_preferred_tce_unsafe"},
    "unsatisfied": [
        "requires(selectivity=field_effect_tumor_selective)",
        "unmeasured(surface-abundance-density.density_floor_verdict=unmeasured)",
    ],
}
# A decline for a reason OTHER than blindness — a corroboration axis missed, but the deciding-axis
# card field WAS measured (no `unmeasured(...)` entry). The tier's quantity judgment stands here.
_MEASURED_MISS_TR = {
    "thesis": "antigen_driven",
    "deciding": {"short": "surface_modality", "verdict": "adc_preferred_tce_unsafe"},
    "unsatisfied": ["requires(selectivity=field_effect_tumor_selective)"],
}


def test_positive_tier_may_not_override_the_thesis_anti_blind_refusal():
    """THE leak this change closes (MUC13/COADREAD, live on trunk). The tier reaches its nominating
    bar on evidence quantity, but the thesis decider already REFUSED because the deciding-axis
    ground-truth field is unmeasured. The tier may not override that refusal — the anti-blind bound is
    a cross-path invariant. `winner == "positive_tier"` here because the decider fired no action."""
    value, patch = _rec(
        thesis_action=None, thesis_record=_BLIND_TR, tier="strong", tier_nominates=True, pos_hits=[_HIT]
    )
    assert value is None, "the tier nominated a target the framework is blind on the deciding axis of"
    assert "forced_recommendation" not in patch
    assert "fired" not in patch  # never — see test_reconciler_never_writes_fired
    wh = patch["nominate_withheld"]
    assert wh["reason"] == "blind_deciding_axis"
    assert wh["path"] == "positive_tier"
    assert wh["thesis"] == "antigen_driven"
    assert any("density_floor_verdict=unmeasured" in c for c in wh["anti_blind_conjuncts"])


def test_positive_tier_still_nominates_when_the_thesis_declined_on_a_MEASURED_axis():
    """The over-block guard. A thesis decline whose `unsatisfied` names only a corroboration miss — the
    deciding-axis card field WAS measured (no `unmeasured(...)` marker) — is NOT blindness. The tier's
    independent evidence-quantity judgment is entitled to stand. Without this the fix would convert
    correct tier nominations into abstentions whenever the thesis happened to want a different verdict."""
    value, patch = _rec(
        thesis_action=None, thesis_record=_MEASURED_MISS_TR, tier="strong", tier_nominates=True, pos_hits=[_HIT]
    )
    assert value == "nominate"
    assert patch["forced_by"] == "positive_tier"
    assert "nominate_withheld" not in patch


def test_positive_tier_unaffected_when_there_is_no_thesis_block():
    """EGFR/ERBB2 safety. oncogene_addiction is an unregistered thesis, so `thesis_nomination` returns
    thesis_record=None. These nominate via the tier on MEASURED density and must be structurally clear
    of the anti-blind key — the guard requires a thesis record to inspect."""
    value, patch = _rec(thesis_action=None, thesis_record=None, tier="strong", tier_nominates=True, pos_hits=[_HIT])
    assert value == "nominate"
    assert patch["forced_by"] == "positive_tier"
    assert "nominate_withheld" not in patch


def test_anti_blind_refusal_does_not_touch_a_thesis_decider_win():
    """When the decider itself fires (density WAS measured), it wins the precedence and the anti-blind
    guard is inert — the guard only fires when `positive_tier` is the sole winner. A decider win with a
    corroborating tier is the ordinary agreeing case and must nominate."""
    value, patch = _rec(
        thesis_action="nominate", thesis_record=_TR, tier="strong", tier_nominates=True, pos_hits=[_HIT]
    )
    assert value == "nominate"
    assert patch["forced_by"] == "thesis_decider"
    assert "nominate_withheld" not in patch
