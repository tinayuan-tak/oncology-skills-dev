"""dgidb_drug_gene.read — hermetic tests (injected DGIdb rows, no S3).

Pins the known_drug_tractability_class precedence (approved hoisted above clinically_actionable),
the coverage-gap default (absent -> no_known_drug_evidence, NOT undruggable), and field passthrough.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dgidb_drug_gene.read import known_drug_tractability_for_gene  # noqa: E402


def _row(**kw):
    base = {"druggability_tier": "category_only", "is_druggable_genome": False,
            "is_clinically_actionable": False, "has_approved_drug": False,
            "n_drug_interactions": 0, "n_approved_drug_interactions": 0,
            "n_antineoplastic_interactions": 0, "n_categories": 1, "gene_categories": "ENZYME"}
    base.update(kw)
    return base


def test_approved_drug_hoisted_above_clinical():
    # both flags true -> approved wins (the harder pharmacology fact)
    s = known_drug_tractability_for_gene("EGFR", dgidb_row=_row(
        has_approved_drug=True, is_clinically_actionable=True, is_druggable_genome=True,
        n_drug_interactions=549, n_approved_drug_interactions=200, n_antineoplastic_interactions=311,
        gene_categories="CLINICALLY ACTIONABLE|DRUGGABLE GENOME|KINASE"))
    assert s["known_drug_tractability_class"] == "approved_drug_tractable"
    assert s["n_approved_drug_interactions"] == 200
    assert s["has_approved_drug"] is True


def test_clinically_actionable_when_no_approved():
    s = known_drug_tractability_for_gene("KRAS", dgidb_row=_row(
        is_clinically_actionable=True, n_drug_interactions=165, n_antineoplastic_interactions=113))
    assert s["known_drug_tractability_class"] == "clinically_actionable"


def test_druggable_genome_only():
    s = known_drug_tractability_for_gene("CACNA2D4", dgidb_row=_row(
        is_druggable_genome=True, n_drug_interactions=3, gene_categories="DRUGGABLE GENOME|ION CHANNEL"))
    assert s["known_drug_tractability_class"] == "druggable_genome"


def test_interaction_only():
    s = known_drug_tractability_for_gene("X", dgidb_row=_row(n_drug_interactions=2, n_categories=0,
                                                             gene_categories=None))
    assert s["known_drug_tractability_class"] == "interaction_only"


def test_category_only():
    s = known_drug_tractability_for_gene("VPS4A", dgidb_row=_row())  # enzyme category, no drugs
    assert s["known_drug_tractability_class"] == "category_only"


def test_absent_is_coverage_gap_not_undruggable():
    s = known_drug_tractability_for_gene("NOTAGENE", dgidb_row=None)
    assert s["known_drug_tractability_class"] == "no_known_drug_evidence"
    assert s["has_approved_drug"] is False
    assert s["n_drug_interactions"] == 0
    assert "coverage gap" in s["known_drug_context"].lower()
