"""combo-and-resistance skill — hermetic verdict tests (no S3)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from run import _verdict, _resistance_verdict, _headline  # noqa: E402


def _f(*ids): return [{"rule_id": r, "card_id": "combo-crispr-screen"} for r in ids]


def _rf(*ids): return [{"rule_id": r, "card_id": "resistance-emergence-signature"} for r in ids]


def test_strong_wins():
    assert _verdict(_f("combo-strong-opportunity"))[0] == "strong_combination_opportunity"

def test_supported():
    assert _verdict(_f("combo-supported-opportunity"))[0] == "combination_opportunity"

def test_context():
    assert _verdict(_f("combo-context-opportunity"))[0] == "context_combination_opportunity"

def test_no_signal_is_measured_negative():
    assert _verdict(_f("combo-no-signal"))[0] == "no_combination_signal"

def test_no_anchor_is_insufficient_not_negative():
    assert _verdict(_f("combo-no-anchor-screen"))[0] == "combination_insufficient"

def test_no_rule_defaults_insufficient():
    v, d = _verdict([]); assert v == "combination_insufficient" and d is None

def test_precedence_strong_over_context():
    v, d = _verdict(_f("combo-context-opportunity", "combo-strong-opportunity"))
    assert v == "strong_combination_opportunity" and d == "combo-strong-opportunity"


# ── resistance half (secondary verdict) ──

def test_resistance_strong_wins():
    assert _resistance_verdict(_rf("resistance-strong-signal"))[0] == "strong_resistance_signal"

def test_resistance_supported():
    assert _resistance_verdict(_rf("resistance-supported-signal"))[0] == "resistance_signal"

def test_resistance_context():
    assert _resistance_verdict(_rf("resistance-context-signal"))[0] == "context_resistance_signal"

def test_resistance_no_signal_is_measured_negative():
    assert _resistance_verdict(_rf("resistance-no-signal"))[0] == "no_resistance_signal"

def test_resistance_no_anchor_is_insufficient_not_negative():
    assert _resistance_verdict(_rf("resistance-no-anchor-screen"))[0] == "resistance_insufficient"

def test_resistance_no_rule_defaults_insufficient():
    v, d = _resistance_verdict([]); assert v == "resistance_insufficient" and d is None

def test_resistance_precedence_strong_over_context():
    v, d = _resistance_verdict(_rf("resistance-context-signal", "resistance-strong-signal"))
    assert v == "strong_resistance_signal" and d == "resistance-strong-signal"


def test_headline_derives_resistance_verdict_from_passed_merged_fired():
    # Sweep-2 S2: the dispatcher now fires resistance as an extra AUDIT axis and passes the MERGED
    # fired to _headline; _headline must derive the resistance verdict from THAT (not re-fire), so
    # the verdict is traceable to an emitted fired rule.
    cards = [{"card_id": "combo-crispr-screen", "summary": {}},
             {"card_id": "resistance-emergence-signature",
              "summary": {"resistance_emergence_class": "strong_resistance_signal"}}]
    fired = [{"rule_id": "combination-strong", "card_id": "combo-crispr-screen"},
             {"rule_id": "resistance-strong-signal", "card_id": "resistance-emergence-signature"}]
    h = _headline(cards, fired, ("combination_supported", "combination-strong"))
    assert h["resistance_verdict"] == "strong_resistance_signal"
    assert h["resistance_driving_rule_id"] == "resistance-strong-signal"
