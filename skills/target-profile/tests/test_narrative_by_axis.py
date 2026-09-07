"""Composed per-axis narrative facet — verdict-inert (Stage C deterministic half).

Hermetic: builds a tiny fixture contracts repo (resolver + nomination_verdict_gate vocab +
interpretation-rules with rationale) in tmp_path and drives run._narrative_by_axis over the
run._fragility_facet output, so the test is independent of live contracts content.

Covers: movers (winning driver), dissenters (opposing-sign fired non-driver, per channel),
flip_conditions carried from the fragility facet's decision_flips (incl. recommendation_flip),
rule_sentences captioned from the rules file, and VERDICT-INERT non-mutation of sub_results.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from _skills_common.rules_loader import rule_text_index
from _test_support import load_run_py

run = load_run_py(Path(__file__).resolve().parents[1], "tp_run_narrative")

_SAFETY_SPEC = {
    "default": "no_safety_concern",
    "resolve": [
        {"when_fired": "safety-killer", "verdict": "highly_constrained_safety_concern"},
        {"when_fired": "safety-ok", "verdict": "no_safety_concern"},
    ],
}
_RULES = {
    "axis": "test_axis",
    "rules_id": "t",
    "rules": [
        {
            "rule_id": "safety-killer",
            "when": {"card_id": "gnomad-lof-constraint", "field": "f", "equals": "x"},
            "signals": {"small_molecule": "opposing", "degrader": "opposing"},
            "rationale": "Highly LoF-constrained in gnomAD.",
        },
        {
            "rule_id": "safety-ok",
            "when": {"card_id": "clingen-dosage", "field": "f", "equals": "y"},
            "signals": {"small_molecule": "supportive", "degrader": "supportive"},
            "rationale": "Recessive-only: het carriers healthy.",
        },
    ],
}


def _fixture_contracts(tmp_path: Path) -> Path:
    (tmp_path / "resolvers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "resolvers" / "safety.resolver.yaml").write_text(yaml.safe_dump(_SAFETY_SPEC))
    vocab = {
        "enum_id": "nomination_verdict_gate",
        "action_precedence": {"veto": 2, "hold": 1},
        "gates": [
            {"sub_skill": "safety", "verdict": "highly_constrained_safety_concern", "action": "hold", "rationale": "t"}
        ],
        "positive_signals": [],
        "positive_contradictions": [],
        "positive_tier_config": {"min_dimensions_for_strong": 2, "require_dominant_for_strong": True},
        "contested_threshold": {"fragility_index_min": 0.5},
    }
    (tmp_path / "vocabularies").mkdir(parents=True, exist_ok=True)
    (tmp_path / "vocabularies" / "nomination_verdict_gate.yaml").write_text(yaml.safe_dump(vocab))
    (tmp_path / "interpretation-rules").mkdir(parents=True, exist_ok=True)
    (tmp_path / "interpretation-rules" / "test-axis.rules.yaml").write_text(yaml.safe_dump(_RULES))
    return tmp_path


def _sub_results():
    return {
        "safety": {
            "skill_dir": "safety",
            "cards": [{"card_id": "gnomad-lof-constraint", "summary": {"constraint_class": "highly_constrained"}}],
            "fired": [
                {
                    "rule_id": "safety-killer",
                    "card_id": "gnomad-lof-constraint",
                    "signals": {"small_molecule": "opposing", "degrader": "opposing"},
                    "rationale": "Highly LoF-constrained in gnomAD.",
                    "killer_message": None,
                },
                {
                    "rule_id": "safety-ok",
                    "card_id": "clingen-dosage",
                    "signals": {"small_molecule": "supportive", "degrader": "supportive"},
                    "rationale": "Recessive-only: het carriers healthy.",
                    "killer_message": None,
                },
            ],
            "verdict": ("highly_constrained_safety_concern", "safety-killer"),
        }
    }


def test_full_narrative_movers_dissenters_flips_sentences(tmp_path):
    c = _fixture_contracts(tmp_path)
    rule_text_index.cache_clear()
    sr = _sub_results()
    frag = run._fragility_facet(sr, contracts_repo=c)
    nba = run._narrative_by_axis(sr, frag, contracts_repo=c)
    n = nba["safety"]
    # movers: the winning driver only (safety-ok is a pure opposer → dissenter, not a mover)
    assert [(m["rule_id"], m["role"]) for m in n["movers"]] == [("safety-killer", "driver")]
    # dissenters: the reassurance rule opposes the concern on BOTH channels
    assert {(d["rule_id"], d["channel"]) for d in n["dissenters"]} == {
        ("safety-ok", "small_molecule"),
        ("safety-ok", "degrader"),
    }
    # flip_conditions carried from the fragility facet: removing the killer drops to no_safety_concern,
    # crossing the hold boundary → recommendation_flip True
    flips = {f["rule_id"]: f for f in n["flip_conditions"]}
    assert flips["safety-killer"]["to_verdict"] == "no_safety_concern"
    assert flips["safety-killer"]["recommendation_flip"] is True
    # rule_sentences captioned from the rules file for every cited rule
    assert n["rule_sentences"]["safety-killer"]["rationale"] == "Highly LoF-constrained in gnomAD."
    assert n["rule_sentences"]["safety-ok"]["rationale"] == "Recessive-only: het carriers healthy."
    rule_text_index.cache_clear()


def test_verdict_inert_does_not_mutate_sub_results(tmp_path):
    c = _fixture_contracts(tmp_path)
    rule_text_index.cache_clear()
    sr = _sub_results()
    before = copy.deepcopy(sr)
    frag = run._fragility_facet(sr, contracts_repo=c)
    run._narrative_by_axis(sr, frag, contracts_repo=c)
    assert sr == before
    rule_text_index.cache_clear()
