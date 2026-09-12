"""Governance for the interpretation-encoding reference-frame rulers (Stage 2).

Lives skills-side (not target-contracts) because it cross-checks SALIENCE_SPECS — which are defined in
_skills_common — against the card contracts' `outputs.summary_fields` + `thresholds:`; target-contracts
cannot import skills. Fail-soft when the contracts checkout is absent (isolated CI) so it never red-fails
on environment, only on a real spec/contract drift.

Invariants:
  1. Every verdict-bearing measurement_type is GAUGEABLE — has a `direction` (numeric ruler) OR a
     non-empty `categorical` (the class IS the ruler). No un-gaugeable verdict type.
  2. Every `reference_frame` is well-formed: value_field + scale (no bare number) + direction (to orient).
  3. Every reference_frame field (value/distance/position + anchor fields) is a REAL summary_field of the
     naming card (sync check — a renamed contract field can't silently break the ruler).
  4. Every reference_frame cut single-sources to a REAL numeric key in the driving card's `thresholds:`
     (never re-hardcoded; never dangling).
"""

import sys
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[1]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.evidence_salience import SALIENCE_SPECS, contract_threshold
from _skills_common.paths import target_contracts_root


@lru_cache(maxsize=256)
def _card_summary_fields(card_id: str):
    """The declared outputs.summary_fields of a card (or None when the contracts checkout is absent)."""
    p = target_contracts_root() / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return None
    spec = yaml.safe_load(p.read_text()) or {}
    fields = ((spec.get("outputs") or {}).get("summary_fields")) or []
    return {f for f in fields if isinstance(f, str)}


def _frames(mt):
    """A spec's reference_frame normalized to a LIST of frame dicts — one card may carry >1 ruler
    (reference_frame is a dict OR a list of dicts). Empty list when the type has no frame."""
    rf = SALIENCE_SPECS[mt].get("reference_frame")
    if isinstance(rf, list):
        return [f for f in rf if isinstance(f, dict)]
    return [rf] if isinstance(rf, dict) else []


def _cuts(rf):
    """Every cut dict on a frame: the single `cut` (distance_to_cut / floor_cut_ceiling / count_of_total)
    plus the `cuts` ladder (graded_band)."""
    return ([rf["cut"]] if isinstance(rf.get("cut"), dict) else []) + [
        c for c in (rf.get("cuts") or []) if isinstance(c, dict)
    ]


def test_every_verdict_bearing_type_is_gaugeable():
    bad = [mt for mt, s in SALIENCE_SPECS.items() if not (s.get("direction") or s.get("categorical"))]
    assert not bad, f"measurement_types with neither a direction (numeric ruler) nor categorical: {bad}"


# ── invariant 1b: the verdict-bearing SET comes from the CONTRACTS, not from SALIENCE_SPECS ────────────
# test_every_verdict_bearing_type_is_gaugeable above iterates SALIENCE_SPECS.items(), so a verdict-bearing
# measurement_type with NO SPEC AT ALL is INVISIBLE to it — it passes by not being enumerated. That is the
# vacuous half: when this was written, 13 of the 43 verdict-bearing types had no spec and the test was green.
# The authoritative set is derived here from the contracts instead: rules named `gating` in
# coverage/rule_role_partition.yaml → their when.card_id → that card's measurement_type.

# DECLARED DEBT, not a gap. Verdict-bearing types that carry no SALIENCE_SPEC yet, each owned by the review
# of its own subskill (this ratchet is scoped to genomic-alteration-profile, whose three —
# copy_number_alteration, mutation_variant_class_spectrum, mutation_clonality — were filled 2026-09-12).
# A NEW gating card must either ship a spec or be added here DELIBERATELY, with the owning review named.
_UNSPECCED_VERDICT_BEARING_DEBT = {
    "cis_dosage_coupling",  # cis-feature-expression-coherence — cis-feature-coherence review
    "dosage_sensitivity_safety",  # clingen-dosage — on-target-safety review
    "exon_window",  # modality-exon-window — modality-fit review
    "human_genetic_safety",  # gene-burden-safety — on-target-safety review
    "known_drug_tractability",  # known-drug-tractability — tractability review
    "paralog_buffering",  # paralog-buffering — functional-requirement review
    "partner_conditional_dependency",  # partner-conditional-dependency — combination review
    "pmhc_epitope_evidence",  # pmhc-epitope-evidence-iedb — pMHC review
    "pmhc_presentation",  # pmhc-presentation — pMHC review
    "sc_normal_celltype_expression",  # sc-normal-celltype-expression — tumor-selectivity review
}


@lru_cache(maxsize=1)
def _verdict_bearing_measurement_types():
    """{measurement_type} for every card named by a GATING interpretation rule, read from the contracts.
    None when the contracts checkout is absent."""
    root = target_contracts_root()
    part = root / "coverage" / "rule_role_partition.yaml"
    if not part.exists():
        return None
    gating = set((yaml.safe_load(part.read_text()) or {}).get("gating") or [])
    rule_to_card = {}
    for f in sorted((root / "interpretation-rules").glob("*.rules.yaml")):
        doc = yaml.safe_load(f.read_text())
        rules = doc if isinstance(doc, list) else ((doc or {}).get("rules") or [])
        for r in rules:
            if isinstance(r, dict) and r.get("rule_id"):
                rule_to_card[r["rule_id"]] = (r.get("when") or {}).get("card_id")
    gating_cards = {rule_to_card[r] for r in gating if rule_to_card.get(r)}
    types = set()
    for c in sorted((root / "cards").glob("*.card.yaml")):
        spec = yaml.safe_load(c.read_text()) or {}
        if spec.get("card_id") in gating_cards and spec.get("measurement_type"):
            types.add(spec["measurement_type"])
    return types


