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

from methods.pair_selectivity_gate import samecell as S  # noqa: E402
from methods.pair_selectivity_gate import cli as C  # noqa: E402


def _cube():
    # EPCAM pairs: CEACAM5 coordinated (enr>1.2), ERBB2 mutually exclusive (enr<0.8), 2 donors each.
    rows = []
    for d in ("d1", "d2"):
        rows += [
            {"gene_a": "EPCAM", "gene_b": "CEACAM5", "both_fraction": 0.55,
             "enrichment_vs_independence": 1.6, "dataset_id": "ds", "donor_id": d},
            {"gene_a": "ERBB2", "gene_b": "EPCAM", "both_fraction": 0.05,   # order-flipped on purpose
             "enrichment_vs_independence": 0.5, "dataset_id": "ds", "donor_id": d},
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
    r = S.read_target_samecell_avidity("EPCAM", "GBM")   # not in INDICATION_TO_SAMECELL_MANIFEST
    assert r["samecell_avidity_class"] == "data_unavailable"
    assert "no same-cell coexpr cube" in r["_data_note"]


def test_cube_unreadable_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(S, "_read_cube", lambda m: None)
    r = S.read_target_samecell_avidity("EPCAM", "COADREAD")
    assert r["samecell_avidity_class"] == "data_unavailable"


def test_target_absent_from_all_pairs(monkeypatch):
    monkeypatch.setattr(S, "_read_cube", lambda m: _cube())
    r = S.read_target_samecell_avidity("KRAS", "COADREAD")   # not in any pair
    assert r["samecell_avidity_class"] == "data_unavailable"
    assert "not in any nominated pair" in r["_data_note"]


def test_cli_build_summary_stamps_version(monkeypatch):
    monkeypatch.setattr(S, "_read_cube", lambda m: _cube())
    s = C.build_summary("EPCAM", "COADREAD")
    assert s["method_version"] == C.METHOD_VERSION
    assert s["samecell_avidity_class"] == "same_cell_coordinated"
