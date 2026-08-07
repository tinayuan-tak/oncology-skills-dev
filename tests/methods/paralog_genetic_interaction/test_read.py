"""paralog_genetic_interaction.read — hermetic tests (injected summary rows, no S3).

Pins the combinatorial_dependency_class precedence (constitutive > context > suppressive >
no_interaction), the coverage-gap default (absent -> no_paralog_screened, NOT interaction-negative),
the data_unavailable-vs-no_paralog distinction, and partner ranking by mean_gi.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.paralog_genetic_interaction.read import (  # noqa: E402
    combinatorial_dependency_for_gene,
)


def _pair(partner, mean_gi, iclass, **kw):
    base = {
        "target_gene": "GENEA", "partner_gene": partner, "pair_id": f"GENEA_{partner}",
        "n_lines": 278, "mean_gi": mean_gi, "median_gi": mean_gi,
        "gi_ttest_pvalue": 1e-10, "frac_lines_strong_gi": 0.2, "min_gi": mean_gi - 0.8,
        "min_gi_model_id": "ACH-000001", "min_gi_lineage": "Lung",
        "n_lineages_strong": 3, "interaction_class": iclass,
    }
    base.update(kw)
    return base


def test_constitutive_wins_precedence():
    rows = (
        _pair("P1", -0.10, "context_buffering"),
        _pair("P2", -0.60, "constitutive_buffering"),
        _pair("P3", 0.30, "suppressive"),
    )
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "strong_synthetic_lethal"
    # strongest partner = most-negative mean_gi
    assert r["strongest_partner"] == "P2"
    assert r["n_interacting_partners"] == 3


def test_context_when_no_constitutive():
    rows = (_pair("P1", -0.15, "context_buffering"), _pair("P2", -0.05, "no_interaction"))
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "context_synthetic_lethal"
    assert r["strongest_partner"] == "P1"


def test_suppressive_when_only_positive():
    rows = (_pair("P1", 0.40, "suppressive"), _pair("P2", 0.05, "no_interaction"))
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "suppressive_interaction"


def test_no_interaction_when_all_neutral():
    rows = (_pair("P1", -0.05, "no_interaction"), _pair("P2", 0.02, "no_interaction"))
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    assert r["combinatorial_dependency_class"] == "no_interaction"
    assert r["n_interacting_partners"] == 0


def test_absent_gene_is_coverage_gap_not_negative():
    # empty tuple = gene not in the paralog library
    r = combinatorial_dependency_for_gene("NOTINLIB", summary_rows=tuple())
    assert r["combinatorial_dependency_class"] == "no_paralog_screened"
    assert "coverage gap" in r["combinatorial_context"]


def test_read_failure_is_data_unavailable_not_negative():
    # None = read/S3 failure (distinct from empty = screened-but-absent)
    r = combinatorial_dependency_for_gene("SOMEGENE", summary_rows=None)
    assert r["combinatorial_dependency_class"] == "data_unavailable"


def test_partner_ranking_ascending_by_mean_gi():
    rows = (
        _pair("HI", -0.10, "context_buffering"),
        _pair("LO", -0.70, "constitutive_buffering"),
        _pair("MID", -0.40, "constitutive_buffering"),
    )
    r = combinatorial_dependency_for_gene("GENEA", summary_rows=rows)
    order = [p["partner_gene"] for p in r["top_partners"]]
    assert order == ["LO", "MID", "HI"]
