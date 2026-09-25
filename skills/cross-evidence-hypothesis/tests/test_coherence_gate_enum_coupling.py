"""Coupling / drift guards for the coherence layer's verdict vocabulary (#1607).

The coherence layer (`is_negative_verdict` / `NEGATIVE_SIGNAL_VERDICTS` / `INTRINSIC_CONTRADICTIONS`)
must recognise the SAME measured-negative verdict tokens the nomination gate kills on. Its token set
had DRIFTED from the gate enum, fail-OPENing on most measured negatives (not_dependent_in_indication,
the surface/selectivity/safety/tractability kills), and `INTRINSIC_CONTRADICTIONS.contradicted_by`
carried two phantom / abstain tokens (no_sl_partner, no_partner_mapped) so its rule was vacuous.

These tests pin the alignment to the LIVE target-contracts vocabulary, so a future gate kill (or a
renamed card enum value) can never silently re-open the hole:

  * every non-`uncorroborated` kill_capable_verdicts token is recognised as a measured negative;
  * every INTRINSIC_CONTRADICTIONS.contradicted_by value is a live card-enum token (kills phantoms);
  * plus behavioural checks: a positive thesis resting on a measured-negative axis is flagged (was
    fail-open), a genuinely coherent package is not, and the SL intrinsic rule fires on the real
    no_curated_sl_partner negative.

`uncorroborated` dispositions (dependency=discordant, selectivity=discordant_across_comparators) are the
gate's own "absence of resolution, NOT a measurement against the target" class and are DELIBERATELY not
required here (see test_coherence_and_survival.test_is_negative_verdict_polarity)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))

import hypothesis_core as hc  # noqa: E402

# Same resolution as skills/_skills_common/paths.py: env TARGET_CONTRACTS_ROOT (set by CI) else the
# sibling-repo default. CI checks out target-contracts at the pinned SHA into this path.
_CONTRACTS_ROOT = Path(
    os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts",
    )
)
_GATE_YAML = _CONTRACTS_ROOT / "vocabularies" / "nomination_verdict_gate.yaml"


def _norm_set(tokens) -> set:
    return {hc._norm(t) for t in tokens}


def _load_gate() -> dict:
    assert _GATE_YAML.exists(), f"gate vocab not found at {_GATE_YAML} (TARGET_CONTRACTS_ROOT?)"
    return yaml.safe_load(_GATE_YAML.read_text())


def _card_enum_tokens(card_id: str) -> set:
    path = _CONTRACTS_ROOT / "cards" / f"{card_id}.card.yaml"
    assert path.exists(), f"card not found: {path}"
    voc = (yaml.safe_load(path.read_text()).get("outputs") or {}).get("summary_fields_vocabulary") or {}
    out: set = set()
    for values in voc.values():
        out |= set(values or [])
    return out


# ============================ drift guard: gate enum ⊆ recognised negatives ========================
def test_negative_signal_verdicts_cover_gate_enum():
    """Every non-`uncorroborated` kill_capable_verdicts token MUST be a recognised measured negative —
    the realignment that closes the fail-open, and the guard that keeps it closed on future gate churn."""
    reg = _load_gate()["kill_capable_verdicts"]
    required = {e["verdict"] for entries in reg.values() for e in entries if e.get("disposition") != "uncorroborated"}
    # sanity: the corpus-dominant veto + a kill from each of the previously-blind axes are in the gate
    for tok in (
        "not_dependent_in_indication",
        "tce_unsafe_normal_liability",
        "selective_but_stromal_confound",
        "highly_constrained_safety_concern",
        "structurally_intractable",
    ):
        assert tok in required, f"{tok} unexpectedly absent from gate kill set — test/gate drift"
    missing = {t for t in required if not hc.is_negative_verdict(t)}
    assert not missing, f"coherence layer fail-OPEN on gate kill tokens: {sorted(missing)}"
    # the uncorroborated tokens are deliberately NOT required (gap-adjacent, not measured negatives)
    assert hc.is_negative_verdict("discordant_across_comparators") is False


# ============================ phantom kill: contradicted_by values are live enum tokens ============
def test_intrinsic_contradiction_values_are_live_enum_tokens():
    """Every INTRINSIC_CONTRADICTIONS.contradicted_by value must be a real enum token on the card it
    keys — the guard that kills the vacuous no_sl_partner (phantom) / no_partner_mapped (abstain) rule."""
    card_enums = {
        "synthetic_lethal_partners": _card_enum_tokens("synthetic-lethal-partners"),
        "partner_conditional_dependency": _card_enum_tokens("partner-conditional-dependency"),
    }
    checked = 0
    for rule in hc.INTRINSIC_CONTRADICTIONS:
        for sig, negvals in rule["contradicted_by"].items():
            enum = card_enums.get(hc._norm(sig))
            if enum is None:  # a key that is not one of the cards we snapshot here
                continue
            for v in negvals:
                assert v in enum, f"contradicted_by[{sig}]={v!r} is not a live enum token of {sig}"
                checked += 1
    assert checked > 0, "no INTRINSIC_CONTRADICTIONS values were checked — coupling test went vacuous"
    # the retired phantom is NOT an enum member anywhere (documents WHY it was vacuous)
    assert "no_sl_partner" not in card_enums["synthetic_lethal_partners"]
    assert "no_sl_partner" not in card_enums["partner_conditional_dependency"]


# ============================ behaviour: positive thesis on a measured-negative axis ===============
def test_ndi_positive_thesis_on_measured_negative_axis_now_flagged():
    """A causal_rationale resting on dependency=not_dependent_in_indication (the corpus-dominant veto,
    fail-OPEN before #1607) as SUPPORT, unsurfaced, now raises the coherence violation."""
    conv = {"dependency": "not_dependent_in_indication", "mechanism": "well_characterized"}
    clauses = {"causal_rationale": {"support": ["dependency", "mechanism"], "surfaced": []}}
    v = hc.coherence_violations(clauses, conv, [], [], {"dependency", "mechanism"}, out_of_scope=set())
    assert v["causal_rationale"][0]["type"] == "negative_signal_asserted"
    assert v["causal_rationale"][0]["dimension"] == "dependency"


def test_coherent_package_positive_verdicts_not_flagged():
    """A genuinely coherent package — every cited axis carries a POSITIVE verdict — raises nothing."""
    conv = {
        "dependency": "strongly_selective_dependency",
        "selectivity": "strong_tumor_selective",
        "mechanism": "well_characterized",
    }
    clauses = {
        "causal_rationale": {"support": ["dependency", "selectivity", "mechanism"], "surfaced": []},
        "therapeutic_hypothesis": {"support": ["dependency", "selectivity"], "surfaced": []},
    }
    present = {"dependency", "selectivity", "mechanism"}
    assert hc.coherence_violations(clauses, conv, [], [], present, out_of_scope=set()) == {}


def test_intrinsic_sl_fires_on_no_curated_sl_partner():
    """The realigned SL intrinsic rule fires on the SL card's real measured negative
    (no_curated_sl_partner), which the vacuous {no_partner_mapped, no_sl_partner} keys could never see."""
    conv = {
        "combinatorial_dependency": "constitutive_combinatorial_dependency",
        "synthetic_lethal_partners": "no_curated_sl_partner",
    }
    clauses = {"therapeutic_hypothesis": {"support": ["combinatorial-dependency"], "surfaced": []}}
    present = {"combinatorial-dependency", "synthetic_lethal_partners"}
    v = hc.coherence_violations(clauses, conv, [], [], present, out_of_scope=set())
    labels = [x.get("label") for x in v.get("therapeutic_hypothesis", [])]
    assert "combination_or_sl_strategy_without_mapped_partner" in labels
