"""Guard C — one classifier for the Go/No-Go recommendation.

The committee-PDF title slide and the integrated-report context builder used to
classify the recommendation string with two independent inline expressions that
DISAGREED on ``CONDITIONAL NO-GO`` (PDF → amber "caution"; context → red no-go).
These tests pin the single shared classifier's semantics AND assert that both
render paths reference that one function, so the classification can never
diverge again.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.recommendation import (  # noqa: E402
    classify_recommendation,
    badge_color_for,
    BADGE_COLOR,
)


@pytest.mark.parametrize("rec,kind", [
    ("NO-GO",                         "no_go"),
    ("CONDITIONAL NO-GO",             "no_go"),   # 'NO-GO' precedence — the bug this guards
    ("no-go — insufficient evidence", "no_go"),
    ("CONDITIONAL",                   "conditional"),
    ("CONDITIONAL GO",                "conditional"),
    ("GO",                            "go"),
    ("GO — HIGH PRIORITY",            "go"),
    ("go",                            "go"),
    ("TBD",                           "unknown"),
    ("",                              "unknown"),
    (None,                            "unknown"),
])
def test_classify_recommendation(rec, kind):
    assert classify_recommendation(rec) == kind


def test_conditional_no_go_is_red_not_amber():
    """The exact regression: 'CONDITIONAL NO-GO' must be a NO-GO (red)."""
    assert classify_recommendation("CONDITIONAL NO-GO") == "no_go"
    assert badge_color_for("CONDITIONAL NO-GO") == "RED"


def test_badge_color_map_covers_all_kinds():
    kinds = {classify_recommendation(s) for s in
             ("NO-GO", "CONDITIONAL", "GO", "TBD")}
    assert kinds <= set(BADGE_COLOR)
    for k in BADGE_COLOR:
        assert BADGE_COLOR[k] in {"RED", "AMBER", "GREEN", "GRAY"}


def test_context_builder_uses_the_shared_classifier():
    """context.py must reference the one shared classifier (no inline re-impl)."""
    from integrated_report import context as ctx_mod
    assert ctx_mod.classify_recommendation is classify_recommendation


def test_pdf_renderer_uses_the_shared_classifier():
    """generate_target_report_pdf must reference the same shared classifier.

    Skipped if matplotlib isn't importable in this environment (the PDF module
    imports it at module load); the context-side guard above still holds.
    """
    try:
        import generate_target_report_pdf as pdf_mod  # noqa: F401
    except Exception as e:  # pragma: no cover - env-dependent import
        pytest.skip(f"generate_target_report_pdf not importable here: {e}")
    assert pdf_mod.classify_recommendation is classify_recommendation
