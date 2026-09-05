"""Unified skill_report assembler (docs/UNIFIED_OUTPUT_CONTRACT.md)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _skills_common.skill_report import (  # noqa: E402
    build_skill_report, canonical_polarity, ROLE_GATING, ROLE_DESCRIPTIVE, ROLE_INERT)

_HB = {
    "verdict": {"call": "highly_constrained_safety_concern", "phrase": "Highly LoF-constrained — full-KO risk",
                "polarity": "negative"},
    "confidence": {"level": "high", "basis": "gnomAD measured"},
    "top_tension": {"text": "WT-loss concern is modality-conditional", "severity": 2},
    "headline_text": "Highly LoF-constrained — high confidence",
}
_CV = {
    "A": {"signal": "strong", "corroboration": "high", "conflict": None, "informs": "constraint",
          "evidence_atom": {"cite": {"card_id": "gnomad-lof-constraint", "fields": ["pli_score"]}}},
    "homogeneity": "n/a",          # non-atom key must be skipped
    "_disclaimer": "…",
}
# a claim whose corroboration comes from a DIFFERENT card than its signal (presence abundance pattern):
_CV_MULTI = {
    "A": {"signal": "weak", "corroboration": "moderate", "conflict": None, "informs": "abundance",
          "evidence_atom": {"cite": {"card_id": "tumor-rna-distribution", "fields": ["median_log2tpm"]}},
          "corr_cite": {"card_id": "rna-protein-concordance-tumor", "fields": ["rna_as_biomarker"]}},
}


def test_gating_report_shape_and_polarity():
    r = build_skill_report(role=ROLE_GATING, verdict="highly_constrained_safety_concern",
                           driving_rule_id="highly-constrained-safety-warning", headline_block=_HB,
                           claim_vector=_CV, fired_rule_ids=["highly-constrained-safety-warning"],
                           cards_used=["gnomad-lof-constraint"])
    assert r["role"] == "gating"
    assert r["call"] == "highly_constrained_safety_concern"
    assert r["polarity"] == "opposing"                    # negative → opposing (canonical floor)
    assert r["honest_phrase"] == "Highly LoF-constrained — full-KO risk"
    assert r["confidence"]["level"] == "high"
    assert r["top_tension"]["severity"] == 2
    # claim_chips: only the real atom (A), decoupled signal+corroboration, with its cite; scalars skipped
    assert [c["key"] for c in r["claim_chips"]] == ["A"]
    a = r["claim_chips"][0]
    assert a["signal"] == "strong" and a["corroboration"] == "high"
    # single-source chip → cites is a length-1 list, role-tagged; `cite` is the raw primary (back-compat)
    assert a["cites"] == [{"role": "signal", "card_id": "gnomad-lof-constraint", "fields": ["pli_score"]}]
    assert a["cite"] == {"card_id": "gnomad-lof-constraint", "fields": ["pli_score"]}
    assert r["provenance"]["driving_rule_id"] == "highly-constrained-safety-warning"


def test_chip_tracks_multiple_source_cards():
    # a chip whose corroboration comes from a different card than its signal → cites lists BOTH, role-tagged
    r = build_skill_report(role=ROLE_DESCRIPTIVE, verdict=None, claim_vector=_CV_MULTI)
    cites = r["claim_chips"][0]["cites"]
    assert cites == [
        {"role": "signal", "card_id": "tumor-rna-distribution", "fields": ["median_log2tpm"]},
        {"role": "corroboration", "card_id": "rna-protein-concordance-tumor", "fields": ["rna_as_biomarker"]},
    ]


def test_descriptive_and_inert_are_not_scored():
    assert canonical_polarity(ROLE_DESCRIPTIVE, _HB) == "not_scored"
    assert canonical_polarity(ROLE_INERT, _HB) == "not_scored"
    r = build_skill_report(role=ROLE_DESCRIPTIVE, verdict=None, headline_block=_HB, claim_vector=_CV)
    assert r["call"] is None and r["polarity"] == "not_scored"


def test_explicit_killer_override_and_positive_map():
    assert canonical_polarity(ROLE_GATING, {"verdict": {"polarity": "positive"}}) == "supportive"
    # a skill that knows the call is a veto passes canonical killer explicitly
    assert canonical_polarity(ROLE_GATING, _HB, explicit="killer") == "killer"


def test_bad_role_rejected():
    import pytest
    with pytest.raises(ValueError):
        build_skill_report(role="bogus", verdict=None)


def test_claim_scalars_carry_non_atom_coordinates():
    # non-atom entries (e.g. presence homogeneity) are dropped from chips but preserved in claim_scalars,
    # so the spine is a lossless carrier of the claim vector; private `_`-keys are excluded.
    r = build_skill_report(role=ROLE_DESCRIPTIVE, verdict=None, claim_vector=_CV)
    assert [c["key"] for c in r["claim_chips"]] == ["A"]          # atoms → chips
    assert r["claim_scalars"] == {"homogeneity": "n/a"}          # scalar preserved, _disclaimer excluded


def test_claim_chips_by_subtype_rides_the_spine():
    rows = [{"stratum": "MSI", "evidence_state": "measured", "dependency_class": "dependent"}]
    r = build_skill_report(role=ROLE_GATING, verdict="x", headline_block=_HB, claim_chips_by_subtype=rows)
    assert r["claim_chips_by_subtype"] == rows
    # None (not []) when the skill emits no subtype panorama — the whole-cohort spine
    assert build_skill_report(role=ROLE_GATING, verdict="x", headline_block=_HB)["claim_chips_by_subtype"] is None


def test_modality_scope_is_first_class_on_the_spine():
    # the FOR-WHAT projection rides the spine as a top-level slot (the modality_fit rollup reads it here,
    # not a claim_record_shadow reach-in); None for a modality-blind skill that passes nothing.
    ms = {"small_molecule": "favorable", "biologics": "na", "_refinements": {"degrader": "conditional"}}
    r = build_skill_report(role=ROLE_GATING, verdict="x", headline_block=_HB, modality_scope=ms)
    assert r["modality_scope"] == ms
    assert build_skill_report(role=ROLE_GATING, verdict="x", headline_block=_HB)["modality_scope"] is None


def test_subgroup_signals_ride_the_spine():
    # hierarchy sub-group signals ride the spine so the composed report can render the embedded sub-skill
    # view (bands + per-skill scatter); None for a skill that emits no hierarchy signals.
    sg = {"abundance": {"signal": "strong", "confidence": "high", "n_sources": 2, "n_agree": 2,
                        "power": "high", "conflict": False, "sources": []}}
    r = build_skill_report(role=ROLE_GATING, verdict="x", headline_block=_HB, subgroup_signals=sg)
    assert r["subgroup_signals"] == sg
    assert build_skill_report(role=ROLE_GATING, verdict="x", headline_block=_HB)["subgroup_signals"] is None
