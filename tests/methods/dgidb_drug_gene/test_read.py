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

from methods.dgidb_drug_gene import read as dgidb  # noqa: E402
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


def test_absent_is_coverage_gap_not_undruggable(monkeypatch):
    # Simulate a gene GENUINELY absent from DGIdb (the reader returns None on a real 404 / empty
    # rollup). Must stay hermetic (no live S3): passing dgidb_row=None triggers a real _read_dgidb_row,
    # so we stub it to the genuine-absence sentinel. (Burndown P1: _read_dgidb_row now re-raises a
    # transient/creds failure instead of masking it as None, so a live read here would surface that.)
    monkeypatch.setattr(dgidb, "_read_dgidb_row", lambda *_a, **_k: None)
    monkeypatch.setattr(dgidb, "_read_directional_rows", lambda *_a, **_k: [])  # directness read stubbed absent
    s = known_drug_tractability_for_gene("NOTAGENE", dgidb_row=None)
    assert s["known_drug_tractability_class"] == "no_known_drug_evidence"
    assert s["has_approved_drug"] is False
    assert s["n_drug_interactions"] == 0
    assert "coverage gap" in s["known_drug_context"].lower()
    # directness: genuinely absent → 0 typed-direct, not_approved (no approved drug to gate)
    assert s["n_direct_interactions"] == 0
    assert s["direct_engagement_class"] == "indirect_or_untyped_only"
    assert s["approved_drug_engagement_class"] == "not_approved"


# ── DIRECTNESS metadata (2026-09-04) ─────────────────────────────────────────────────────────────────
def _dir_rows(*type_lists):
    """Build directional rows from interaction_types strings (one per drug)."""
    return [{"drug_name_norm": f"d{i}", "interaction_types": t} for i, t in enumerate(type_lists)]


def test_count_direct_only_typed_sm_interactions():
    # inhibitor/antagonist/binder count; antibody/vaccine/untyped do NOT
    rows = _dir_rows("inhibitor", "antagonist", "binder", "antibody|inhibitor", "antibody", "vaccine", "")
    assert dgidb._count_direct(rows) == 4          # 3 pure-direct + 1 antibody|inhibitor (has inhibitor)
    assert dgidb._count_direct([]) == 0
    assert dgidb._count_direct(None) is None        # unmeasured


def test_direct_engagement_threshold():
    assert dgidb._direct_engagement_class(5) == "direct_typed"
    assert dgidb._direct_engagement_class(10) == "direct_typed"
    assert dgidb._direct_engagement_class(4) == "sparse_direct"     # TP53-shape
    assert dgidb._direct_engagement_class(1) == "sparse_direct"     # CTNNB1-shape
    assert dgidb._direct_engagement_class(0) == "indirect_or_untyped_only"  # MYC-shape
    assert dgidb._direct_engagement_class(None) == "unmeasured"


def test_approved_engagement_class_gates_on_directness():
    # approved + direct → approved_direct (BRAF/KRAS/BTK/IDH1)
    assert dgidb._approved_drug_engagement_class(True, "direct_typed") == "approved_direct"
    # approved + sparse/indirect → approved_indirect_only (CTNNB1/MYC/TP53 — the inflation)
    assert dgidb._approved_drug_engagement_class(True, "sparse_direct") == "approved_indirect_only"
    assert dgidb._approved_drug_engagement_class(True, "indirect_or_untyped_only") == "approved_indirect_only"
    # UNMEASURED directness must NOT demote (fail toward prior behaviour)
    assert dgidb._approved_drug_engagement_class(True, "unmeasured") == "approved_direct"
    # non-approved genes → not_approved regardless
    assert dgidb._approved_drug_engagement_class(False, "direct_typed") == "not_approved"


def test_ctnnb1_shape_approved_but_indirect():
    # CTNNB1: approved drug catalogued, but only 1 typed-direct interaction (pri-724, itself indirect)
    s = known_drug_tractability_for_gene(
        "CTNNB1", dgidb_row=_row(has_approved_drug=True, n_approved_drug_interactions=17,
                                 n_drug_interactions=50, n_antineoplastic_interactions=27),
        directional_rows=_dir_rows("inhibitor"))
    assert s["known_drug_tractability_class"] == "approved_drug_tractable"   # UNCHANGED (Design B2)
    assert s["n_direct_interactions"] == 1
    assert s["approved_drug_engagement_class"] == "approved_indirect_only"
    assert "indirect" in s["directness_context"].lower()


def test_braf_shape_approved_direct():
    s = known_drug_tractability_for_gene(
        "BRAF", dgidb_row=_row(has_approved_drug=True, n_approved_drug_interactions=194,
                               n_drug_interactions=424),
        directional_rows=_dir_rows(*(["inhibitor"] * 44)))
    assert s["n_direct_interactions"] == 44
    assert s["approved_drug_engagement_class"] == "approved_direct"
