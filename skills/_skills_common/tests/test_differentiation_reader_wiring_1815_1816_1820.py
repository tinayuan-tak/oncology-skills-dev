"""Reader-wiring guard for differentiation-landscape #1815 / #1816 / #1820.

These pin that the newly-READ fields actually REACH an output object — the claim-vector atoms and the
question-table rows — not merely get dispatched-and-dropped (cf. #1580). Each test stores the RAW card
summary / headline input and re-derives via the real functions, so it CAN fail: on the pre-#1967 code the
atoms omitted these keys and there was no Q5 row.

All verdict-inert: these are render facets, never a resolver rung.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.differentiation_claims import differentiation_claim_vector  # noqa: E402
from _skills_common.differentiation_question_table import differentiation_question_table  # noqa: E402


def _by_id(rows: list) -> dict:
    return {r["id"]: r for r in rows}


# ---- #1820: emitted-but-unread fields now retained on the claim-vector atoms -------------------------


def test_survival_atom_retains_median_ostime_effect_size():
    # (#1820 F4) the KM EFFECT SIZE (per-arm median OS days) reaches the SURVIVAL atom `values`, not only
    # the class token + p/n counts.
    cards = [
        {
            "card_id": "expression-clinical-association",
            "summary": {
                "survival_association_class": "expression_high_worse_survival",
                "logrank_p": 0.003,
                "n_patients": 430,
                "n_events": 210,
                "median_ostime_high_days": 540.0,
                "median_ostime_low_days": 1180.0,
            },
        }
    ]
    vals = differentiation_claim_vector({}, cards)["SURVIVAL"]["evidence_atom"]["values"]
    assert vals["median_ostime_high_days"] == 540.0
    assert vals["median_ostime_low_days"] == 1180.0


def test_prognosis_atom_retains_pan_cancer_class():
    # (#1820 F5) the clean independent pan-cancer PRECOG class reaches the PROGNOSIS atom.
    cards = [
        {
            "card_id": "precog-prognostic-association",
            "summary": {
                "prognostic_class": "expression_high_worse_survival",
                "pan_cancer_prognostic_class": "unfavorable",
                "meta_z": 3.4,
                "n_precog_datasets": 12,
            },
        }
    ]
    vals = differentiation_claim_vector({}, cards)["PROGNOSIS"]["evidence_atom"]["values"]
    assert vals["pan_cancer_prognostic_class"] == "unfavorable"


def test_node_atom_retains_single_ko_leverage_understated():
    # (#1820 F7) the single-KO leverage-understated caveat reaches the NODE atom.
    cards = [
        {
            "card_id": "pathway-node-leverage",
            "summary": {
                "node_leverage_class": "dominant_node",
                "evidence_scope": "within_indication",
                "single_ko_leverage_understated": True,
            },
        }
    ]
    vals = differentiation_claim_vector({}, cards)["NODE"]["evidence_atom"]["values"]
    assert vals["single_ko_leverage_understated"] is True


def test_absent_effect_size_keys_are_simply_omitted():
    # Absence trap: a card summary lacking the new keys must not fabricate them (non-None-only retention).
    cards = [
        {
            "card_id": "expression-clinical-association",
            "summary": {"survival_association_class": "expression_high_worse_survival", "logrank_p": 0.003},
        }
    ]
    vals = differentiation_claim_vector({}, cards)["SURVIVAL"]["evidence_atom"]["values"]
    assert "median_ostime_high_days" not in vals
    assert "median_ostime_low_days" not in vals


# ---- #1815: mutational-signature-context reaches the Q5 question-table row --------------------------


def test_q5_mutational_process_reaches_the_question_table():
    # (#1815) a present dominant mutational process reaches the Q5 row primary + support (moderate INFORMS
    # signal), verdict-inert. CAN fail: pre-#1815 there was no Q5 row.
    h = {
        "claim_vector": {},
        "mutational_dominant_process": "MMR_deficiency",
        "mutational_mmr_deficiency_class": "high",
        "mutational_hrd_class": "low",
    }
    rows = differentiation_question_table(h)
    assert [r["id"] for r in rows] == ["Q1", "Q2", "Q3", "Q4", "Q5"]
    q5 = _by_id(rows)["Q5"]
    assert "MMR_deficiency" in q5["primary"]
    assert "MMR-deficiency: high" in q5["support"] and "HRD: low" in q5["support"]
    assert q5["signal"]["tier"] == "moderate" and q5["signal"]["polarity"] == "informs"


def test_q5_absent_is_an_unmeasured_row_never_omitted():
    # No mutational card -> Q5 still present as an unmeasured row (names the gap), never dropped.
    q5 = _by_id(differentiation_question_table({"claim_vector": {}}))["Q5"]
    assert q5["signal"]["tier"] == "unmeasured"


def test_q5_data_unavailable_and_none_are_treated_as_no_dominant_process():
    for sentinel in ("data_unavailable", "none"):
        q5 = _by_id(differentiation_question_table({"claim_vector": {}, "mutational_dominant_process": sentinel}))["Q5"]
        assert q5["signal"]["tier"] == "unmeasured"


# ---- #1816: oncogenic-pathway-alteration reaches the Q3 question-table support ----------------------


def test_q3_oncogenic_pathway_alteration_reaches_the_question_table():
    # (#1816) genomic pathway-alteration frequency lens reaches Q3 support alongside the NODE dependency
    # class — the "frequently altered AND best node, or dominated?" story. Verdict-inert.
    h = {
        "claim_vector": {"NODE": {"signal": "strong", "corroboration": "moderate", "evidence": "dominant_node"}},
        "node_leverage_class": "dominant_node",
        "oncogenic_pathway_class": "frequently_altered",
        "target_pathway_alteration": "RTK-RAS altered in 62% of cohort",
        "node_single_ko_leverage_understated": True,
    }
    q3 = _by_id(differentiation_question_table(h))["Q3"]
    assert "pathway-alteration: frequently_altered" in q3["support"]
    assert "target pathway alteration: RTK-RAS altered in 62% of cohort" in q3["support"]
    assert "single-KO leverage understated" in q3["support"]


def test_q4_resistance_and_withdrawn_bits_reach_the_question_table():
    # (#1820 F6/F7) reported resistance mechanisms + withdrawn competitor agents reach Q4 support.
    h = {
        "claim_vector": {},
        "highest_clinical_stage": "phase_2",
        "resistance_mechanisms_reported": ["gatekeeper mutation"],
        "competitor_withdrawn_agents": ["drugX"],
    }
    q4 = _by_id(differentiation_question_table(h))["Q4"]
    assert "resistance mechanisms reported" in q4["support"]
    assert "withdrawn agents" in q4["support"]
