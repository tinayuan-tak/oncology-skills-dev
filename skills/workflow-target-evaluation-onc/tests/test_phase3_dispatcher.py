"""Tests for the Phase 3 modality-aware dispatcher.

Pure-function tests. Verify each rule's penalty math, the recommendation
classifier's tier boundaries, and three regression scenarios from real
genes (CRBN degrader, PCDH7 antibody, STK11+ ADC).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from modality_registry import ModalityRegistry  # noqa: E402
from phase3_dispatcher import (  # noqa: E402
    Phase3Result,
    apply_phase3_rule,
    classify_recommendation,
)


@pytest.fixture(scope="module")
def registry() -> ModalityRegistry:
    return ModalityRegistry()


# ---------------------------------------------------------------------------
# Per-rule penalty math (the central matrix from the design table)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rule_name, tox_risk, expected_penalty", [
    # tumor_vs_normal_strict — antibody_naked, rnai
    ("tumor_vs_normal_strict", "Low", 0),
    ("tumor_vs_normal_strict", "Medium", 1),
    ("tumor_vs_normal_strict", "High", 2),

    # tumor_vs_normal_very_strict — adc (one notch worse on Med/High)
    ("tumor_vs_normal_very_strict", "Low", 0),
    ("tumor_vs_normal_very_strict", "Medium", 2),
    ("tumor_vs_normal_very_strict", "High", 3),

    # tumor_vs_normal_relaxed — small_molecule (Med = no penalty)
    ("tumor_vs_normal_relaxed", "Low", 0),
    ("tumor_vs_normal_relaxed", "Medium", 0),
    ("tumor_vs_normal_relaxed", "High", 1),

    # any_normal_expression_blocks — tce (Low still gets penalty 1)
    ("any_normal_expression_blocks", "Low", 1),
    ("any_normal_expression_blocks", "Medium", 3),
    ("any_normal_expression_blocks", "High", 4),
])
def test_rule_tox_penalty(
    registry: ModalityRegistry, rule_name: str, tox_risk: str, expected_penalty: int
) -> None:
    cfg = registry.get_rule_config(rule_name)
    result = apply_phase3_rule(
        rule_name=rule_name,
        rule_config=cfg,
        base_score=4,
        tox_risk=tox_risk,
    )
    assert result.tox_penalty == expected_penalty


# ---------------------------------------------------------------------------
# expression_floor_only is special — penalty depends on expression vs floor
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("expression, floor, expected_penalty", [
    (4.5, 2.0, 0),    # well above floor — no penalty
    (2.5, 2.0, 0),    # above floor
    (2.0, 2.0, 0),    # at floor (>=)
    (1.99, 2.0, 2),   # just below — penalty kicks in
    (0.5, 2.0, 2),    # well below
])
def test_expression_floor_rule(
    registry: ModalityRegistry, expression: float, floor: float, expected_penalty: int
) -> None:
    cfg = registry.get_rule_config("expression_floor_only")
    result = apply_phase3_rule(
        rule_name="expression_floor_only",
        rule_config=cfg,
        base_score=4,
        tox_risk="High",   # irrelevant for this rule — should be ignored
        expression=expression,
        expression_floor=floor,
    )
    assert result.tox_penalty == expected_penalty


def test_expression_floor_rule_ignores_tox_risk(registry: ModalityRegistry) -> None:
    """High tumor-vs-normal tox should NOT penalize a degrader."""
    cfg = registry.get_rule_config("expression_floor_only")
    for tox in ("Low", "Medium", "High"):
        result = apply_phase3_rule(
            rule_name="expression_floor_only",
            rule_config=cfg,
            base_score=4,
            tox_risk=tox,
            expression=4.5,
            expression_floor=2.0,
        )
        assert result.tox_penalty == 0, f"degrader should not penalize {tox} tox"


# ---------------------------------------------------------------------------
# high_tox_blocks_priority by rule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rule_name, tox_risk, expected_blocks", [
    ("tumor_vs_normal_strict", "High", True),
    ("tumor_vs_normal_strict", "Medium", False),
    ("tumor_vs_normal_strict", "Low", False),

    ("tumor_vs_normal_very_strict", "High", True),
    ("tumor_vs_normal_very_strict", "Low", False),

    # SMI relaxed never blocks
    ("tumor_vs_normal_relaxed", "High", False),
    ("tumor_vs_normal_relaxed", "Low", False),

    # Degrader never blocks (tumor-vs-normal not applicable)
    ("expression_floor_only", "High", False),

    # TCE blocks at Medium AND High (stricter than the others)
    ("any_normal_expression_blocks", "High", True),
    ("any_normal_expression_blocks", "Medium", True),
    ("any_normal_expression_blocks", "Low", False),
])
def test_high_tox_blocks_priority_by_rule(
    registry: ModalityRegistry, rule_name: str, tox_risk: str, expected_blocks: bool
) -> None:
    cfg = registry.get_rule_config(rule_name)
    result = apply_phase3_rule(
        rule_name=rule_name,
        rule_config=cfg,
        base_score=4,
        tox_risk=tox_risk,
        expression=4.5,        # degrader-relevant; benign for others
        expression_floor=2.0,
    )
    assert result.high_tox_blocks_priority is expected_blocks


# ---------------------------------------------------------------------------
# Audit-trail metadata: rule_applied + tox_context
# ---------------------------------------------------------------------------

def test_rule_applied_field_matches_rule_name(registry: ModalityRegistry) -> None:
    """rule_applied is what gets logged in the audit trail — must match the
    name passed in, not vary by rule branch."""
    for rule_name in registry.list_rules():
        cfg = registry.get_rule_config(rule_name)
        result = apply_phase3_rule(
            rule_name=rule_name, rule_config=cfg,
            base_score=4, tox_risk="Medium",
            expression=4.0, expression_floor=2.0,
        )
        assert result.rule_applied == rule_name


def test_tox_context_includes_tox_risk_for_tumor_vs_normal_rules(
    registry: ModalityRegistry,
) -> None:
    cfg = registry.get_rule_config("tumor_vs_normal_strict")
    result = apply_phase3_rule(
        rule_name="tumor_vs_normal_strict", rule_config=cfg,
        base_score=4, tox_risk="High",
    )
    assert "High" in result.tox_context


def test_tox_context_for_degrader_mentions_neosubstrate(
    registry: ModalityRegistry,
) -> None:
    """Below floor → cite the floor; above → cite neosubstrate."""
    cfg = registry.get_rule_config("expression_floor_only")
    above = apply_phase3_rule(
        rule_name="expression_floor_only", rule_config=cfg,
        base_score=4, tox_risk="High",
        expression=4.5, expression_floor=2.0,
    )
    assert "neosubstrate" in above.tox_context.lower()

    below = apply_phase3_rule(
        rule_name="expression_floor_only", rule_config=cfg,
        base_score=4, tox_risk="High",
        expression=1.0, expression_floor=2.0,
    )
    assert "expression-floor" in below.tox_context.lower()


# ---------------------------------------------------------------------------
# Tox-risk normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("input_tox, expected_penalty", [
    ("Low", 0),
    ("low", 0),
    ("LOW", 0),
    ("Medium", 1),
    ("medium", 1),
    ("Moderate", 1),
    ("High", 2),
    ("HIGH", 2),
    ("hi", 2),
    # Unknown / empty fall back to Medium (conservative)
    ("Unknown", 1),
    ("", 1),
    ("garbage", 1),
])
def test_tox_risk_normalization(
    registry: ModalityRegistry, input_tox: str, expected_penalty: int
) -> None:
    cfg = registry.get_rule_config("tumor_vs_normal_strict")
    result = apply_phase3_rule(
        rule_name="tumor_vs_normal_strict",
        rule_config=cfg,
        base_score=4,
        tox_risk=input_tox,
    )
    assert result.tox_penalty == expected_penalty


# ---------------------------------------------------------------------------
# Recommendation classifier
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("base, penalty, mut_pen, blocks, expected_rec", [
    # PRIORTY: high adjusted, no blocking, no mut penalty
    (5, 0, 0, False, "PRIORITY"),
    (4, 0, 0, False, "PRIORITY"),
    (5, 1, 0, False, "PRIORITY"),   # adj=4

    # Blocked → CONDITIONAL even if score qualifies
    (5, 0, 0, True, "CONDITIONAL"),
    (4, 0, 0, True, "CONDITIONAL"),

    # Mut penalty 1 → GO not PRIORITY (still passes adj>=4)
    (5, 0, 1, False, "GO"),

    # Mut penalty >=2 → CAUTION regardless of score
    (5, 0, 2, False, "CAUTION"),
    (5, 0, 3, False, "CAUTION"),

    # adj=3 → CONDITIONAL
    (4, 1, 0, False, "CONDITIONAL"),
    (3, 0, 0, False, "CONDITIONAL"),
    (5, 2, 0, False, "CONDITIONAL"),

    # adj<=2 → CAUTION
    (4, 2, 0, False, "CAUTION"),
    (3, 1, 0, False, "CAUTION"),
    (2, 0, 0, False, "CAUTION"),
    (1, 0, 0, False, "CAUTION"),

    # adj is floored at 1
    (4, 5, 0, False, "CAUTION"),
])
def test_classify_recommendation(
    base: int, penalty: int, mut_pen: int, blocks: bool, expected_rec: str
) -> None:
    _, rec = classify_recommendation(base, penalty, mut_pen, blocks)
    assert rec == expected_rec


# ---------------------------------------------------------------------------
# Regression scenarios — three real cases from this project's history
# ---------------------------------------------------------------------------

class TestCRBNDegraderRegression:
    """CRBN motivated the registry. Confirm degrader path produces non-CAUTION
    recommendations for CRBN-like inputs."""

    @pytest.mark.parametrize("whitespace_label, expression", [
        ("Chemorefractory 3L+", 4.43),
        ("RAS Mutant Frontline", 4.40),
        ("Resectable", 4.09),
    ])
    def test_crbn_degrader_priority_in_idas_whitespaces(
        self, registry: ModalityRegistry, whitespace_label: str, expression: float
    ) -> None:
        cfg = registry.get_rule_config("expression_floor_only")
        result = apply_phase3_rule(
            rule_name="expression_floor_only", rule_config=cfg,
            base_score=4,           # expression > 4 log2TPM gives base 4
            tox_risk="High",        # CRBN's actual tumor-vs-normal signal
            expression=expression,
            expression_floor=2.0,
        )
        # Degrader should ignore tumor-vs-normal entirely.
        assert result.tox_penalty == 0, f"{whitespace_label}: degrader should not penalize"

        # Recommendation should be PRIORITY, not CAUTION.
        adj, rec = classify_recommendation(
            base_score=4, tox_penalty=result.tox_penalty,
            mutation_penalty=0,
            high_tox_blocks_priority=result.high_tox_blocks_priority,
        )
        assert rec == "PRIORITY", (
            f"{whitespace_label}: degrader should be PRIORITY, got {rec}"
        )


class TestPCDH7AntibodyRegression:
    """PCDH7 was evaluated as antibody/ADC in the v1.1.0 PCDH7 NSCLC report.
    Confirm naked-antibody path gives PRIORITY in the iDAS whitespaces."""

    def test_pcdh7_antibody_priority_in_2l_non_aga(
        self, registry: ModalityRegistry
    ) -> None:
        """2L Non-AGA: expr 4.43, tox=Low → PRIORITY for naked antibody."""
        cfg = registry.get_rule_config("tumor_vs_normal_strict")
        result = apply_phase3_rule(
            rule_name="tumor_vs_normal_strict", rule_config=cfg,
            base_score=4, tox_risk="Low",
        )
        assert result.tox_penalty == 0
        adj, rec = classify_recommendation(
            base_score=4, tox_penalty=0, mutation_penalty=0,
            high_tox_blocks_priority=result.high_tox_blocks_priority,
        )
        assert rec == "PRIORITY"


class TestSTK11ADCStrictness:
    """STK11+ LUAD shows ~0.6× expression vs WT. As an ADC target with
    HIGH tumor-vs-normal tox (hypothetical), the very-strict rule should
    apply a stricter penalty than the antibody rule."""

    def test_adc_penalty_stricter_than_antibody_for_same_inputs(
        self, registry: ModalityRegistry
    ) -> None:
        ab_cfg = registry.get_rule_config("tumor_vs_normal_strict")
        adc_cfg = registry.get_rule_config("tumor_vs_normal_very_strict")

        ab_result = apply_phase3_rule(
            rule_name="tumor_vs_normal_strict", rule_config=ab_cfg,
            base_score=4, tox_risk="High",
        )
        adc_result = apply_phase3_rule(
            rule_name="tumor_vs_normal_very_strict", rule_config=adc_cfg,
            base_score=4, tox_risk="High",
        )

        assert adc_result.tox_penalty > ab_result.tox_penalty, (
            "ADC must be strictly more penalized than naked antibody at High tox"
        )

    def test_tce_strictest_of_all(self, registry: ModalityRegistry) -> None:
        """At Medium tox, TCE penalty (3) must exceed ADC (2) and antibody (1)."""
        ab_cfg = registry.get_rule_config("tumor_vs_normal_strict")
        adc_cfg = registry.get_rule_config("tumor_vs_normal_very_strict")
        tce_cfg = registry.get_rule_config("any_normal_expression_blocks")

        ab_p = apply_phase3_rule(
            "tumor_vs_normal_strict", ab_cfg, 4, "Medium"
        ).tox_penalty
        adc_p = apply_phase3_rule(
            "tumor_vs_normal_very_strict", adc_cfg, 4, "Medium"
        ).tox_penalty
        tce_p = apply_phase3_rule(
            "any_normal_expression_blocks", tce_cfg, 4, "Medium"
        ).tox_penalty

        assert tce_p > adc_p > ab_p, (
            f"Penalty ordering violated: tce={tce_p}, adc={adc_p}, ab={ab_p}"
        )


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_apply_phase3_rule_unknown_rule_raises(registry: ModalityRegistry) -> None:
    cfg = registry.get_rule_config("tumor_vs_normal_strict")
    with pytest.raises(ValueError, match="Unknown phase3_tox_rule"):
        apply_phase3_rule(
            rule_name="not-a-real-rule", rule_config=cfg,
            base_score=4, tox_risk="Low",
        )
