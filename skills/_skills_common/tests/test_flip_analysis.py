"""Unit tests for the counterfactual flip primitive (flip_analysis.py).

Hermetic: builds a tiny resolver spec on disk (tmp_path) and drives flip_analysis against it, so the
test does not depend on the live target-contracts resolver content (which shifts). Covers: a
single-rule toggle that flips the verdict, a genuinely robust verdict (redundant when_any_fired),
the no-resolver → None contract, determinism, and non-mutation of the input `fired` list.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from _skills_common.flip_analysis import flip_analysis  # noqa: E402


def _write_resolver(root: Path, gate: str, spec: dict) -> None:
    (root / "resolvers").mkdir(parents=True, exist_ok=True)
    (root / "resolvers" / f"{gate}.resolver.yaml").write_text(yaml.safe_dump(spec))


_KILLER_SPEC = {
    "default": "insufficient",
    "resolve": [
        {"when_fired": "killer-rule", "verdict": "the_killer"},
        {"when_any_fired": ["pos-a", "pos-b"], "verdict": "the_positive"},
    ],
}


def test_single_rule_toggle_flips(tmp_path):
    _write_resolver(tmp_path, "g", _KILLER_SPEC)
    fired = [{"rule_id": "killer-rule"}]
    fa = flip_analysis(fired, "g", contracts_repo=tmp_path)
    assert fa["base_verdict"] == "the_killer"
    assert fa["n_relevant"] == 3  # killer-rule, pos-a, pos-b
    assert not fa["robust"]
    # removing killer-rule falls through to the default → a flip; adding pos-a/pos-b does NOT (killer
    # rung is first and still fires), so exactly one flip.
    flipped = {f["rule_id"] for f in fa["flips"]}
    assert flipped == {"killer-rule"}
    assert fa["flip_fragility"] == 1 / 3


def test_robust_verdict_has_zero_flips(tmp_path):
    # when_any_fired:[a,b] with BOTH fired — removing either leaves the other firing the same verdict,
    # and there are no absent relevant rules to add. Genuinely robust.
    _write_resolver(tmp_path, "g", {"default": "D", "resolve": [{"when_any_fired": ["a", "b"], "verdict": "P"}]})
    fa = flip_analysis([{"rule_id": "a"}, {"rule_id": "b"}], "g", contracts_repo=tmp_path)
    assert fa["base_verdict"] == "P"
    assert fa["robust"] is True
    assert fa["n_flips"] == 0
    assert fa["flip_fragility"] == 0.0


def test_none_when_resolver_absent(tmp_path):
    # No resolvers/<gate>.resolver.yaml → None (caller treats as flip-inapplicable, NOT robust).
    assert flip_analysis([{"rule_id": "x"}], "no_such_gate", contracts_repo=tmp_path) is None


_SEL_SPEC = {
    "default": "not_selective",
    "resolve": [
        {"when_fired": "sel-strong", "verdict": "strong_tumor_selective"},
    ],
}


def test_selectivity_gate_applies_normal_breadth_veto(tmp_path):
    """O3: for the SELECTIVITY gate, flip_analysis applies the shared normal-breadth veto clamp, so the
    base_verdict reflects the POST-veto call the run adopts. Firing sel-strong (→ strong_tumor_selective
    pure) alongside a veto rule must yield base_verdict=selective_but_broadly_normal."""
    _write_resolver(tmp_path, "selectivity", _SEL_SPEC)
    fired = [{"rule_id": "sel-strong"}, {"rule_id": "tvn-no-therapeutic-window-veto"}]
    fa = flip_analysis(fired, "selectivity", contracts_repo=tmp_path)
    assert fa["base_verdict"] == "selective_but_broadly_normal"


def test_non_selectivity_gate_ignores_veto_rule(tmp_path):
    """The clamp is SELECTIVITY-gate-scoped: a veto rule id in fired must NOT alter any other gate's
    base_verdict (the veto rule is not even a resolver rung there)."""
    _write_resolver(tmp_path, "g", _KILLER_SPEC)
    fired = [{"rule_id": "killer-rule"}, {"rule_id": "tvn-no-therapeutic-window-veto"}]
    fa = flip_analysis(fired, "g", contracts_repo=tmp_path)
    assert fa["base_verdict"] == "the_killer"  # unchanged by the (selectivity-only) clamp


def test_deterministic(tmp_path):
    _write_resolver(tmp_path, "g", _KILLER_SPEC)
    fired = [{"rule_id": "killer-rule"}]
    a = flip_analysis(fired, "g", contracts_repo=tmp_path)
    b = flip_analysis(fired, "g", contracts_repo=tmp_path)
    assert a == b


def test_does_not_mutate_input_fired(tmp_path):
    _write_resolver(tmp_path, "g", _KILLER_SPEC)
    fired = [{"rule_id": "killer-rule"}]
    before = [dict(f) for f in fired]
    flip_analysis(fired, "g", contracts_repo=tmp_path)
    assert fired == before  # the scan toggles copies, never the caller's list
