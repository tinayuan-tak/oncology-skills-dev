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


def test_absent_by_class_yields_full_unmeasured_ladder():
    rows = genomic_question_table({})  # no by_class at all
    assert [r["id"] for r in rows] == ["SNV", "CN", "Fusion", "Splice"]
    assert all(r["signal"]["tier"] == "unmeasured" for r in rows)


def test_renders_html_via_shared_renderer():
    html = render_question_table_html(
        genomic_question_table(_headline()), verdict="recurrent_snv_driver", title="Genomic alteration"
    )
    assert "<table" in html and "Genomic alteration at a glance" in html and "recurrent_snv_driver" in html
