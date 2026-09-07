"""Synthetic-lethal-partners compact question-table hero — deterministic projection over a synthetic
headline. Verdict-inert; no I/O."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # skills/ for _skills_common

from _skills_common.sl_question_table import sl_question_table
from _skills_common.presence_question_table import render_question_table_html


def test_experimental_partner_strong():
    rows = {
        r["id"]: r
        for r in sl_question_table(
            {
                "sl_partner_verdict": "experimental_sl_partner",
                "sl_partner_class": "has_experimental_sl_partner",
                "sl_partner_count": 12,
                "n_experimental_partners": 3,
                "best_evidence_tier": "experimental",
            }
        )
    }
    assert [k for k in ("Partner", "Support")] == ["Partner", "Support"]
    assert rows["Partner"]["signal"]["tier"] == "strong"
    assert rows["Support"]["signal"]["tier"] == "strong"


def test_computational_only_is_weaker():
    rows = {
        r["id"]: r
        for r in sl_question_table(
            {
                "sl_partner_class": "has_computational_sl_partner",
                "sl_partner_count": 4,
                "best_evidence_tier": "computational",
            }
        )
    }
    assert rows["Partner"]["signal"]["tier"] == "moderate"
    assert rows["Support"]["signal"]["tier"] == "weak"


def test_no_partner_support_row_unmeasured():
    rows = {r["id"]: r for r in sl_question_table({"sl_partner_class": "no_curated_sl_partner"})}
    assert rows["Partner"]["signal"]["tier"] == "absent"
    # nothing to support when there is no partner → Support is a named gap, not a fabricated negative
    assert rows["Support"]["signal"]["tier"] == "unmeasured"


def test_renders_html():
    html = render_question_table_html(
        sl_question_table({"sl_partner_class": "has_experimental_sl_partner", "best_evidence_tier": "experimental"}),
        verdict="experimental_sl_partner",
        title="Synthetic-lethal partners",
    )
    assert "<table" in html and "Synthetic-lethal partners at a glance" in html
