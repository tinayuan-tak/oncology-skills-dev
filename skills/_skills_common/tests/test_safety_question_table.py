"""On-target-safety question-table hero — deterministic projection over a synthetic
on-target-safety-liability headline. Verdict-inert; no I/O. Polarity is INVERTED: strong = LoF-tolerant
(safe), absent = a liability."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # skills/ for _skills_common

from _skills_common.safety_question_table import safety_question_table
from _skills_common.presence_question_table import render_question_table_html


def _safe_headline():
    # a LoF-tolerant (safe) target on every leg → all strong
    return {
        "safety_verdict": "lof_tolerant_low_concern",
        "constraint_class": "tolerant",
        "burden_safety_class": "no_burden_signal",
        "dosage_sensitivity_class": "dosage_sufficient",
        "mouse_ko_phenotype_class": "no_phenotype",
        "clinvar_pathogenic_class": "no_pathogenic_signal",
    }


def _liability_headline():
    # a constrained / essential target → the legs read as liabilities (absent = concern)
    return {
        "safety_verdict": "lof_intolerant_high_concern",
        "constraint_class": "highly_constrained",
        "burden_safety_class": "lof_risk_phenotype",
        "dosage_sensitivity_class": "autosomal_dominant_loss",
        "mouse_ko_phenotype_class": "lethal_ko",
        "clinvar_pathogenic_class": "germline_pathogenic",
    }


def test_rows_in_order():
    rows = safety_question_table(_safe_headline())
    assert [r["id"] for r in rows] == ["Constraint", "Burden", "Dosage", "Mouse-KO", "ClinVar"]


def test_safe_target_all_strong():
    rows = safety_question_table(_safe_headline())
    assert all(r["signal"]["tier"] == "strong" for r in rows)


def test_liability_target_all_absent():
    rows = safety_question_table(_liability_headline())
    # inverted polarity: a liability on every leg → absent (a concern), NOT strong
    assert all(r["signal"]["tier"] == "absent" for r in rows)


def test_indeterminate_and_missing_are_unmeasured():
    h = {"constraint_class": "indeterminate", "burden_safety_class": "insufficient"}  # rest missing
    rows = {r["id"]: r for r in safety_question_table(h)}
    assert rows["Constraint"]["signal"]["tier"] == "unmeasured"
    assert rows["Burden"]["signal"]["tier"] == "unmeasured"
    assert rows["ClinVar"]["signal"]["tier"] == "unmeasured"  # missing field → named gap


def test_renders_html_via_shared_renderer():
    html = render_question_table_html(
        safety_question_table(_safe_headline()), verdict="lof_tolerant_low_concern", title="On-target safety"
    )
    assert "<table" in html and "On-target safety at a glance" in html
