"""Behavioral golden for cis_coherence.resolver.yaml (cis-feature-coherence Stage 0, 2026-08-20).

cis_coherence is a deterministic 2x2 cross-tab of two coherence legs:
  leg-1  feature -> own-expression   (cis_dosage_class; the NEW cis-feature-expression-coherence card)
  leg-2  expression/feature -> own-dependency  (correlation_class OR amp_expr_stratification_class)

These pins encode the full cross-tab + the OR-on-leg-2 + the honest-abstention default. Evaluated with
a self-contained first-match interpreter that mirrors claude-oncology-skills/_skills_common/resolver.py
::resolve_verdict — the ONE engine the skills call — so this is the target-contracts-side golden.

VERDICT-INERT: cis_coherence is a dedicated self-contained axis (like combination_opportunity), NOT in
the skills gating axes. This golden pins the classification only; no nomination gate depends on it.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
SPEC = yaml.safe_load((REPO / "resolvers" / "cis_coherence.resolver.yaml").read_text())

# leg tokens (fired by interpretation-rules/cis-coherence.rules.yaml)
DOSAGE_COUPLED = "cis-dosage-coupled-supportive"          # leg-1 +
DOSAGE_UNCOUPLED = "cis-dosage-uncoupled-neutral"         # leg-1 - (measured, CN-independent)
DEP_CORR = "cis-expr-dependency-coupled-supportive"       # leg-2 + (correlation leg)
DEP_ABSENT = "cis-expr-dependency-absent-neutral"         # leg-2 - (no expr->dep)
DEP_CONJOINT = "cis-conjoint-dependent-supportive"        # leg-2 + (amp-expr conjoint leg)


def resolve(*fired_ids: str) -> tuple[str, str | None]:
    """First-match interpreter — byte-identical semantics to _skills_common/resolver.py."""
    fired = set(fired_ids)
    for rung in SPEC.get("resolve", []):
        verdict = rung["verdict"]
        if "when_fired" in rung:
            rid = rung["when_fired"]
            if rid in fired:
                return verdict, (rung.get("driving_rule") or rid)
        elif "when_any_fired" in rung:
            for rid in rung["when_any_fired"]:
                if rid in fired:
                    return verdict, (rung.get("driving_rule") or rid)
        elif "when_all_fired" in rung:
            rids = rung["when_all_fired"]
            if all(r in fired for r in rids):
                return verdict, (rung.get("driving_rule") or rids[-1])
    return SPEC["default"], None


# --- the four cross-tab cells -------------------------------------------------

def test_coupled_and_dependent_is_coherent_cis_driver():
    """leg-1 coupled + leg-2 dependent (either leg) → coherent_cis_driver, cis-dosage as driver.
    The oncogene-addiction chain (ERBB2/MYC/KRAS-amp): CN drives expression drives dependency."""
    assert resolve(DOSAGE_COUPLED, DEP_CONJOINT) == ("coherent_cis_driver", DOSAGE_COUPLED)
    assert resolve(DOSAGE_COUPLED, DEP_CORR) == ("coherent_cis_driver", DOSAGE_COUPLED)


def test_coupled_but_dependency_absent_is_expressed_cis_coupled_inert():
    """leg-1 coupled + leg-2 absent → expressed_cis_coupled_inert (the abundance-laundering guard):
    CN drives expression, but more abundance does not mean more required."""
    assert resolve(DOSAGE_COUPLED, DEP_ABSENT) == ("expressed_cis_coupled_inert", DEP_ABSENT)


def test_uncoupled_but_dependent_is_dependency_without_cis_dosage():
    """leg-1 uncoupled + leg-2 dependent → dependency_without_cis_dosage: a real dependency, but the
    expression is copy-number-INDEPENDENT (trans/lineage-regulated), not amplification-driven."""
    assert resolve(DOSAGE_UNCOUPLED, DEP_CONJOINT) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)
    assert resolve(DOSAGE_UNCOUPLED, DEP_CORR) == ("dependency_without_cis_dosage", DOSAGE_UNCOUPLED)


def test_uncoupled_and_absent_is_cis_uncoupled_no_dependency():
    """leg-1 uncoupled + leg-2 absent → cis_uncoupled_no_dependency (no coherent cis chain)."""
    assert resolve(DOSAGE_UNCOUPLED, DEP_ABSENT) == ("cis_uncoupled_no_dependency", DOSAGE_UNCOUPLED)


# --- coherent wins first-match when BOTH leg-2 signals fire (no double-count) --

def test_coherent_wins_when_both_leg2_signals_fire():
    # Conjoint + correlation both present with a coupled leg-1 → still one coherent_cis_driver.
    assert resolve(DOSAGE_COUPLED, DEP_CONJOINT, DEP_CORR) == ("coherent_cis_driver", DOSAGE_COUPLED)


def test_coherent_wins_over_inert_when_dep_present_and_absent_both_fire():
    # Defensive: if a card mis-emits both a dep-coupled AND dep-absent token, the coherent rung
    # precedes the inert rung in the ladder → coherent wins (present beats absent, first-match).
    assert resolve(DOSAGE_COUPLED, DEP_CORR, DEP_ABSENT)[0] == "coherent_cis_driver"


# --- honest abstention: any leg untestable/unmeasured -> default --------------

def test_nothing_fired_is_default_insufficient():
    assert resolve() == ("insufficient_cis_coherence", None)


def test_dosage_only_no_leg2_is_insufficient():
    # leg-1 present but leg-2 entirely unmeasured (no correlation/conjoint token) → cannot assemble
    # the chain → honest abstention, NOT a coherent or inert claim.
    assert resolve(DOSAGE_COUPLED) == ("insufficient_cis_coherence", None)


def test_leg2_only_no_dosage_is_insufficient():
    # leg-2 present but leg-1 untestable (cn_invariant_panel / data_unavailable fire no leg-1 token)
    # → cannot establish whether the dependency is cis-driven → abstain.
    assert resolve(DEP_CORR) == ("insufficient_cis_coherence", None)
    assert resolve(DEP_CONJOINT) == ("insufficient_cis_coherence", None)
