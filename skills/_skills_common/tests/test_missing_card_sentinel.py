"""Regression tests for RP4 — dual missing-card sentinel canonicalization.

The root cause: _skills_common/__init__.py was translating `_missing` → `missing`
(no underscore) when assembling the output cards list. Downstream code in
dispatcher.py then defensively accepted both spellings via `or c.get("missing")`.

Fix: __init__.py emits `_missing` everywhere; dispatcher.py checks only `_missing`.
These tests verify both that the output dict carries `_missing` and that the
old bare `missing` arm is gone from dispatcher.
"""

from __future__ import annotations

import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common.dispatcher import _apply_on_dependency_status

# ---------------------------------------------------------------------------
# Test 1 — resolve_cards output carries _missing (not bare missing)
# ---------------------------------------------------------------------------


def _make_card(card_id: str, missing: bool) -> dict:
    """Build a card_output dict as resolve_cards produces internally."""
    return {
        "card_id": card_id,
        "summary": {} if missing else {"value": 42},
        "_missing": missing,
        "_missing_reason": "dispatcher_returned_none" if missing else None,
    }


def test_make_decision_json_emits_underscore_missing_key():
    """make_decision_json must emit `_missing` in the cards list, not bare `missing`.

    RP4 regression: the old code translated _missing → missing (bare) when
    assembling the output cards list in make_decision_json. The fix keeps `_missing`.
    """
    from _skills_common import make_decision_json

    card_outputs = [_make_card("card-x", missing=True)]

    result = make_decision_json(
        skill_name="test-skill",
        target="GENE",
        indication="NSCLC",
        question="Is GENE tractable?",
        card_outputs=card_outputs,
        fired=[],
        headline={"verdict": "insufficient"},
    )

    assert len(result["cards"]) == 1
    card = result["cards"][0]

    assert "_missing" in card, "RP4 regression: `_missing` key absent — make_decision_json emitted bare `missing`"
    assert card["_missing"] is True, f"Expected _missing=True, got {card['_missing']}"
    assert "missing" not in card, "Bare `missing` key (no underscore) must not appear — `_missing` is canonical"


def test_make_decision_json_present_card_has_missing_false():
    """A present card in the output dict must carry `_missing: False`."""
    from _skills_common import make_decision_json

    card_outputs = [_make_card("card-y", missing=False)]

    result = make_decision_json(
        skill_name="test-skill",
        target="GENE",
        indication="NSCLC",
        question="Is GENE tractable?",
        card_outputs=card_outputs,
        fired=[],
        headline={"verdict": "supportive"},
    )

    card = result["cards"][0]
    assert "_missing" in card
    assert card["_missing"] is False
    assert "missing" not in card


# ---------------------------------------------------------------------------
# Test 2 — dispatcher.py no longer accepts bare `missing` as sentinel
# ---------------------------------------------------------------------------


def test_apply_on_dependency_status_ignores_bare_missing():
    """_apply_on_dependency_status checks only `_missing`; bare `missing` is NOT a sentinel.

    A card with `missing: True` but no `_missing` key must be treated as *present*
    (the dual-key shim is gone). This test confirms the old shim is removed.
    """
    cards = [
        {"card_id": "card-present", "summary": {"v": 1}, "_missing": False},
        {"card_id": "card-old-style", "summary": {}, "missing": True},  # old format
    ]
    on_dep = {"card-old-style": "skip_section"}

    surviving, skipped, caveats = _apply_on_dependency_status(cards, on_dep)

    surviving_ids = {c["card_id"] for c in surviving}
    # card-old-style has only bare `missing`, not `_missing` — so it's NOT missing
    # under the new rule, and skip_section does not fire.
    assert "card-old-style" in surviving_ids, (
        "card-old-style should be treated as present (bare `missing` is not a sentinel)"
    )
    assert skipped == [], f"Nothing should be skipped; got {skipped}"


def test_apply_on_dependency_status_skips_underscore_missing():
    """_apply_on_dependency_status correctly skips a card with `_missing: True`."""
    cards = [
        {"card_id": "card-a", "summary": {"v": 1}, "_missing": False},
        {"card_id": "card-b", "summary": {}, "_missing": True},
    ]
    on_dep = {"card-b": "skip_section"}

    surviving, skipped, caveats = _apply_on_dependency_status(cards, on_dep)

    surviving_ids = {c["card_id"] for c in surviving}
    assert "card-a" in surviving_ids
    assert "card-b" not in surviving_ids
    assert skipped == ["card-b"]


# ---------------------------------------------------------------------------
# M2 (2026-08-11 code review) — honest data_unavailable is detected on ANY *_class
# field, still counts against coverage (_missing), but IS available for rule-matching
# so its dedicated `equals: data_unavailable` resolver rung fires.
# ---------------------------------------------------------------------------


def test_data_unavailable_detected_on_topic_specific_class_field():
    """_summary_is_unavailable must recognize data_unavailable in a topic-specific *_class
    field (dependency_class, cn_stratification_class, fit_class, …), not only the 3 legacy
    primaries (selectivity_class/class/interpretation_call)."""
    from _skills_common import _data_unavailable_field, _summary_is_unavailable

    for field in ("dependency_class", "cn_stratification_class", "fit_class", "concordance_class"):
        summary = {field: "data_unavailable"}
        assert _data_unavailable_field(summary) == field
        assert _summary_is_unavailable(summary) == f"{field}=data_unavailable"
    # a real answer in a *_class field is NOT flagged
    assert _data_unavailable_field({"dependency_class": "strongly_dependent"}) is None