def test_every_contract_declared_verdict_bearing_type_has_a_spec():
    types = _verdict_bearing_measurement_types()
    if types is None:
        pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
    assert types, "derived NO verdict-bearing types — the derivation broke, not the contracts"
    unspecced = {t for t in types if t not in SALIENCE_SPECS}
    undeclared = sorted(unspecced - _UNSPECCED_VERDICT_BEARING_DEBT)
    assert not undeclared, (
        "verdict-bearing measurement_types with NO SALIENCE_SPEC and no declared debt entry "
        f"(a gating card whose numbers reach no capsule/ruler): {undeclared}"
    )


def test_the_unspecced_debt_list_has_no_stale_entries():
    """The ratchet's other direction: an entry that has since been given a spec, or that is no longer
    verdict-bearing, must LEAVE the list — otherwise the allowlist grows into a permanent excuse and stops
    measuring anything. This is what forces the list to shrink as each subskill review lands."""
    types = _verdict_bearing_measurement_types()
    if types is None:
        pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
    now_specced = sorted(t for t in _UNSPECCED_VERDICT_BEARING_DEBT if t in SALIENCE_SPECS)
    not_gating = sorted(t for t in _UNSPECCED_VERDICT_BEARING_DEBT if t not in types)
    assert not now_specced, f"declared debt that now HAS a spec — remove from the list: {now_specced}"
    assert not not_gating, f"declared debt that is no longer verdict-bearing — remove from the list: {not_gating}"


def test_the_genomic_verdict_bearing_types_are_all_specced():
    """The scope this PR closed, pinned so a later edit cannot quietly re-open it. These three are named by
    GATING genomic rules; copy_number_alteration and mutation_variant_class_spectrum key resolver rungs."""
    for mt in ("copy_number_alteration", "mutation_variant_class_spectrum", "mutation_clonality"):
        assert mt in SALIENCE_SPECS, f"{mt}: verdict-bearing genomic type lost its spec"
        assert mt not in _UNSPECCED_VERDICT_BEARING_DEBT, f"{mt}: specced, so it must not be in the debt list"


@pytest.mark.parametrize("mt", sorted(mt for mt, s in SALIENCE_SPECS.items() if s.get("reference_frame")))
def test_reference_frame_is_wellformed(mt):
    frames = _frames(mt)
    assert frames, f"{mt}: reference_frame present but no frame dict resolved"
    for rf in frames:
        assert rf.get("value_field"), f"{mt}: reference_frame needs a value_field"
        assert rf.get("scale"), f"{mt}: reference_frame needs a scale (no bare number)"
        assert SALIENCE_SPECS[mt].get("direction"), f"{mt}: reference_frame needs a direction to orient the gauge"
        assert rf.get("kind") in (
            "percentile",
            "floor_cut_ceiling",
            "comparator_delta",
            "distance_to_cut",
            "graded_band",
            "count_of_total",
            "cohort_percentile",
        ), f"{mt}: unknown frame kind {rf.get('kind')!r}"
        if rf.get("kind") == "graded_band":
            assert len(_cuts(rf)) >= 2, f"{mt}: graded_band needs >=2 cut anchors (the ladder)"
        if rf.get("kind") == "count_of_total":
            assert rf.get("total_field"), f"{mt}: count_of_total needs a total_field (the denominator)"
        if rf.get("kind") == "cohort_percentile":
            # the atlas feature key whose corpus column IS the known-target cohort; keyed as
            # {measurement_type}::num::{value_field} so it matches the atlas numeric feature.
            assert rf.get("cohort_key") == f"{mt}::num::{rf['value_field']}", (
                f"{mt}: cohort_percentile needs cohort_key '{mt}::num::{rf['value_field']}', got {rf.get('cohort_key')!r}"
            )


@pytest.mark.parametrize("mt", sorted(mt for mt, s in SALIENCE_SPECS.items() if s.get("reference_frame")))
def test_reference_frame_fields_are_real_summary_fields(mt):
    for rf in _frames(mt):
        card_id = next((c.get("card_id") for c in _cuts(rf) if c.get("card_id")), None)
        if not card_id:
            continue  # no cut card to anchor the summary-field sync check for this frame
        sf = _card_summary_fields(card_id)
        if sf is None:
            pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
        named = [rf.get("value_field"), rf.get("distance_field"), rf.get("position_field"), rf.get("total_field")]
        named += [a.get("field") for a in (rf.get("anchors") or []) if isinstance(a, dict)]
        missing = sorted(f for f in named if f and f not in sf)
        assert not missing, f"{mt}: reference_frame fields not in {card_id} outputs.summary_fields: {missing}"


@pytest.mark.parametrize(
    "mt",
    sorted(
        mt
        for mt, s in SALIENCE_SPECS.items()
        if any(
            _cuts(f)
            for f in (
                s["reference_frame"] if isinstance(s.get("reference_frame"), list) else [s.get("reference_frame")]
            )
            if isinstance(f, dict)
        )
    ),
)
def test_reference_frame_cut_resolves_to_a_real_threshold(mt):
    for rf in _frames(mt):
        for cut in _cuts(rf):
            if _card_summary_fields(cut.get("card_id")) is None:
                pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
            v = contract_threshold(cut.get("card_id"), cut.get("threshold"))
            assert v is not None, (
                f"{mt}: cut {cut.get('threshold')!r} does not resolve to a numeric key in "
                f"{cut.get('card_id')} thresholds: (single-source it from the contract)"
            )


def test_significance_field_added_for_mutation_stratified_is_real():
    # the Stage-2 coverage-gap fill must name a real summary_field
    sf = _card_summary_fields("mutation-stratified-dependency")
    if sf is None:
        pytest.skip("contracts checkout absent")
    assert "hotspot_mannwhitney_q" in sf
