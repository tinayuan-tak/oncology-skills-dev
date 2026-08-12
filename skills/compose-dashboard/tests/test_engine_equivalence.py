"""Cross-engine EQUIVALENCE GOLDEN for the D2 synthesize() -> resolver swap.

BACKGROUND (why this test exists)
---------------------------------
The framework has TWO composition engines:

  1. The SHARED declarative resolver — `_skills_common.resolver.resolve_verdict_for_gate`
     over `target-contracts/resolvers/<gate>.resolver.yaml`. Used by the standalone focused
     skills + target-profile. Non-Turing: ordered precedence over the SET of fired rule IDs
     (when_fired / when_any_fired / when_all_fired). One verdict per gate.

  2. compose-dashboard's `scripts/_synthesis.py::synthesize()` — a PER-MODALITY `fit_level`
     scorer (strong / moderate / weak / insufficient_evidence / not_viable) that makes ZERO
     `resolve_verdict_for_gate` calls. It reuses the SAME `_skills_common.fired_rules` matcher
     (via `_build_signal_matrix`) but reconstructs the verdict itself.

Phase D / step D2 will REPLACE synthesize()'s verdict reconstruction with the resolver, keeping
`_build_signal_matrix` as an optional per-modality LENS. This golden PINS the relationship the
swap must preserve, over the SAME fired-rule set both engines consume, so Stage 2 has a precise
target and `test_end_to_end` / `test_compose_correctness` can be re-pointed with confidence.

This test is ADDITIVE and PASSES ON CURRENT TRUNK — it pins the CURRENT relationship, not the
post-swap one. Where a clean 1:1 mapping exists it asserts the equivalence; where it does not,
it PINS BOTH engine outputs verbatim and documents the exact correspondence inline.

WHAT IT PROVES
--------------
  * Surface (surface_modality gate, fit_class-driven): the resolver's single gate verdict and
    synthesize()'s per-modality fit_levels are driven by the SAME fired rule, and the resolver
    verdict names the modality whose synth arm is `strong`. neither_viable <-> both arms
    not_viable and both_viable <-> both arms strong are CLEAN. modality_ambiguous is a PINNED
    DIVERGENCE (resolver -> abstention verdict; synth -> ratio-based `weak`, no `insufficient`).
  * Intracellular (tractability_small_molecule gate, KRAS/COADREAD real stub through the full
    compose() pipeline): synth small_molecule=strong <-> resolver well_covered, and the
    resolver's driving_rule is a member of synth's small_molecule fired_rule_ids — the
    load-bearing cross-engine invariant.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# --- path wiring (mirror the sibling tests) ---------------------------------
SKILL_DIR = Path(__file__).resolve().parent.parent          # skills/compose-dashboard
SKILLS_ROOT = SKILL_DIR.parent                              # skills/
for p in (str(SKILL_DIR), str(SKILLS_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

# Import _synthesis via the `scripts` package so its relative imports
# (`from ._resolution import ...`, used when contracts_root is not None) resolve.
from scripts._synthesis import synthesize  # noqa: E402
from scripts.compose_dashboard import compose  # noqa: E402
from _skills_common import fired_rules, resolve_verdict_for_gate  # noqa: E402
from _skills_common.resolver import load_resolver  # noqa: E402

# target-contracts root (read-only). Matches the default the pipeline itself uses.
import os  # noqa: E402
CONTRACTS_ROOT = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))


# ============================================================================
# Shared helpers
# ============================================================================

def _norm_for_matcher(card_outputs: list[dict]) -> list[dict]:
    """Reproduce _build_signal_matrix's normalization: an applies_when-excluded card is
    marked _missing so fired_rules skips it — the SAME exclusion the synth engine applies.
    This is exactly the fired-rule set the swap will hand to resolve_verdict_for_gate."""
    return [dict(c, _missing=True) if c.get("excluded_by_applies_when") else c
            for c in card_outputs]


def _fired_over_cards(card_outputs: list[dict], axis: str) -> list[dict]:
    normed = _norm_for_matcher(card_outputs)
    surviving = [c["card_id"] for c in normed
                 if c.get("card_id") and not c.get("_missing")]
    return fired_rules(normed, axis=axis, card_id_filter=surviving)


# ============================================================================
# SURFACE case — surface_modality gate, driven by adc-tce-modality-fit.fit_class
# ============================================================================
#
# Golden table (PINNED against current trunk; captured empirically):
#
#   fit_class          resolver surface_modality verdict     synth adc / bite_tce fit_level
#   ------------------ ----------------------------------    ------------------------------
#   neither_viable     neither_viable                        not_viable / not_viable   [CLEAN]
#   both_viable        both_viable                           strong     / strong       [CLEAN]
#   ADC_preferred      adc_preferred                         strong     / weak         [preferred-arm]
#   TCE_preferred      tce_preferred                         weak       / strong       [preferred-arm]
#   modality_ambiguous modality_ambiguous                    weak       / weak         [DIVERGENCE — pinned]
#
# The two engines fire the SAME single rule (fit_class -> one rule) and the resolver verdict
# names the modality whose synth arm is `strong`. The ambiguous row is the (ii)-class semantic
# the swap must handle: the resolver has an explicit abstention verdict; synth has NO
# `insufficient` output for a single-in-scope neutral/insufficient signal and falls to `weak`.

_FIT_CARD = "adc-tce-modality-fit"
_SURFACE_AXIS = "surface_intrinsic"

# fit_class -> (resolver_verdict, driving_rule, {modality: synth_fit_level})
_SURFACE_GOLDEN = {
    "neither_viable": ("neither_viable", "neither-viable-killer",
                       {"adc": "not_viable", "bite_tce": "not_viable"}),
    "both_viable": ("both_viable", "both-viable-supportive",
                    {"adc": "strong", "bite_tce": "strong"}),
    "ADC_preferred": ("adc_preferred", "adc-preferred-supportive",
                      {"adc": "strong", "bite_tce": "weak"}),
    "TCE_preferred": ("tce_preferred", "tce-preferred-supportive",
                      {"adc": "weak", "bite_tce": "strong"}),
    "modality_ambiguous": ("modality_ambiguous", "modality-ambiguous-insufficient",
                           {"adc": "weak", "bite_tce": "weak"}),
}


def _surface_cards(fit_class: str) -> list[dict]:
    return [{
        "card_id": _FIT_CARD,
        "interpretation_call": "uninterpreted",
        "excluded_by_applies_when": False,
        "summary": {"fit_class": fit_class},
    }]


def _surface_run_plan(modalities: list[str]) -> dict:
    return {
        "axis_resolution": {"status": "resolved", "resolved_axis": _SURFACE_AXIS},
        "input_context": {"target_symbol": "TROP2", "indication": "COADREAD"},
        "loaded_modality_modules": [
            {"modality": m, "headline_decision_question": f"Q-{m}",
             "synthesis_emphasis": {"primary_cards": [_FIT_CARD], "secondary_cards": [],
                                    "modality_killer_conditions": []}}
            for m in modalities],
    }


def test_surface_resolver_spec_present():
    """Pre-condition: the surface_modality resolver spec loads (the swap's target gate)."""
    spec = load_resolver("surface_modality", CONTRACTS_ROOT)
    assert spec is not None and spec.get("gate") == "surface_modality"


@pytest.mark.parametrize("fit_class", list(_SURFACE_GOLDEN))
def test_surface_engine_equivalence(fit_class):
    """Both engines consume the SAME fired rule; assert the pinned resolver verdict AND the
    per-modality synth fit_levels, and the cross-engine correspondence between them."""
    exp_verdict, exp_driving, exp_fits = _SURFACE_GOLDEN[fit_class]
    cards = _surface_cards(fit_class)

    # --- Engine 2 (resolver) over the fired-rule set ---
    fired = _fired_over_cards(cards, _SURFACE_AXIS)
    fired_ids = {fr["rule_id"] for fr in fired}
    assert exp_driving in fired_ids, (
        f"fit_class={fit_class}: expected rule {exp_driving!r} to fire; got {sorted(fired_ids)}")
    verdict, driving = resolve_verdict_for_gate(fired, "surface_modality")
    assert (verdict, driving) == (exp_verdict, exp_driving), (
        f"fit_class={fit_class}: resolver verdict drift {(verdict, driving)!r} "
        f"!= pinned {(exp_verdict, exp_driving)!r}")

    # --- Engine 1 (synthesize) per-modality ---
    syn = synthesize(_surface_run_plan(["adc", "bite_tce"]), cards, contracts_root=CONTRACTS_ROOT)
    fits = {f["modality"]: f["fit_level"] for f in syn["modality_fit_assessment"]}
    assert fits == exp_fits, (
        f"fit_class={fit_class}: synth fit_levels drift {fits!r} != pinned {exp_fits!r}")

    # --- Cross-engine invariant: same driving rule feeds BOTH engines ---
    # synth records the fired rules per modality; the resolver's driving rule must be among them.
    all_synth_fired = set()
    for f in syn["modality_fit_assessment"]:
        all_synth_fired.update(f.get("fired_rule_ids", []))
    assert driving in all_synth_fired, (
        f"fit_class={fit_class}: resolver driving rule {driving!r} not in synth fired ids "
        f"{sorted(all_synth_fired)} — engines would not share provenance")


def test_surface_clean_mapping_neither_viable():
    """CLEAN 1:1 the swap must preserve exactly:
        resolver surface_modality == neither_viable  <->  synth emits not_viable for ALL
        surface modalities  <->  headline conveys 'no viable modality'."""
    cards = _surface_cards("neither_viable")
    fired = _fired_over_cards(cards, _SURFACE_AXIS)
    verdict, _ = resolve_verdict_for_gate(fired, "surface_modality")
    syn = synthesize(_surface_run_plan(["adc", "bite_tce"]), cards, contracts_root=CONTRACTS_ROOT)
    fits = {f["fit_level"] for f in syn["modality_fit_assessment"]}
    assert verdict == "neither_viable"
    assert fits == {"not_viable"}, f"expected every arm not_viable, got {fits}"
    assert "no viable modality" in syn["headline"].lower()


def test_surface_clean_mapping_both_viable():
    """CLEAN 1:1: resolver both_viable <-> synth strong on ALL surface arms."""
    cards = _surface_cards("both_viable")
    fired = _fired_over_cards(cards, _SURFACE_AXIS)
    verdict, _ = resolve_verdict_for_gate(fired, "surface_modality")
    syn = synthesize(_surface_run_plan(["adc", "bite_tce"]), cards, contracts_root=CONTRACTS_ROOT)
    fits = {f["fit_level"] for f in syn["modality_fit_assessment"]}
    assert verdict == "both_viable"
    assert fits == {"strong"}


def test_surface_pinned_divergence_modality_ambiguous():
    """DIVERGENCE (NOT a clean mapping) — PINNED so Stage 2 has a precise target.

    The resolver has an explicit abstention verdict `modality_ambiguous`. synthesize() has NO
    corresponding `insufficient` fit_level for a single-card-in-scope neutral/insufficient
    signal: the tier-2 `insufficient` signal produces neither a dominant hit nor a
    contradiction, so scoring falls through to the ratio path and yields `weak` (0/1 positive,
    1 in scope < MIN_IN_SCOPE_FOR_STRONG). The headline is NOT the 'Insufficient evidence'
    override (that fires only on >=3 NOT_INFORMATIVE interpretation_calls — a different
    mechanism). Stage-2 swap MUST decide how the resolver's modality_ambiguous surfaces
    (candidate: a distinct `insufficient`/`abstain` fit_level)."""
    cards = _surface_cards("modality_ambiguous")
    fired = _fired_over_cards(cards, _SURFACE_AXIS)
    verdict, driving = resolve_verdict_for_gate(fired, "surface_modality")
    syn = synthesize(_surface_run_plan(["adc", "bite_tce"]), cards, contracts_root=CONTRACTS_ROOT)
    fits = {f["modality"]: f["fit_level"] for f in syn["modality_fit_assessment"]}
    # Resolver side (abstention-class verdict)
    assert (verdict, driving) == ("modality_ambiguous", "modality-ambiguous-insufficient")
    # Synth side (ratio-based weak on both arms — the divergence)
    assert fits == {"adc": "weak", "bite_tce": "weak"}
    # Documented: synth does NOT emit an insufficient_evidence fit_level here, nor the
    # 'Insufficient evidence' headline override.
    assert "insufficient_evidence" not in fits.values()
    assert "insufficient evidence" not in syn["headline"].lower()


# ============================================================================
# INTRACELLULAR case — tractability_small_molecule gate, KRAS/COADREAD FULL PIPELINE
# ============================================================================
#
# Golden (PINNED against current trunk; KRAS/COADREAD stub through compose()):
#
#   synth small_molecule fit_level = strong          (dominant signal, no contradiction)
#   synth degrader       fit_level = strong
#   resolver tractability_small_molecule = well_covered
#        driving_rule = e7-triangulated-target-engaged-supportive
#   resolver dependency          = concordant_dependent
#   resolver genomic_alteration  = biomarker_stratified_dependency
#   resolver selectivity         = insufficient (no selectivity rule fires on the stub)
#
# NOT a clean 1:1: synth has 5 fit_levels, the resolver has 11 tractability verdicts. So we PIN
# BOTH sides + assert the load-bearing invariant: the resolver's driving_rule is a member of
# synth's small_molecule fired_rule_ids, i.e. both engines pivot off the SAME fired rule.

def _kras_pipeline():
    run_plan, ep, errors = compose(
        target="KRAS", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality=None, subgroup_spec="all",
        execution_mode="stub", deterministic_timestamps=True,
    )
    assert errors == [], f"compose() validation errors: {errors}"
    return run_plan, ep


def test_kras_synth_side_pinned():
    """Engine 1 (synthesize via full compose): small_molecule + degrader both `strong`."""
    _, ep = _kras_pipeline()
    fits = {f["modality"]: f["fit_level"] for f in ep["synthesis"]["modality_fit_assessment"]}
    assert fits == {"small_molecule": "strong", "degrader": "strong"}, f"drift: {fits}"
    assert "small_molecule fit is strong" in ep["synthesis"]["headline"]
    # Not the abstention headline — the positive path is exercised.
    assert "insufficient evidence" not in ep["synthesis"]["headline"].lower()


def test_kras_resolver_side_pinned():
    """Engine 2 (resolver) over the fired-rule set reconstructed from the SAME card_outputs."""
    _, ep = _kras_pipeline()
    fired = _fired_over_cards(ep["cards"], "intracellular_intrinsic")
    assert resolve_verdict_for_gate(fired, "tractability_small_molecule") == \
        ("well_covered", "e7-triangulated-target-engaged-supportive")
    assert resolve_verdict_for_gate(fired, "dependency") == \
        ("concordant_dependent", "concordant-dependent-supportive-dominant")
    assert resolve_verdict_for_gate(fired, "genomic_alteration") == \
        ("biomarker_stratified_dependency", "mutant-strongly-dependent-supportive")
    # No selectivity rule fires on the KRAS stub -> resolver abstains (default).
    assert resolve_verdict_for_gate(fired, "selectivity") == ("insufficient", None)


def test_kras_cross_engine_shared_driving_rule():
    """THE load-bearing equivalence invariant for the swap: the small_molecule gate verdict the
    resolver would emit (well_covered) is driven by e7-triangulated-target-engaged-supportive,
    which is ALSO a member of synthesize()'s small_molecule fired_rule_ids. Both engines pivot
    off the SAME fired rule over the SAME cards — so re-pointing synth's small_molecule
    fit_level to the resolver verdict preserves provenance and the positive call."""
    _, ep = _kras_pipeline()
    sm = next(f for f in ep["synthesis"]["modality_fit_assessment"]
              if f["modality"] == "small_molecule")
    fired = _fired_over_cards(ep["cards"], "intracellular_intrinsic")
    verdict, driving = resolve_verdict_for_gate(fired, "tractability_small_molecule")

    # Positive on both engines.
    assert sm["fit_level"] == "strong"
    assert verdict == "well_covered"
    # Shared provenance: resolver driving rule is in synth's per-modality fired ids.
    assert driving in sm["fired_rule_ids"], (
        f"resolver driving rule {driving!r} not in synth small_molecule fired_rule_ids "
        f"{sm['fired_rule_ids']} — the swap would lose the shared-provenance invariant")
