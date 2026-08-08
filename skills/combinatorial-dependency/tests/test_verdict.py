"""combinatorial-dependency skill — hermetic verdict tests (no S3/network).

Pins the self-contained _verdict precedence (constitutive > context > suppressive >
no_interaction > insufficient), the coverage-gap→insufficient mapping, and the
no-rule-fired→insufficient default. Also documents the EGFR/ZAP70 spurious-strong-pair
case as a KNOWN limitation the card's n_lines/p-value carry is designed to catch.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILL_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILL_SCRIPTS))

from run import _verdict  # noqa: E402


def _fired(*rule_ids):
    return [{"rule_id": rid, "card_id": "combinatorial-dependency"} for rid in rule_ids]


def test_constitutive_wins():
    v, drv = _verdict(_fired("combo-constitutive-synthetic-lethal"))
    assert v == "constitutive_combinatorial_dependency"
    assert drv == "combo-constitutive-synthetic-lethal"


def test_context_maps_to_context_verdict():
    v, drv = _verdict(_fired("combo-context-conditional-synthetic-lethal"))
    assert v == "context_combinatorial_dependency"


def test_suppressive():
    v, _ = _verdict(_fired("combo-suppressive-interaction"))
    assert v == "suppressive_combinatorial_interaction"


def test_no_interaction_is_measured_negative():
    v, _ = _verdict(_fired("combo-no-interaction"))
    assert v == "no_combinatorial_dependency"


def test_coverage_gap_is_insufficient_not_negative():
    v, _ = _verdict(_fired("combo-no-paralog-screened"))
    assert v == "combinatorial_dependency_insufficient"


def test_data_unavailable_is_insufficient():
    v, _ = _verdict(_fired("combo-dependency-data-unavailable"))
    assert v == "combinatorial_dependency_insufficient"


def test_no_rule_fired_defaults_insufficient():
    v, drv = _verdict([])
    assert v == "combinatorial_dependency_insufficient"
    assert drv is None


def test_precedence_constitutive_over_context_if_both_present():
    # defensive: if two class rules somehow both fired, strongest wins
    v, drv = _verdict(_fired("combo-context-conditional-synthetic-lethal",
                             "combo-constitutive-synthetic-lethal"))
    assert v == "constitutive_combinatorial_dependency"
    assert drv == "combo-constitutive-synthetic-lethal"
