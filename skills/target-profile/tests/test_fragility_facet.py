"""Fragility facet — verdict-inert flip-stability (2026-08-12).

Hermetic: builds a tiny fixture contracts repo (resolvers + nomination_verdict_gate vocab) in tmp_path
and drives run._fragility_facet against it, so the test is independent of live contracts content.

Covers the load-bearing behaviours:
  - raw vs DECISION flip fragility: a lineage_selective→selective_dependent toggle is a raw flip but
    NOT a decision flip (both are `positive`) — the round-1 KRAS anchor.
  - contested flag fires from the declarative threshold on a genuinely fragile axis, and is None when
    no threshold is configured (never-fabricate).
  - a blind (un-evidenced) decision axis is tracked separately, NOT folded into the flip index.
  - VERDICT-INERT: the facet never mutates sub_results and never perturbs _gate_recommendation.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run  # noqa: E402

_DEP_SPEC = {
    "default": "insufficient",
    "resolve": [
        {"when_fired": "non-dependent-killer", "verdict": "non_dependent"},
        {"when_fired": "lineage-selective-supportive", "verdict": "lineage_selective"},
        {"when_fired": "strongly-selective-supportive", "verdict": "selective_dependent"},
    ],
}
_SEL_SPEC = {
    "default": "not_selective",
    "resolve": [
        {"when_fired": "sel-strong", "verdict": "strong_tumor_selective"},
        {"when_fired": "sel-none", "verdict": "not_selective"},
    ],
}


def _fixture_contracts(tmp_path: Path, with_threshold: bool = True) -> Path:
    (tmp_path / "resolvers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "resolvers" / "dependency.resolver.yaml").write_text(yaml.safe_dump(_DEP_SPEC))
    (tmp_path / "resolvers" / "selectivity.resolver.yaml").write_text(yaml.safe_dump(_SEL_SPEC))
    vocab = {
        "enum_id": "nomination_verdict_gate",
        "action_precedence": {"veto": 2, "hold": 1},
        "gates": [
            {"sub_skill": "dependency", "verdict": "non_dependent", "action": "veto", "rationale": "t"},
            {"sub_skill": "safety", "verdict": "highly_constrained_safety_concern",
             "action": "hold", "rationale": "t"},
        ],
        "positive_signals": [
            {"sub_skill": "dependency", "verdict": "lineage_selective", "weight": "supportive"},
            {"sub_skill": "dependency", "verdict": "selective_dependent", "weight": "supportive"},
            {"sub_skill": "selectivity", "verdict": "strong_tumor_selective", "weight": "dominant"},
        ],
        "positive_contradictions": [
            {"sub_skill": "selectivity", "verdict": "not_selective"},
        ],
        "positive_tier_config": {"min_dimensions_for_strong": 2, "require_dominant_for_strong": True},
    }
    if with_threshold:
        vocab["contested_threshold"] = {"fragility_index_min": 0.5}
    (tmp_path / "vocabularies").mkdir(parents=True, exist_ok=True)
    (tmp_path / "vocabularies" / "nomination_verdict_gate.yaml").write_text(yaml.safe_dump(vocab))
    return tmp_path


def _sr(**by_short) -> dict:
    """sub_results from {short: (fired_rule_ids, verdict_tuple_or_None)}."""
    out = {}
    for short, (rule_ids, verdict) in by_short.items():
        out[short] = {"skill_dir": short, "cards": [],
                      "fired": [{"rule_id": r} for r in rule_ids], "verdict": verdict}
    return out


def test_raw_vs_decision_flip_kras_anchor(tmp_path):
    c = _fixture_contracts(tmp_path)
    sr = _sr(dependency=(["lineage-selective-supportive", "strongly-selective-supportive"],
                         ("lineage_selective", "lineage-selective-supportive")))
    f = run._fragility_facet(sr, contracts_repo=c)
    ax = f["per_axis"]["dependency"]
    # raw flips: killer-add (→non_dependent) AND lineage-remove (→selective_dependent) = 2/3.
    # decision flips: ONLY the killer-add crosses a role boundary (positive→kill); the
    # lineage→selective toggle stays `positive`, so it is NOT a decision flip. = 1/3.
    assert ax["raw_flip_fragility"] == round(2 / 3, 4)
    assert ax["decision_flip_fragility"] == round(1 / 3, 4)
    assert ax["decision_flip_fragility"] < ax["raw_flip_fragility"]
    flipped_to = {df["to_verdict"] for df in ax["decision_flips"]}
    assert flipped_to == {"non_dependent"}           # only the role-crossing flip
    assert "selective_dependent" not in flipped_to   # the KRAS anchor: raw-but-not-decision
    assert f["target_index"] == round(1 / 3, 4)
    assert f["contested"] is False                   # 0.333 < 0.5


def test_contested_true_on_fragile_axis(tmp_path):
    c = _fixture_contracts(tmp_path)
    # selectivity is a 2-rule axis: removing sel-strong drops to not_selective (positive→contradiction),
    # a single decision flip = 0.5 → meets the 0.5 threshold.
    sr = _sr(selectivity=(["sel-strong"], ("strong_tumor_selective", "sel-strong")))
    f = run._fragility_facet(sr, contracts_repo=c)
    assert f["per_axis"]["selectivity"]["decision_flip_fragility"] == 0.5
    assert f["target_index"] == 0.5
    assert f["contested"] is True


def test_blind_axis_tracked_separately_not_in_index(tmp_path):
    c = _fixture_contracts(tmp_path)
    sr = _sr(dependency=(["non-dependent-killer"], ("non_dependent", "non-dependent-killer")),
             safety=([], None))   # safety: no verdict, no fired → blind
    f = run._fragility_facet(sr, contracts_repo=c)
    assert "safety" in f["blind_decision_axes"]
    assert f["per_axis"]["safety"]["fragility"] is None
    assert f["per_axis"]["safety"]["reason"] == "blind"
    # target_index reflects only the measured dependency axis (1/3), NOT a blind 1.0 inflation.
    assert f["target_index"] == round(1 / 3, 4)


def test_no_contested_flag_without_threshold(tmp_path):
    c = _fixture_contracts(tmp_path, with_threshold=False)
    sr = _sr(selectivity=(["sel-strong"], ("strong_tumor_selective", "sel-strong")))
    f = run._fragility_facet(sr, contracts_repo=c)
    assert f["target_index"] == 0.5          # the number is always emitted
    assert f["contested"] is None            # but no flag without a configured threshold
    assert f["_contested_threshold"] is None


def test_verdict_inert(tmp_path):
    """The facet must not mutate sub_results and must not perturb the recommendation gate."""
    c = _fixture_contracts(tmp_path)
    sr = _sr(dependency=(["lineage-selective-supportive"], ("lineage_selective", "lineage-selective-supportive")),
             selectivity=(["sel-strong"], ("strong_tumor_selective", "sel-strong")))
    sr_before = copy.deepcopy(sr)
    gate_before = run._gate_recommendation(sr, contracts_repo=c)
    f = run._fragility_facet(sr, contracts_repo=c)
    gate_after = run._gate_recommendation(sr, contracts_repo=c)
    assert sr == sr_before                    # no mutation of the input
    assert gate_before == gate_after          # the facet did not perturb the gate
    # the facet is a facet, not a recommendation: it carries no overall_recommendation / value.
    assert "overall_recommendation" not in f
    assert "value" not in f


def test_short_to_gate_maps_to_real_resolvers():
    """Drift guard: every gate in _SHORT_TO_GATE must resolve to a real resolver with a non-empty
    verdict-movable rule set against the LIVE contracts. Catches the rename class that motivated the
    explicit map (short `tractability_sm` → gate `tractability_small_molecule`). Skips if the live
    contracts checkout is unavailable (hermetic unit tests above still run)."""
    import os
    import pytest
    from _skills_common.reachability import resolver_referenced_rule_ids

    contracts = Path(os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
    if not (contracts / "resolvers").is_dir():
        pytest.skip("live target-contracts resolvers/ not available")
    for short, gate in run._SHORT_TO_GATE.items():
        rids = resolver_referenced_rule_ids(gate, contracts_repo=contracts)
        assert rids, f"_SHORT_TO_GATE[{short!r}] -> {gate!r} has no resolver-referenced rules " \
                     f"(renamed/missing resolver?)"
