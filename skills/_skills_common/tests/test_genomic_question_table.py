"""Genomic per-alteration-class question-table hero — deterministic projection over a synthetic
headline.genomic_alteration_by_class. Verdict-inert; no I/O.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # skills/ for _skills_common

from _skills_common.genomic_question_table import genomic_question_table
from _skills_common.presence_question_table import render_question_table_html


def _headline():
    return {
        "genomic_alteration_profile": "recurrent_snv_driver",
        "genomic_alteration_by_class": {
            "snv_indel": {
                "verdict": "recurrent_snv_driver",
                "evidence_state": "measured",
                "recurrence_class": "top_1pct",
                "stratified_dependency_class": "biomarker_stratified_dependency",
            },
            "copy_number": {"verdict": "neutral_cn", "evidence_state": "measured"},
            "fusion": {"verdict": "data_unavailable", "evidence_state": "data_unavailable"},
        },
    }


def test_rows_one_per_class_in_order():
    rows = genomic_question_table(_headline())
    assert [r["id"] for r in rows] == ["SNV", "CN", "Fusion", "Splice"]


def test_signal_tiers_by_class():
    rows = {r["id"]: r for r in genomic_question_table(_headline())}
    # recurrent driver → strong (positive keyword); measured + biomarker strat → high confidence
    assert rows["SNV"]["signal"]["tier"] == "strong"
    assert rows["SNV"]["confidence"]["tier"] == "high"
    # neutral_cn measured → absent (measured-negative)
    assert rows["CN"]["signal"]["tier"] == "absent"
    assert rows["CN"]["confidence"]["tier"] == "moderate"
    # fusion data_unavailable → unmeasured (a NAMED gap, never a fabricated negative)
    assert rows["Fusion"]["signal"]["tier"] == "unmeasured"
    assert rows["Fusion"]["confidence"]["tier"] == "unmeasured"


def test_fusion_confound_surfaces_on_row_support():
    """#1765: an `alteration_confounded` fusion arm surfaces in the Fusion row's support string."""
    h = {
        "genomic_alteration_by_class": {
            "fusion": {
                "verdict": "recurrent_fusion_driver",
                "evidence_state": "measured",
                "stratified_dependency_class": "fusion_positive_strongly_dependent",
                "stratified_dependency_confound": "alteration_confounded",
            },
        },
    }
    rows = {r["id"]: r for r in genomic_question_table(h)}
    assert "stratified dependency confound: alteration_confounded" in rows["Fusion"]["support"]


def test_fusion_confound_absent_is_byte_stable():
    """Without the confound field (data_unavailable / missing) the support string is unchanged."""
    base = {
        "verdict": "recurrent_fusion_driver",
        "evidence_state": "measured",
        "stratified_dependency_class": "fusion_positive_strongly_dependent",
    }
    without = genomic_question_table({"genomic_alteration_by_class": {"fusion": dict(base)}})
    unavail = genomic_question_table(
        {"genomic_alteration_by_class": {"fusion": {**base, "stratified_dependency_confound": "data_unavailable"}}}
    )
    fusion_support = lambda rows: next(r for r in rows if r["id"] == "Fusion")["support"]
    assert "confound" not in fusion_support(without)
    assert fusion_support(without) == fusion_support(unavail)


def test_absent_by_class_yields_full_unmeasured_ladder():
    rows = genomic_question_table({})  # no by_class at all
    assert [r["id"] for r in rows] == ["SNV", "CN", "Fusion", "Splice"]
    assert all(r["signal"]["tier"] == "unmeasured" for r in rows)


def _headline_with_recurrence(mc3="top_1pct", genie="top_decile", pooled=None):
    """A headline whose claim_vector carries a resolved recurrence_concordance claim, built via the REAL
    builder (mirrors run.py, which sets headline['claim_vector'] before building the question_table)."""
    from _skills_common.genomic_claims import genomic_claim_vector

    h = dict(
        _headline(),
        driver_recurrence_class=mc3,
        genie_driver_recurrence_class=genie,
        pooled_driver_recurrence_class=pooled,
    )
    h["claim_vector"] = genomic_claim_vector(h, [])
    return h


def test_integrated_signal_attached_to_snv_row_when_claim_resolves():
    # SK#1750: the recurrence_concordance claim reaches the SNV answer row as an additive integrated_signal.
    rows = {r["id"]: r for r in genomic_question_table(_headline_with_recurrence())}
    isig = rows["SNV"].get("integrated_signal")
    assert isig is not None and isig["kind"] == "recurrence_concordance"
    assert isig["concordance_class"] == "recurrence_concordant"
    assert isig["corroboration"] == "high"
    assert isig["provenance_ref"] == "claim_vector.recurrence_concordance"
    assert isig["qualifying_signal"] is None  # concordant → no caveat
    assert isig["positive_signal"] and "statement" in isig["positive_signal"]
    # NO other class row carries the annotation (it is the SNV / driver-recurrence question)
    assert all("integrated_signal" not in rows[k] for k in ("CN", "Fusion", "Splice"))
    # verdict-inert: the SNV meter cells are UNCHANGED by the annotation
    assert rows["SNV"]["signal"]["tier"] == "strong" and rows["SNV"]["confidence"]["tier"] == "high"


def test_row_byte_stable_when_claim_absent():
    # No recurrence fields → claim omitted → NO integrated_signal key (row byte-stable vs the bare table).
    bare = {r["id"]: r for r in genomic_question_table(_headline())}
    assert "integrated_signal" not in bare["SNV"]
    # a claim_vector present but WITHOUT recurrence_concordance also leaves the row untouched
    h = dict(_headline(), claim_vector={})
    assert "integrated_signal" not in {r["id"]: r for r in genomic_question_table(h)}["SNV"]


def test_integrated_signal_mutation_degrade_and_omit():
    # Defeat ONE arm → degrades to the single-source qualifying signal (still surfaced, with a caveat).
    one = {r["id"]: r for r in genomic_question_table(_headline_with_recurrence(genie="data_unavailable"))}
    isig = one["SNV"]["integrated_signal"]
    assert isig["concordance_class"] == "single_source_only"
    assert isig["qualifying_signal"] is not None  # names the gap arm
    assert isig["boundary_sensitive"] is True
    # Defeat BOTH arms (pooled still present) → claim omitted → key gone; pooled never resurrects it.
    both = {
        r["id"]: r
        for r in genomic_question_table(
            _headline_with_recurrence(mc3="data_unavailable", genie="data_unavailable", pooled="top_1pct")
        )
    }
    assert "integrated_signal" not in both["SNV"]


def test_renders_html_via_shared_renderer():
    html = render_question_table_html(
        genomic_question_table(_headline()), verdict="recurrent_snv_driver", title="Genomic alteration"
    )
    assert "<table" in html and "Genomic alteration at a glance" in html and "recurrent_snv_driver" in html