def test_honest_data_unavailable_is_available_for_rule_matching_but_counts_against_coverage():
    """The M2 core: an honest data_unavailable card is tagged _missing (coverage) AND
    _data_unavailable (so fired_rules includes it), while a genuine absence (dispatcher None)
    is _missing WITHOUT _data_unavailable (excluded from rule-matching)."""
    from _skills_common import fired_rules

    honest_du = {
        "card_id": "pan-cancer-crispr-dependency-distribution",
        "summary": {"dependency_class": "data_unavailable"},
        "interpretation_call": "data_unavailable",
        "_missing": True,
        "_data_unavailable": True,
    }
    genuine_absence = {
        "card_id": "pan-cancer-rnai-dependency-distribution",
        "summary": {},
        "interpretation_call": "not_implemented",
        "_missing": True,  # no _data_unavailable
    }
    rules = [
        {
            "rule_id": "crispr-data-unavailable-insufficient",
            "when": {
                "card_id": "pan-cancer-crispr-dependency-distribution",
                "field": "dependency_class",
                "equals": "data_unavailable",
            },
            "signals": {},
        },
        {
            "rule_id": "rnai-data-unavailable-insufficient",
            "when": {
                "card_id": "pan-cancer-rnai-dependency-distribution",
                "field": "rnai_dependency_class",
                "equals": "data_unavailable",
            },
            "signals": {},
        },
    ]
    fired = fired_rules(
        [honest_du, genuine_absence],
        axis="intracellular_intrinsic",
        rules=rules,
        card_id_filter=["pan-cancer-crispr-dependency-distribution", "pan-cancer-rnai-dependency-distribution"],
    )
    fired_ids = {f["rule_id"] for f in fired}
    # honest data_unavailable → its rung fires (was silently excluded before M2)
    assert "crispr-data-unavailable-insufficient" in fired_ids
    # genuine absence (no _data_unavailable) → still excluded from rule-matching
    assert "rnai-data-unavailable-insufficient" not in fired_ids


# ---------------------------------------------------------------------------
# R1 (2026-09-06) — a LIVE_READ_ERROR stub whose summary still reports a
# data_unavailable class must ALSO fire its `equals: data_unavailable` rung (so a
# read-errored backbone anchors the provenance rung instead of falling through to a
# null driving_rule), WITHOUT being flagged _data_unavailable (which would mislabel
# its dispatcher availability_state as `insufficient` instead of `read_error`).
# ---------------------------------------------------------------------------


def test_live_read_error_with_class_fires_data_unavailable_rung_but_stays_read_error():
    from _skills_common import fired_rules
    from _skills_common.dispatcher import _availability_state_for

    # the resolve_cards shape for a live-read-errored backbone card that still stamped its class
    read_error = {
        "card_id": "pan-cancer-crispr-dependency-distribution",
        "summary": {"dependency_class": "data_unavailable", "_live_read_error": "S3 timeout"},
        "interpretation_call": "data_unavailable",
        "_missing": True,
        "_missing_reason": "live_read_error: S3 timeout",
        "_data_unavailable": False,  # NOT honest-DU → availability_state must stay read_error
    }
    empty_absence = {
        "card_id": "pan-cancer-rnai-dependency-distribution",
        "summary": {},
        "interpretation_call": "not_implemented",
        "_missing": True,
    }
    rules = [
        {
            "rule_id": "crispr-data-unavailable-insufficient",
            "when": {
                "card_id": "pan-cancer-crispr-dependency-distribution",
                "field": "dependency_class",
                "equals": "data_unavailable",
            },
            "signals": {},
        },
        {
            "rule_id": "rnai-data-unavailable-insufficient",
            "when": {
                "card_id": "pan-cancer-rnai-dependency-distribution",
                "field": "rnai_dependency_class",
                "equals": "data_unavailable",
            },
            "signals": {},
        },
    ]
    fired_ids = {
        f["rule_id"]
        for f in fired_rules(
            [read_error, empty_absence],
            axis="intracellular_intrinsic",
            rules=rules,
            card_id_filter=["pan-cancer-crispr-dependency-distribution", "pan-cancer-rnai-dependency-distribution"],
        )
    }
    # R1 fix: the read-errored card with a class fires its data_unavailable rung (provenance anchor)
    assert "crispr-data-unavailable-insufficient" in fired_ids
    # a truly EMPTY absence (no class) still fires nothing
    assert "rnai-data-unavailable-insufficient" not in fired_ids
    # availability_state distinction is preserved: read_error, NOT insufficient
    assert _availability_state_for(read_error)[0] == "read_error"


def test_data_absence_live_read_error_is_insufficient_not_read_error():
    """A live_read_error naming a DATA-ABSENCE (reader looked; target genuinely not in the dataset) is a
    MEASURED gap → `insufficient`, not `read_error` (could not look). Companion boundary to the test above:
    a genuine failure (S3 timeout / deadlock) and a wiring error must STILL be read_error — the reason
    string decides, and the data-absence markers are specific enough not to catch them."""
    from _skills_common.dispatcher import _availability_state_for

    def av(reason):
        return _availability_state_for(
            {"card_id": "c", "_missing": True, "_missing_reason": reason, "_data_unavailable": False}
        )[0]

    # data-absence → insufficient (looked, genuinely absent)
    assert av("live_read_error: target_not_in_derived_product") == "insufficient"
    assert av("live_read_error: gene_not_in_ccle_rrbs") == "insufficient"
    assert av("live_read_error: target_absent_from_gygi_ms") == "insufficient"
    # genuine failures → read_error (could not look) — the distinction the fix must preserve
    assert av("live_read_error: S3 timeout") == "read_error"
    assert av("live_read_error: deadlock detected by _ModuleLock('methods.x.read')") == "read_error"
    # a wiring error carries 'not_found' but NOT a data-absence marker → stays read_error
    assert av("live_read_error: resolver_not_found") == "read_error"
