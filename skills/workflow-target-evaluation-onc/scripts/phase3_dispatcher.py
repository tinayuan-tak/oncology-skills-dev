"""Phase 3 modality-aware tox dispatcher.

Pure functions. Given a rule name + inputs, returns the (penalty, blocking,
context) needed to compute Phase 3 adjusted_score and recommendation.

Modality-class → rule mapping comes from ModalityRegistry; this module
just applies the named rule. Adding a new rule requires:
  1. Add the rule's tox_penalty_by_risk table to modality_classes.yaml
  2. Add a `_apply_<rule_name>` function below
  3. Wire it into RULE_FUNCTIONS at the bottom

Recommendation classification (`classify_recommendation`) is shared across
rules — only the penalty math differs by modality.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Phase3Result:
    """What the dispatcher returns for a single Phase 3 evaluation."""
    tox_penalty: int
    high_tox_blocks_priority: bool
    tox_context: str          # human-readable, goes into audit trail rationale
    rule_applied: str         # rule name, for audit trail


def apply_phase3_rule(
    rule_name: str,
    rule_config: dict,
    base_score: int,
    tox_risk: str,            # 'Low' | 'Medium' | 'High' | 'Unknown'
    expression: float = 0.0,  # log2TPM, used by expression_floor_only
    expression_floor: float = 0.0,
    mutation_penalty: int = 0,
) -> Phase3Result:
    """Dispatch to the named rule and return penalty + blocking + context.

    `rule_config` is the dict from ModalityRegistry.get_rule_config(rule_name).
    Pulled in by callers so the dispatcher itself stays registry-free
    (easier to test in isolation).
    """
    if rule_name not in RULE_FUNCTIONS:
        raise ValueError(f"Unknown phase3_tox_rule: {rule_name!r}")

    fn = RULE_FUNCTIONS[rule_name]
    return fn(
        rule_config=rule_config,
        base_score=base_score,
        tox_risk=_normalize_tox_risk(tox_risk),
        expression=expression,
        expression_floor=expression_floor,
        mutation_penalty=mutation_penalty,
    )


def _normalize_tox_risk(tox_risk: str) -> str:
    """Map various spellings to canonical 'Low'/'Medium'/'High'.

    Conservative on Unknown: treats as Medium for penalty lookup so unknown
    doesn't silently become Low (which would understate risk).
    """
    if not tox_risk:
        return "Medium"
    t = tox_risk.strip().lower()
    if t in ("low", "lo"):
        return "Low"
    if t in ("medium", "med", "moderate"):
        return "Medium"
    if t in ("high", "hi"):
        return "High"
    return "Medium"


# ---------------------------------------------------------------------------
# Per-rule implementations
# ---------------------------------------------------------------------------
# Each function takes the same kwargs (rule_config, base_score, tox_risk,
# expression, expression_floor, mutation_penalty) and returns a Phase3Result.
# Unused kwargs are absorbed via **_ to keep call sites uniform.

def _apply_tumor_vs_normal_strict(
    rule_config: dict, tox_risk: str, **_
) -> Phase3Result:
    penalty = rule_config["tox_penalty_by_risk"][tox_risk]
    return Phase3Result(
        tox_penalty=penalty,
        high_tox_blocks_priority=(tox_risk == "High"),
        tox_context=f"{tox_risk} toxicity",
        rule_applied="tumor_vs_normal_strict",
    )


def _apply_tumor_vs_normal_very_strict(
    rule_config: dict, tox_risk: str, **_
) -> Phase3Result:
    penalty = rule_config["tox_penalty_by_risk"][tox_risk]
    return Phase3Result(
        tox_penalty=penalty,
        high_tox_blocks_priority=(tox_risk == "High"),
        tox_context=f"{tox_risk} toxicity (ADC strict — bystander payload)",
        rule_applied="tumor_vs_normal_very_strict",
    )


def _apply_tumor_vs_normal_relaxed(
    rule_config: dict, tox_risk: str, **_
) -> Phase3Result:
    penalty = rule_config["tox_penalty_by_risk"][tox_risk]
    return Phase3Result(
        tox_penalty=penalty,
        high_tox_blocks_priority=False,   # SMI: pathway context > expression-window
        tox_context=f"{tox_risk} toxicity (SMI relaxed — pathway-driven)",
        rule_applied="tumor_vs_normal_relaxed",
    )


def _apply_expression_floor_only(
    rule_config: dict, expression: float, expression_floor: float, **_
) -> Phase3Result:
    """Degrader rule: tumor-vs-normal disabled, expression floor instead."""
    if expression < expression_floor:
        penalty = 2  # below floor — recruited E3/target not present enough
        ctx = (
            f"expression-floor:LOW (expr={expression:.2f} < floor={expression_floor:.2f})"
        )
    else:
        penalty = 0
        ctx = "neosubstrate-driven window (tumor-vs-normal not applicable)"
    return Phase3Result(
        tox_penalty=penalty,
        high_tox_blocks_priority=False,   # tumor-vs-normal not applicable
        tox_context=ctx,
        rule_applied="expression_floor_only",
    )


def _apply_any_normal_expression_blocks(
    rule_config: dict, tox_risk: str, **_
) -> Phase3Result:
    """TCE rule: any normal expression triggers cytotoxicity → strictest."""
    penalty = rule_config["tox_penalty_by_risk"][tox_risk]
    blocks = tox_risk in ("Medium", "High")
    return Phase3Result(
        tox_penalty=penalty,
        high_tox_blocks_priority=blocks,
        tox_context=f"{tox_risk} toxicity (TCE strict — any normal expression matters)",
        rule_applied="any_normal_expression_blocks",
    )


RULE_FUNCTIONS: dict[str, Callable[..., Phase3Result]] = {
    "tumor_vs_normal_strict": _apply_tumor_vs_normal_strict,
    "tumor_vs_normal_very_strict": _apply_tumor_vs_normal_very_strict,
    "tumor_vs_normal_relaxed": _apply_tumor_vs_normal_relaxed,
    "expression_floor_only": _apply_expression_floor_only,
    "any_normal_expression_blocks": _apply_any_normal_expression_blocks,
}


# ---------------------------------------------------------------------------
# Recommendation classification (shared across rules)
# ---------------------------------------------------------------------------

def classify_recommendation(
    base_score: int,
    tox_penalty: int,
    mutation_penalty: int,
    high_tox_blocks_priority: bool,
) -> tuple[int, str]:
    """Apply penalties and return (adjusted_score, recommendation).

    Recommendation tiers:
      adjusted >= 4 + no blocking + no mut penalty   → PRIORITY
      adjusted >= 4 + (blocking OR mut_penalty=1)    → GO or CONDITIONAL
      adjusted == 3                                  → CONDITIONAL
      adjusted == 2                                  → CAUTION
      adjusted == 1 or mutation_penalty >= 2         → CAUTION (or EXCLUDE
                                                                  if explicit)
    """
    adjusted = max(1, base_score - tox_penalty - mutation_penalty)

    # Mutation penalty ≥ 2 means target is significantly down-regulated in
    # the relevant mutation context — overrides everything else.
    if mutation_penalty >= 2:
        return adjusted, "CAUTION"

    if adjusted >= 4:
        if high_tox_blocks_priority:
            return adjusted, "CONDITIONAL"
        if mutation_penalty == 0:
            return adjusted, "PRIORITY"
        return adjusted, "GO"

    if adjusted == 3:
        return adjusted, "CONDITIONAL"

    return adjusted, "CAUTION"
