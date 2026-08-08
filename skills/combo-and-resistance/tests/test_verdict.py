"""combo-and-resistance skill — hermetic verdict tests (no S3)."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from run import _verdict  # noqa: E402


def _f(*ids): return [{"rule_id": r, "card_id": "combo-crispr-screen"} for r in ids]


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
