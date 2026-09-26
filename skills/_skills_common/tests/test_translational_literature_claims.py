"""Claim vectors + question tables for the two DESCRIPTIVE context skills that gained a spine
(translational-readiness, literature-context). Verdict-INERT projections; no S3/LLM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _skills_common.literature_context_claims import (  # noqa: E402
    literature_context_claim_vector as lc_cv,
)
from _skills_common.literature_context_claims import (
    literature_context_key_signals as lc_ks,
)
from _skills_common.literature_context_question_table import (  # noqa: E402
    literature_context_question_table as lc_qt,
)
from _skills_common.translational_readiness_claims import (  # noqa: E402
    translational_readiness_claim_vector as tr_cv,
)
from _skills_common.translational_readiness_claims import (
    translational_readiness_key_signals as tr_ks,
)
from _skills_common.translational_readiness_question_table import (  # noqa: E402
    translational_readiness_question_table as tr_qt,
)


# ── translational-readiness ────────────────────────────────────────────────────────────────────────
def test_translational_claim_vector_maps_all_four_legs():
    hl = {
        "model_availability_class": "deep_model_coverage",
        "n_patient_derived_models": 60,
        "genotype_matched_class": "matched_sparse",
        "n_models_with_alteration": 3,
        "organoid_dependency_class": "selective_organoid_dependency",
        "organoid_frac_dependent": 0.3,
        "pdx_drug_response_class": "pdx_objective_responders",
        "pdx_responder_fraction": 0.4,
    }
    v = tr_cv(hl, [])
    assert [k for k in v if not k.startswith("_")] == ["MODEL", "GENOTYPE", "ORGANOID", "PDX"]
    # MODEL corroboration is `single_arm`, not `high`: the old value was a band on
    # `n_patient_derived_models` (60 models → `high`). A model COUNT is the depth of one PDX/organoid
    # repository read, not a second repository agreeing with the first — 60 models from one source is
    # still one source. The count itself is not lost: `deep_model_coverage` already carries it on the
    # signal axis, which is where a magnitude belongs.
    assert v["MODEL"]["signal"] == "strong" and v["MODEL"]["corroboration"] == "single_arm"
    assert v["GENOTYPE"]["signal"] == "moderate"
    assert v["ORGANOID"]["signal"] == "moderate"
    assert v["PDX"]["signal"] == "strong"
    assert "evidence_atom" in v["MODEL"]  # citable


def test_translational_measured_negatives_vs_gaps():
    # genotype `none` = MEASURED negative (absent); pdx unavailable + data_unavailable = gap (unmeasured)
    v = tr_cv(
        {
            "genotype_matched_class": "none",
            "pdx_drug_response_class": "pdx_response_unavailable",
            "model_availability_class": "data_unavailable",
            "organoid_dependency_class": "not_organoid_dependent",
        },
        [],
    )
    assert v["GENOTYPE"]["signal"] == "absent"
    assert v["ORGANOID"]["signal"] == "absent"  # measured non-reproduction
    assert v["PDX"]["signal"] == "unmeasured"
    assert v["MODEL"]["signal"] == "unmeasured"


def test_translational_question_table_full_ladder_even_when_empty():
    rows = tr_qt({"claim_vector": tr_cv({}, [])})
    assert [r["id"] for r in rows] == ["Q1", "Q2", "Q3", "Q4"]  # never omitted — names the gap
    assert all(r["signal"]["tier"] == "unmeasured" for r in rows)


def test_translational_key_signals_headline():
    assert (
        "validatable"
        in tr_ks({"model_availability_class": "deep_model_coverage", "n_patient_derived_models": 60}, [])[
            "headline"
        ].lower()
    )


# ── literature-context ───────────────────────────────────────────────────────────────────────────────
def test_literature_claim_vector_status_gating():
    ok = lc_cv(
        {
            "cited_evidence_status": "ok",
            "paper_disease_mentions": 30,
            "recent_mentions": 8,
            "n_diseases": 5,
            "total_relation_publications": 14,
            "relation_types": ["inhibit"],
        },
        [],
    )
    # VOLUME corroboration is `single_arm`, not `high` (#1600): the old value was minted from a
    # non-independent second arm (`n_diseases>=3 AND tier==strong`). n_diseases is the denominator
    # `paper_disease_mentions` was summed across (a component of the SAME europePMC read, the #1667 shape),
    # not an independent corroborating measurement — so literature is a one-armed axis capped at single_arm.
    assert ok["VOLUME"]["signal"] == "strong" and ok["VOLUME"]["corroboration"] == "single_arm"
    assert ok["RELATION"]["signal"] == "strong"
    # no_evidence → measured absent; data_unavailable → unmeasured; insufficient caps at weak
    assert lc_cv({"cited_evidence_status": "no_evidence"}, [])["VOLUME"]["signal"] == "absent"
    assert lc_cv({"cited_evidence_status": "data_unavailable"}, [])["VOLUME"]["signal"] == "unmeasured"
    assert (
        lc_cv({"cited_evidence_status": "insufficient", "paper_disease_mentions": 30}, [])["VOLUME"]["signal"] == "weak"
    )


def test_literature_question_table_and_key_signals():
    v = lc_cv(
        {
            "cited_evidence_status": "ok",
            "paper_disease_mentions": 30,
            "recent_mentions": 8,
            "n_diseases": 5,
            "total_relation_publications": 14,
            "relation_types": ["inhibit"],
        },
        [],
    )
    rows = lc_qt({"claim_vector": v})
    assert [r["id"] for r in rows] == ["Q1", "Q2", "Q3"]
    assert all(r["signal"]["polarity"] in ("informs", "none") for r in rows)  # descriptive, never supports/opposes
    assert lc_ks({"cited_evidence_status": "ok", "paper_disease_mentions": 30}, [])["headline"]
