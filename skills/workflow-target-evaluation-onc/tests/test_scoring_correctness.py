"""Regression tests for batch-2 scoring-correctness fixes.

C1  — context._build_recommendation_context: "CONDITIONAL GO" → badge GREEN (bug)
                                               should be AMBER
RP8 — risk_assessment_renderer._derive_overall_risk: all-LOW-MEDIUM inputs
       aggregated to MEDIUM because 'MEDIUM' in 'LOW-MEDIUM' is True
C2  — scoring_engine.ScoringEngine.score_safety_profile: parse-miss returns
       score=2.0 (same as HIGH-risk tier 4), should return score=1 (lowest YAML tier)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from integrated_report.parsers import RiskAssessment, ScholarEvalResult  # noqa: E402
from integrated_report.context import _build_recommendation_context  # noqa: E402
from integrated_report.risk_assessment_renderer import _derive_overall_risk  # noqa: E402
from scoring_engine import ScoringEngine  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

def _risk(recommendation: str = "") -> RiskAssessment:
    return RiskAssessment(
        gene="G",
        disease="NSCLC",
        overall_risk_profile="MEDIUM",
        categories={},
        recommendation=recommendation,
    )


def _scholar(recommendation: str = "TBD") -> ScholarEvalResult:
    return ScholarEvalResult(
        gene="G",
        disease="NSCLC",
        total_score=3.0,
        assessment="Moderate",
        recommendation=recommendation,
        high_risk_count=0,
        input_hash="",
        dimensions={},
    )


# ---------------------------------------------------------------------------
# C1 — _build_recommendation_context badge for "CONDITIONAL GO"
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase,expected_color", [
    ("GO",                               "GREEN"),
    ("GO — HIGH PRIORITY",               "GREEN"),
    ("NO-GO",                            "RED"),
    ("NO-GO — insufficient evidence",    "RED"),
    ("CONDITIONAL NO-GO",                "RED"),     # ← 'NO-GO' wins over 'CONDITIONAL' (was AMBER in PDF)
    ("conditional no-go",                "RED"),     # case-insensitive
    ("CONDITIONAL",                      "AMBER"),
    ("CONDITIONAL GO",                   "AMBER"),   # ← C1: was GREEN before fix
    ("CONDITIONAL — biomarker required", "AMBER"),
    ("conditional go",                   "AMBER"),   # case-insensitive
    ("TBD",                              "GRAY"),
    ("PENDING",                          "GRAY"),
])
def test_badge_color(phrase, expected_color):
    """Badge color must correctly classify every recommendation variant."""
    result = _build_recommendation_context(_risk(phrase), _scholar())
    assert result["badge_color"] == expected_color, (
        f"phrase={phrase!r}: expected {expected_color}, got {result['badge_color']}"
    )


def test_conditional_go_is_not_flagged_as_plain_go():
    """is_go must be False for 'CONDITIONAL GO' (C1 regression)."""
    result = _build_recommendation_context(_risk("CONDITIONAL GO"), _scholar())
    assert not result["is_go"], "CONDITIONAL GO should not set is_go=True"
    assert result["is_conditional"], "CONDITIONAL GO should set is_conditional=True"


# ---------------------------------------------------------------------------
# RP8 — _derive_overall_risk: LOW-MEDIUM should not aggregate to MEDIUM
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("levels,expected", [
    (["LOW", "LOW", "LOW"],                          "LOW"),
    (["LOW", "LOW", "MEDIUM"],                       "LOW-MEDIUM"),
    (["LOW-MEDIUM", "LOW-MEDIUM", "LOW-MEDIUM"],     "LOW-MEDIUM"),  # ← RP8: was MEDIUM
    (["LOW-MEDIUM", "LOW", "LOW"],                   "LOW-MEDIUM"),  # ← RP8: was MEDIUM
    (["MEDIUM", "MEDIUM"],                           "MEDIUM"),
    (["MEDIUM", "LOW"],                              "LOW-MEDIUM"),
    (["MEDIUM-HIGH", "LOW"],                         "MEDIUM-HIGH"),
    (["HIGH", "LOW"],                                "HIGH"),
    (["HIGH", "MEDIUM-HIGH"],                        "HIGH"),
])
def test_derive_overall_risk(levels, expected):
    """_derive_overall_risk should aggregate correctly for all combinations."""
    cats = {f"cat{i}": {"level": lev} for i, lev in enumerate(levels)}
    assert _derive_overall_risk(cats) == expected, (
        f"levels={levels}: expected {expected}, got {_derive_overall_risk(cats)!r}"
    )


def test_all_low_medium_stays_low_medium():
    """All-LOW-MEDIUM across all 6 categories must not escalate to MEDIUM (RP8)."""
    cats = {k: {"level": "LOW-MEDIUM"} for k in
            ("biological", "druggability", "translational",
             "clinical", "safety", "commercial")}
    assert _derive_overall_risk(cats) == "LOW-MEDIUM"


# ---------------------------------------------------------------------------
# C2 — score_safety_profile fallback: parse-miss must return score=1
# ---------------------------------------------------------------------------

def test_safety_score_parse_miss_returns_lowest_tier():
    """When no threshold condition matches (parse-miss), score must be 1,
    the YAML floor — not 2.0 which collides with the 'LOW enrichment' tier."""
    engine = ScoringEngine()
    engine.rules = {
        "omics_scoring": {
            "safety_profile": {
                "thresholds": [
                    {"condition": "UNPARSEABLE GARBAGE",
                     "risk": "LOW",
                     "score": 5,
                     "description": "never fires"},
                ]
            }
        }
    }
    result = engine.score_safety_profile(
        tumor_vs_adjacent_fc=3.0,
        normal_expr_log2tpm=2.0,
    )
    assert result.score == 1, (
        f"Parse-miss fallback should be score=1 (YAML floor), got {result.score}"
    )
    assert result.risk_level == "HIGH"


def test_safety_score_normal_thresholds_unaffected():
    """Real scoring thresholds still work correctly after the fix."""
    engine = ScoringEngine()
    # fc >= 2.0 AND normal_expr < 4.0 → score=5 LOW
    result = engine.score_safety_profile(3.0, 3.0)
    assert result.score == 5
    assert result.risk_level == "LOW"

    # fc < 1.5 AND normal_expr >= 5.0 → score=2 HIGH (tier 4 fires before score=1)
    result2 = engine.score_safety_profile(0.5, 6.0)
    assert result2.score == 2
    assert result2.risk_level == "HIGH"


# ---------------------------------------------------------------------------
# C7 — tox fold-change display: abs() inflates when log2fc < 0
# ---------------------------------------------------------------------------

from integrated_report.parsers import IDASAssessment  # noqa: E402


def _idas(on_target_tox_log2fc: float, tox_risk: str = "LOW") -> IDASAssessment:
    from integrated_report.parsers import IDASWhitespace
    ws = IDASWhitespace(label="1L", expression_log2tpm=3.0,
                        alignment="Strong", n_samples=50, source="TCGA")
    return IDASAssessment(
        gene="G", overall_alignment="Strong", recommendation="GO",
        on_target_tox_risk=tox_risk, on_target_tox_log2fc=on_target_tox_log2fc,
        luad_log2fc=None, lusc_log2fc=None,
        whitespaces={"1L": ws},
    )


from integrated_report.context import _build_idas_context  # noqa: E402


@pytest.mark.parametrize("log2fc,expected_fc_str,expected_dir", [
    (1.0,  "2.0×",  "↑"),   # tumor higher: FC = 2^1 = 2.0, direction ↑
    (-1.0, "0.5×",  "↓"),   # tumor lower:  FC = 2^-1 = 0.5, direction ↓ (C7: was "2.0× ↓")
    (0.0,  "1.0×",  "="),   # no change
    (2.0,  "4.0×",  "↑"),
    (-2.0, "0.2×",  "↓"),   # C7: abs() would give "4.0× ↓" — wrong
])
def test_tox_summary_fold_change_direction(log2fc, expected_fc_str, expected_dir):
    """tox_summary fold-change must NOT use abs() — tumor-lower should show <1× not >1×."""
    ctx = _build_idas_context(_idas(log2fc))
    tox_summary = ctx["tox_summary"]
    assert expected_fc_str in tox_summary, (
        f"log2fc={log2fc}: expected {expected_fc_str!r} in tox_summary, got {tox_summary!r}"
    )
    assert expected_dir in tox_summary, (
        f"log2fc={log2fc}: expected direction {expected_dir!r} in {tox_summary!r}"
    )


# ---------------------------------------------------------------------------
# C10 — tractability SM: discordant warning swallowed by pocket check
# ---------------------------------------------------------------------------

sys.path.insert(0, str(SKILL_DIR / "scripts"))
# tractability-small-molecule uses a different scripts path
_SM_SCRIPTS = SKILL_DIR.parent / "tractability-small-molecule" / "scripts"
sys.path.insert(0, str(_SM_SCRIPTS))

from run import _snapshot as _sm_snapshot  # noqa: E402  (tractability-small-molecule/run.py)


def _fired(*rule_ids: str) -> list[dict]:
    return [{"rule_id": rid} for rid in rule_ids]


def test_discordant_beats_pocket_when_both_fire():
    """e7-discordant must win over hotspot-in-druggable-pocket (C10 regression)."""
    both = _fired("hotspot-in-druggable-pocket-sm-supportive-e8",
                  "e7-discordant-off-target-warning")
    verdict, driving = _sm_snapshot(both)
    assert verdict == "discordant", (
        f"When both pocket and discordant fire, expected 'discordant', got {verdict!r}"
    )
    assert driving == "e7-discordant-off-target-warning"


def test_pocket_wins_without_discordant():
    """Pocket check still resolves structurally_ligandable when discordant absent."""
    only_pocket = _fired("hotspot-in-druggable-pocket-sm-supportive-e8")
    verdict, _ = _sm_snapshot(only_pocket)
    assert verdict == "structurally_ligandable"


def test_discordant_alone_resolves_correctly():
    """e7-discordant resolves to discordant when no pocket rule fires."""
    only_discordant = _fired("e7-discordant-off-target-warning")
    verdict, driving = _sm_snapshot(only_discordant)
    assert verdict == "discordant"
    assert driving == "e7-discordant-off-target-warning"
