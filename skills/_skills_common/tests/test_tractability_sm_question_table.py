"""Small-molecule tractability question-table hero — deterministic projection over a synthetic
tractability-small-molecule headline. Verdict-inert; no I/O."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # skills/ for _skills_common

from _skills_common.presence_question_table import render_question_table_html
from _skills_common.tractability_sm_question_table import tractability_sm_question_table


def _headline():
    return {
        "druggability_snapshot": "chemically_active_concordant",
        "prism_activity_class": "clinically_active",  # active compound → strong
        "prism_crispr_concord": "triangulated_target_engaged",  # engaged → strong
        "pdb_coverage_class": "partial",  # partial structure → moderate
        "known_drug_tractability": "approved_drug_tractable",  # approved → strong
    }


def test_rows_in_order():
    rows = tractability_sm_question_table(_headline())
    assert [r["id"] for r in rows] == ["Compound", "Concordance", "Structure", "Known-drug"]


def test_signal_tiers():
    rows = {r["id"]: r for r in tractability_sm_question_table(_headline())}
    assert rows["Compound"]["signal"]["tier"] == "strong"
    assert rows["Concordance"]["signal"]["tier"] == "strong"
    assert rows["Structure"]["signal"]["tier"] == "moderate"  # partial
    assert rows["Known-drug"]["signal"]["tier"] == "strong"


def test_negative_and_gap():
    h = {
        "prism_activity_class": "no_compounds_found",
        "prism_crispr_concord": "discordant_off_target_likely",
        "pdb_coverage_class": "none",
    }  # known_drug field absent → named gap
    rows = {r["id"]: r for r in tractability_sm_question_table(h)}
    assert rows["Compound"]["signal"]["tier"] == "absent"  # no compound
    assert rows["Concordance"]["signal"]["tier"] == "absent"  # discordant → off-target
    assert rows["Structure"]["signal"]["tier"] == "absent"  # none
    assert rows["Known-drug"]["signal"]["tier"] == "unmeasured"  # absent field


def test_renders_html_via_shared_renderer():
    html = render_question_table_html(
        tractability_sm_question_table(_headline()),
        verdict="chemically_active_concordant",
        title="Small-molecule tractability",
    )
    assert "<table" in html and "Small-molecule tractability at a glance" in html
