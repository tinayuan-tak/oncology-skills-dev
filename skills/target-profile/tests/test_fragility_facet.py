"""Fragility facet — verdict-inert flip-stability (2026-08-12).

Hermetic: builds a tiny fixture contracts repo (resolvers + nomination_verdict_gate vocab) in tmp_path
and drives run._fragility_facet against it, so the test is independent of live contracts content.

Covers the load-bearing behaviours:
  - raw vs DECISION flip: a lineage_selective→selective_dependent toggle is a raw flip but NOT a
    decision flip (both are `positive`) — the round-1 KRAS anchor.
  - RECOMMENDATION vs CALL fragility (2026-08-12 refinement): `contested` keys on
    recommendation_fragility_index (flips crossing the KILL boundary — the only ones that can move the
    Go/No-Go), NOT on target_index (any-role call fragility). So an axis that is call-fragile but whose
    flips only touch confidence (KRAS selectivity: positive↔contradiction) is NOT contested.
  - a blind (un-evidenced) decision axis is tracked separately, NOT folded into the indices.
  - VERDICT-INERT: the facet never mutates sub_results and never perturbs _gate_recommendation.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from _test_support import load_run_py

run = load_run_py(Path(__file__).resolve().parents[1], "tp_run_frag")

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
# 2-rule KILL axis: one plausible toggle crosses the kill boundary => recommendation fragility 0.5.
_SAFETY_SPEC = {
    "default": "no_safety_concern",
    "resolve": [
        {"when_fired": "safety-killer", "verdict": "highly_constrained_safety_concern"},
        {"when_fired": "safety-ok", "verdict": "no_safety_concern"},
    ],
}


def _fixture_contracts(tmp_path: Path, with_threshold: bool = True) -> Path:
    (tmp_path / "resolvers").mkdir(parents=True, exist_ok=True)
    (tmp_path / "resolvers" / "dependency.resolver.yaml").write_text(yaml.safe_dump(_DEP_SPEC))
    (tmp_path / "resolvers" / "selectivity.resolver.yaml").write_text(yaml.safe_dump(_SEL_SPEC))
    (tmp_path / "resolvers" / "safety.resolver.yaml").write_text(yaml.safe_dump(_SAFETY_SPEC))
    vocab = {
        "enum_id": "nomination_verdict_gate",
        "action_precedence": {"veto": 2, "hold": 1},
        "gates": [
            {"sub_skill": "dependency", "verdict": "non_dependent", "action": "veto", "rationale": "t"},
            {"sub_skill": "safety", "verdict": "highly_constrained_safety_concern", "action": "hold", "rationale": "t"},
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
        out[short] = {"skill_dir": short, "cards": [], "fired": [{"rule_id": r} for r in rule_ids], "verdict": verdict}
    return out


def test_raw_vs_decision_flip_kras_anchor(tmp_path):
    c = _fixture_contracts(tmp_path)
    sr = _sr(
        dependency=(
            ["lineage-selective-supportive", "strongly-selective-supportive"],
            ("lineage_selective", "lineage-selective-supportive"),
        )
    )
    f = run._fragility_facet(sr, contracts_repo=c)
    ax = f["per_axis"]["dependency"]
    # raw flips: killer-add (→non_dependent) AND lineage-remove (→selective_dependent) = 2/3.
    # decision flips: only the killer-add crosses a ROLE boundary (positive→kill); lineage→selective
    # stays `positive`, so not a decision flip. = 1/3.
    assert ax["raw_flip_fragility"] == round(2 / 3, 4)
    assert ax["decision_flip_fragility"] == round(1 / 3, 4)
    # the killer-add is ALSO a recommendation flip (crosses into a veto); it's the only one.
    assert ax["recommendation_flip_fragility"] == round(1 / 3, 4)
    killer = [df for df in ax["decision_flips"] if df["to_verdict"] == "non_dependent"]
    assert killer and killer[0]["recommendation_flip"] is True and killer[0]["to_role"] == "kill:veto"
    assert {df["to_verdict"] for df in ax["decision_flips"]} == {"non_dependent"}  # KRAS anchor
    assert f["target_index"] == round(1 / 3, 4)
    assert f["recommendation_fragility_index"] == round(1 / 3, 4)
    assert f["contested"] is False  # 0.333 < 0.5


def test_contested_true_on_recommendation_fragile_axis(tmp_path):
    c = _fixture_contracts(tmp_path)
    # safety is a 2-rule KILL axis: removing safety-killer drops to no_safety_concern (kill→neutral),
    # a single kill-boundary-crossing flip = 0.5 → contested.
    sr = _sr(safety=(["safety-killer"], ("highly_constrained_safety_concern", "safety-killer")))
    f = run._fragility_facet(sr, contracts_repo=c)
    assert f["per_axis"]["safety"]["recommendation_flip_fragility"] == 0.5
    assert f["recommendation_fragility_index"] == 0.5
    assert f["contested"] is True


def test_call_fragile_but_recommendation_solid_not_contested(tmp_path):
    """THE refinement: KRAS-like — the selectivity axis is call-fragile (its positive verdict flips to
    a contradiction easily) but that only touches CONFIDENCE, never the Go/No-Go. So target_index is
    high yet contested stays False."""
    c = _fixture_contracts(tmp_path)
    sr = _sr(selectivity=(["sel-strong"], ("strong_tumor_selective", "sel-strong")))
    f = run._fragility_facet(sr, contracts_repo=c)
    ax = f["per_axis"]["selectivity"]
    assert ax["decision_flip_fragility"] == 0.5  # call IS fragile (positive→contradiction)
    assert ax["recommendation_flip_fragility"] == 0.0  # but crosses NO kill boundary
    assert f["target_index"] == 0.5
    assert f["recommendation_fragility_index"] == 0.0
    assert f["contested"] is False  # the whole point of the refinement


def test_selectivity_veto_reflected_in_fragility_base_verdict(tmp_path):
    """O3 (2026-08-15): for a normal-breadth-VETOED selectivity target, the fragility facet's
    base_verdict must reflect the POST-veto verdict the run actually adopted
    (selective_but_broadly_normal), NOT the pre-veto pure-resolver call (strong_tumor_selective).

    The pure resolver has no veto rung (the clamp is post-resolver, in selectivity_veto), so before the
    fix flip_analysis reported the pre-veto verdict. Here we fire sel-strong AND a normal-breadth veto
    rule; the adopted sub-skill verdict is selective_but_broadly_normal, and per_axis base_verdict must
    equal it."""
    c = _fixture_contracts(tmp_path)
    veto_rule = "tvn-no-therapeutic-window-veto"
    sr = _sr(selectivity=(["sel-strong", veto_rule], ("selective_but_broadly_normal", veto_rule)))
    f = run._fragility_facet(sr, contracts_repo=c)
    ax = f["per_axis"]["selectivity"]
    adopted = sr["selectivity"]["verdict"][0]
    assert ax["base_verdict"] == "selective_but_broadly_normal", (
        f"fragility base_verdict={ax['base_verdict']!r} — expected the POST-veto adopted verdict "
        f"(pre-veto leak: reported strong_tumor_selective for a broadly-normal target)."
    )
    assert ax["base_verdict"] == adopted, "facet base_verdict must match the adopted sub-skill verdict"


def test_selectivity_without_veto_unchanged(tmp_path):
    """Guard the no-op contract: a selectivity target with NO veto rule fired is byte-unchanged by the
    O3 clamp (base stays strong_tumor_selective)."""
    c = _fixture_contracts(tmp_path)
    sr = _sr(selectivity=(["sel-strong"], ("strong_tumor_selective", "sel-strong")))
    f = run._fragility_facet(sr, contracts_repo=c)
    assert f["per_axis"]["selectivity"]["base_verdict"] == "strong_tumor_selective"


def test_blind_axis_tracked_separately_not_in_index(tmp_path):
    c = _fixture_contracts(tmp_path)
    sr = _sr(
        dependency=(["non-dependent-killer"], ("non_dependent", "non-dependent-killer")), safety=([], None)
    )  # safety: no verdict, no fired → blind
    f = run._fragility_facet(sr, contracts_repo=c)
    assert "safety" in f["blind_decision_axes"]
    assert f["per_axis"]["safety"]["fragility"] is None
    assert f["per_axis"]["safety"]["reason"] == "blind"
    # dependency base non_dependent(kill); removing the killer → insufficient(neutral) = 1 kill-cross /3.
    assert f["target_index"] == round(1 / 3, 4)
    assert f["recommendation_fragility_index"] == round(1 / 3, 4)


def test_no_contested_flag_without_threshold(tmp_path):
    c = _fixture_contracts(tmp_path, with_threshold=False)
    sr = _sr(safety=(["safety-killer"], ("highly_constrained_safety_concern", "safety-killer")))
    f = run._fragility_facet(sr, contracts_repo=c)
    assert f["recommendation_fragility_index"] == 0.5  # the number is always emitted
    assert f["contested"] is None  # but no flag without a configured threshold
    assert f["_contested_threshold"] is None


def test_verdict_inert(tmp_path):
    """The facet must not mutate sub_results and must not perturb the recommendation gate."""
    c = _fixture_contracts(tmp_path)
    sr = _sr(
        dependency=(["lineage-selective-supportive"], ("lineage_selective", "lineage-selective-supportive")),
        selectivity=(["sel-strong"], ("strong_tumor_selective", "sel-strong")),
    )
    sr_before = copy.deepcopy(sr)
    gate_before = run._gate_recommendation(sr, contracts_repo=c)
    f = run._fragility_facet(sr, contracts_repo=c)
    gate_after = run._gate_recommendation(sr, contracts_repo=c)
    assert sr == sr_before  # no mutation of the input
    assert gate_before == gate_after  # the facet did not perturb the gate
    assert "overall_recommendation" not in f
    assert "value" not in f


def test_short_to_gate_maps_to_real_resolvers():
    """Drift guard: every gate in _SHORT_TO_GATE must resolve to a real resolver with a non-empty
    verdict-movable rule set against the LIVE contracts. Catches the rename class that motivated the
    explicit map (short `tractability_sm` → gate `tractability_small_molecule`). Skips if the live
    contracts checkout is unavailable."""
    import os
    import pytest
    from _skills_common.reachability import resolver_referenced_rule_ids

    contracts = Path(
        os.environ.get(
            "TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
        )
    )
    if not (contracts / "resolvers").is_dir():
        pytest.skip("live target-contracts resolvers/ not available")
    for short, gate in run._SHORT_TO_GATE.items():
        rids = resolver_referenced_rule_ids(gate, contracts_repo=contracts)
        assert rids, f"_SHORT_TO_GATE[{short!r}] -> {gate!r} has no resolver-referenced rules"


def test_acquisition_backlog_lists_blind_axis_with_missing_cards(tmp_path):
    """Ignorance≠negation: a BLIND decision axis becomes an ACQUIRE task naming the missing cards +
    their availability_state (the 'go measure X' backlog the composed layer otherwise drops)."""
    c = _fixture_contracts(tmp_path)
    sr = _sr(dependency=(["strongly-selective-supportive"], ("selective_dependent", "x")))  # evidenced
    sr["safety"] = {
        "skill_dir": "safety",
        "cards": [{"card_id": "gnomad-lof-constraint", "_missing": True, "availability_state": "data_blocked"}],
        "fired": [],
        "verdict": None,
    }  # blind
    f = run._fragility_facet(sr, contracts_repo=c)
    ab = {a["axis"]: a for a in f["acquisition_backlog"]}
    assert "safety" in ab, "blind decision axis must surface as an ACQUIRE task"
    assert ab["safety"]["action"] == "acquire"
    assert ab["safety"]["missing_cards"][0]["card_id"] == "gnomad-lof-constraint"
    assert ab["safety"]["missing_cards"][0]["availability_state"] == "data_blocked"
    assert "dependency" not in ab, "an evidenced axis is not an ignorance/acquire task"


def test_measured_negative_kill_is_not_an_acquire_task(tmp_path):
    """A fired KILL verdict (measured negative) must NOT appear in the acquisition backlog — it is a
    real veto (KILL), not ignorance (ACQUIRE). This is the ignorance-vs-negation action split."""
    c = _fixture_contracts(tmp_path)
    sr = _sr(safety=(["safety-killer"], ("highly_constrained_safety_concern", "safety-killer")))
    f = run._fragility_facet(sr, contracts_repo=c)
    assert "safety" not in {a["axis"] for a in f["acquisition_backlog"]}


# ── M4 insufficient-split: the factored record's finding.availability drives a THIRD action class ──


def test_measured_insufficient_is_a_strengthen_task_not_acquire(tmp_path):
    """The record resolves the state the has_signal/blind logic could not: a MEASURED-but-underpowered
    verdict (finding.availability=='insufficient') HAS signal (so it is not blind/acquire) yet is thin
    → it lands in `underpowered_axes` with action 'strengthen', NOT in acquisition_backlog."""
    c = _fixture_contracts(tmp_path)
    sr = _sr(dependency=(["strongly-selective-supportive"], ("selective_dependent", "x")))  # has signal
    sr["dependency"]["claim_record_shadow"] = {"axis": "dependency", "finding": {"availability": "insufficient"}}
    f = run._fragility_facet(sr, contracts_repo=c)
    up = {a["axis"]: a for a in f["underpowered_axes"]}
    assert "dependency" in up, "a measured-underpowered axis must surface as a STRENGTHEN task"
    assert up["dependency"]["action"] == "strengthen"
    assert up["dependency"]["availability"] == "insufficient"
    assert "dependency" not in {a["axis"] for a in f["acquisition_backlog"]}  # has signal → not acquire


def test_acquire_entry_carries_record_availability(tmp_path):
    """An open-world ACQUIRE entry is tagged with the record's axis-level absence TYPE (authoritative
    over the per-missing-card availability_state)."""
    c = _fixture_contracts(tmp_path)
    sr = _sr(dependency=(["strongly-selective-supportive"], ("selective_dependent", "x")))
    sr["safety"] = {
        "skill_dir": "safety",
        "cards": [{"card_id": "gnomad-lof-constraint", "_missing": True, "availability_state": "data_blocked"}],
        "fired": [],
        "verdict": None,
        "claim_record_shadow": {"axis": "safety", "finding": {"availability": "not_wired"}},
    }
    f = run._fragility_facet(sr, contracts_repo=c)
    ab = {a["axis"]: a for a in f["acquisition_backlog"]}
    assert ab["safety"]["availability"] == "not_wired"


def test_no_underpowered_axes_without_a_record(tmp_path):
    """Backward-compat: with no claim_record_shadow present (pre-M1 sub_results), underpowered_axes is
    empty and acquisition_backlog is unchanged."""
    c = _fixture_contracts(tmp_path)
    sr = _sr(dependency=(["strongly-selective-supportive"], ("selective_dependent", "x")))
    f = run._fragility_facet(sr, contracts_repo=c)
    assert f["underpowered_axes"] == []
