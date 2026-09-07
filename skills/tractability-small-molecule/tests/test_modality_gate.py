"""CASE-008 modality gate (v3.11.0, VERDICT-MOVING signal-vector).

A biologics-only approved antigen (approved ADC/TCE/CAR/mAb, no approved small molecule) must NOT mint
small-molecule tractability from DGIdb's modality-blind has_approved_drug flag. The AM reader emits
approved_drug_engagement_class=approved_biologic_only; the TC resolver rung
`known-drug-approved-biologic-only-sm-not-supportive` routes the DRUG axis to annotation_only_indirect
INSTEAD of the SM-supportive approved-drug rung. These tests pin:
  1. fired_rules maps approved_biologic_only → the new rung (and NOT the SM-supportive/indirect rungs);
  2. the resolver returns annotation_only_indirect for that rung, and stays chemically_active for a
     dual-modality SM target (approved_direct) — the osimertinib guard;
  3. _sm_modality_mismatch_caveat consumes the reader's authoritative approved_drug_modality and becomes
     a CONFIRMATION when the gate fired.
The top-line VERDICT is unchanged for the live calibration targets (DLL3/STEAP1 STRUCT-driven,
FOLR1/NECTIN4/CEACAM5 e7-discordant); this gate moves the DRUG-axis fired signal.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tsm_run_modality")

_ALL_CARD_IDS = ["prism-compound-activity", "prism-crispr-concordance", "dependency-predictability",
                 "structure-features-static", "known-drug-tractability", "degradation-feasibility",
                 "gdsc-drug-activity"]


def _cards(**summaries):
    return [{"card_id": cid, "summary": summaries.get(cid, {})} for cid in _ALL_CARD_IDS]


def _fired_for(known_drug_summary: dict):
    import _skills_common as skc
    cards = _cards(**{"known-drug-tractability": known_drug_summary})
    return skc.fired_rules(cards, "intracellular_intrinsic", card_id_filter=["known-drug-tractability"])


def _resolver_available() -> bool:
    try:
        return tp._snapshot([{"rule_id": "prism-no-compounds-found-neutral"}])[0] == "chemically_unhit"
    except RuntimeError:
        return False


# ── fired_rules mapping (the reader field → the rule) ─────────────────────────────────────────────
def test_biologic_only_fires_the_gate_rung_not_the_sm_supportive_rung():
    fired = _fired_for({"approved_drug_engagement_class": "approved_biologic_only",
                        "approved_drug_modality": "biologic"})
    ids = {f["rule_id"] for f in fired}
    assert "known-drug-approved-biologic-only-sm-not-supportive" in ids
    assert "known-drug-approved-antineoplastic-sm-supportive" not in ids   # SM rung gated OFF
    assert "known-drug-approved-indirect-only-sm-weak" not in ids          # mutually exclusive


def test_approved_direct_still_fires_sm_supportive_osimertinib_guard():
    fired = _fired_for({"approved_drug_engagement_class": "approved_direct",
                        "approved_drug_modality": "small_molecule_or_unknown"})
    ids = {f["rule_id"] for f in fired}
    assert "known-drug-approved-antineoplastic-sm-supportive" in ids
    assert "known-drug-approved-biologic-only-sm-not-supportive" not in ids


# ── resolver outcome ──────────────────────────────────────────────────────────────────────────────
@pytest.mark.skipif(not _resolver_available(), reason="tractability_small_molecule resolver spec not resolvable")
def test_resolver_biologic_only_maps_to_annotation_only_indirect():
    v, drv = tp._snapshot([{"rule_id": "known-drug-approved-biologic-only-sm-not-supportive"}])
    assert v == "annotation_only_indirect"
    assert drv == "known-drug-approved-biologic-only-sm-not-supportive"


@pytest.mark.skipif(not _resolver_available(), reason="tractability_small_molecule resolver spec not resolvable")
def test_resolver_biologic_only_loses_to_structural_and_offtarget():
    # DLL3/STEAP1 shape: a predicted structural pocket co-fires → structurally_ligandable WINS (verdict-stable).
    v, _ = tp._snapshot([{"rule_id": "known-drug-approved-biologic-only-sm-not-supportive"},
                         {"rule_id": "ligandability-predicted-sm-supportive"}])
    assert v == "structurally_ligandable"
    # FOLR1/NECTIN4/CEACAM5 shape: an e7 off-target read co-fires → discordant WINS (verdict-stable).
    v2, _ = tp._snapshot([{"rule_id": "known-drug-approved-biologic-only-sm-not-supportive"},
                          {"rule_id": "e7-discordant-off-target-warning"}])
    assert v2 == "discordant"


@pytest.mark.skipif(not _resolver_available(), reason="tractability_small_molecule resolver spec not resolvable")
def test_legacy_oracle_mirrors_resolver_for_the_new_rung():
    fired = [{"rule_id": "known-drug-approved-biologic-only-sm-not-supportive"}]
    assert tp._snapshot(fired) == tp._snapshot_legacy_oracle(fired)


# ── _sm_modality_mismatch_caveat ────────────────────────────────────────────────────────────────
def test_caveat_confirmation_when_gate_fired():
    hl = {"approved_drug_modality": "biologic", "approved_drug_modality_tag": "tce",
          "approved_drug_engagement_class": "approved_biologic_only", "has_approved_drug": True,
          "n_antineoplastic_interactions": 4}
    c = tp._sm_modality_mismatch_caveat(hl, target="DLL3")
    assert c is not None
    assert "MODALITY GATE FIRED" in c
    assert "approved_biologic_only" in c and "annotation_only_indirect" in c
    assert "modality=tce" in c


def test_caveat_mismatch_when_biologic_but_not_gated():
    # authoritative modality says biologic but the engagement class hasn't been gated (stale contract path)
    hl = {"approved_drug_modality": "biologic", "approved_drug_modality_tag": "adc",
          "approved_drug_engagement_class": "approved_direct", "has_approved_drug": True}
    c = tp._sm_modality_mismatch_caveat(hl, target="FOLR1")
    assert c is not None and "MODALITY MISMATCH" in c


def test_caveat_none_for_sm_or_unknown_and_not_applicable():
    assert tp._sm_modality_mismatch_caveat(
        {"approved_drug_modality": "small_molecule_or_unknown", "has_approved_drug": True}, target="EGFR") is None
    assert tp._sm_modality_mismatch_caveat(
        {"approved_drug_modality": "not_applicable"}, target="STEAP1") is None


def test_caveat_curated_fallback_when_card_field_absent():
    # degraded/stale run: card lacks approved_drug_modality → fall back to the curated set + has_approved
    assert tp._sm_modality_mismatch_caveat(
        {"has_approved_drug": True}, target="DLL3") is not None            # DLL3 ∈ curated set
    assert tp._sm_modality_mismatch_caveat(
        {"has_approved_drug": True}, target="BRAF") is None                # BRAF ∉ curated set → None


# ── #07: live biologics-only vocab reader (replaces the hardcoded fallback) ───────────────────────
def test_live_loader_covers_biologics_only_and_excludes_dual_sm():
    from _skills_common._live_readers import _load_biologics_precedent_modalities
    m = _load_biologics_precedent_modalities()
    # biologics-only antigens present with their modality tag
    assert m.get("DLL3") == "tce" and m.get("CEACAM5") == "adc_tce" and m.get("FOLR1") == "adc"
    # osimertinib guard: dual-modality SM targets + the SM-radioligand PSMA are EXCLUDED
    for g in ("EGFR", "ERBB2", "MET", "FOLH1"):
        assert g not in m, f"{g} must NOT be biologics_only (has approved/SM-radioligand chemistry)"


def test_caveat_live_fallback_excludes_dual_modality_target():
    # The DRIFT fix: on the degraded fallback path (card field absent), the LIVE vocab read must NOT
    # caveat ERBB2 (dual-modality — approved SM tucatinib/lapatinib), unlike the coarse hardcoded set.
    assert tp._sm_modality_mismatch_caveat({"has_approved_drug": True}, target="ERBB2") is None
    assert tp._sm_modality_mismatch_caveat({"has_approved_drug": True}, target="DLL3") is not None
