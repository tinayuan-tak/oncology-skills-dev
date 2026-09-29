"""Tests for the target-centric same-cell avidity reader (card-facing). No S3: _read_cube is
monkeypatched with a synthetic per-(donor,pair) cube."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

pd = pytest.importorskip("pandas")

from methods.pair_selectivity_gate import cli as C  # noqa: E402
from methods.pair_selectivity_gate import normal as N  # noqa: E402
from methods.pair_selectivity_gate import samecell as S  # noqa: E402


def _normal_cube_clean():
    # EPCAM:CEACAM5 in ONE well-powered (tissue, cell_type) group: 3 donors x 100 cells, ~0 co-expr
    # -> passes the >=3-donor/>=10-cell support floor, normal_max_both ~0 -> selectivity_clean.
    rows = [
        {
            "gene_a": "CEACAM5",
            "gene_b": "EPCAM",
            "tissue": "colon",
            "cell_type": "enterocyte",
            "dataset_id": "nd",
            "donor_id": d,
            "n_cells": 100,
            "both_fraction": 0.0,
            "enrichment_vs_independence": None,
        }
        for d in ("n1", "n2", "n3")
    ]
    return pd.DataFrame(rows)


def _cube():
    # EPCAM pairs: CEACAM5 coordinated (enr>1.2), ERBB2 mutually exclusive (enr<0.8), 3 donors each
    # (>= window.MIN_TUMOR_DONORS so the tumor axis clears the BP-2 donor floor).
    rows = []
    for d in ("d1", "d2", "d3"):
        rows += [
            {
                "gene_a": "EPCAM",
                "gene_b": "CEACAM5",
                "both_fraction": 0.55,
                "enrichment_vs_independence": 1.6,
                "dataset_id": "ds",
                "donor_id": d,
            },
            {
                "gene_a": "ERBB2",
                "gene_b": "EPCAM",
                "both_fraction": 0.05,  # order-flipped on purpose
                "enrichment_vs_independence": 0.5,
                "dataset_id": "ds",
                "donor_id": d,
            },
        ]
    return pd.DataFrame(rows)


def test_best_partner_is_coordinated(monkeypatch):
    monkeypatch.setattr(S, "_read_cube", lambda m: _cube())
    r = S.read_target_samecell_avidity("EPCAM", "COADREAD")
    assert r["samecell_avidity_class"] == "same_cell_coordinated"
    assert r["best_partner"] == "CEACAM5"
    assert r["best_enrichment_median"] == 1.6
    assert r["n_partners_tested"] == 2
    assert r["n_coordinated_partners"] == 1
    # order-insensitive: ERBB2 (as gene_a) is still found as a partner of EPCAM, and is exclusive
    erbb2 = next(p for p in r["partners"] if p["partner"] == "ERBB2")
    assert erbb2["avidity_call"] == "same_cell_mutually_exclusive"


def test_indication_without_cube_is_data_unavailable(monkeypatch):
    r = S.read_target_samecell_avidity("EPCAM", "GBM")  # not in INDICATION_TO_SAMECELL_MANIFEST
    assert r["samecell_avidity_class"] == "data_unavailable"
    assert "no same-cell coexpr cube" in r["_data_note"]


def test_cube_unreadable_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(S, "_read_cube", lambda m: None)
    r = S.read_target_samecell_avidity("EPCAM", "COADREAD")
    assert r["samecell_avidity_class"] == "data_unavailable"


def test_target_absent_from_all_pairs(monkeypatch):
    monkeypatch.setattr(S, "_read_cube", lambda m: _cube())
    r = S.read_target_samecell_avidity("KRAS", "COADREAD")  # not in any pair
    assert r["samecell_avidity_class"] == "data_unavailable"
    assert "not in any nominated pair" in r["_data_note"]


def test_cli_build_summary_stamps_version(monkeypatch):
    monkeypatch.setattr(S, "_read_cube", lambda m: _cube())
    monkeypatch.setattr(N, "_read_normal_cube", lambda m=None: _normal_cube_clean())
    s = C.build_summary("EPCAM", "COADREAD")
    assert s["method_version"] == C.METHOD_VERSION
    assert s["samecell_avidity_class"] == "same_cell_coordinated"


def test_cli_build_summary_surfaces_selectivity_window(monkeypatch):
    # Tumor: EPCAM:CEACAM5 coordinated at both=0.55 (>=TAU). Normal: CEACAM5:EPCAM ~0 in a
    # well-powered colon enterocyte group -> selectivity_clean. Combined -> window_open.
    monkeypatch.setattr(S, "_read_cube", lambda m: _cube())
    monkeypatch.setattr(N, "_read_normal_cube", lambda m=None: _normal_cube_clean())
    s = C.build_summary("EPCAM", "COADREAD")
    # the tumor-avidity fields the existing rules read are untouched
    assert s["samecell_avidity_class"] == "same_cell_coordinated"
    assert s["best_partner"] == "CEACAM5"
    # the NEW selectivity-window fields (the previously-orphaned normal gate, now wired)
    assert s["window_verdict"] == "window_open"
    assert s["window_best_partner"] == "CEACAM5"
    assert s["selectivity_margin"] == 0.55  # tumor_both 0.55 - normal_max_both 0.0
    assert s["n_window_open"] == 1
    assert s["_window"]["_evidence_tier"] == "single_cell_measured"


def test_cli_build_summary_no_window_on_normal_liability(monkeypatch):
    # Same tumor coordination, but the normal cube now shows CEACAM5:EPCAM co-expressed on a
    # well-powered normal cell type -> normal_liability -> no_window (the SAFETY negative the
    # tumor-only avidity class cannot express).
    def _liable(m=None):
        rows = [
            {
                "gene_a": "CEACAM5",
                "gene_b": "EPCAM",
                "tissue": "colon",
                "cell_type": "enterocyte",
                "dataset_id": "nd",
                "donor_id": d,
                "n_cells": 100,
                "both_fraction": 0.40,
                "enrichment_vs_independence": 1.5,
            }
            for d in ("n1", "n2", "n3")
        ]
        return pd.DataFrame(rows)

    monkeypatch.setattr(S, "_read_cube", lambda m: _cube())
    monkeypatch.setattr(N, "_read_normal_cube", _liable)
    s = C.build_summary("EPCAM", "COADREAD")
    assert s["samecell_avidity_class"] == "same_cell_coordinated"  # tumor axis still coordinated
    assert s["window_verdict"] == "no_window"  # but normal liability closes it
    assert s["normal_liability_locus"]["tissue"] == "colon"
