"""pair_selectivity_gate.samecell — avidity-call bands + order-insensitive pair match (no S3).

_read_cube is monkeypatched with a synthetic same-cell cube; the S3 read itself is live-smoked
separately. Pins the enrichment→avidity-call bands + cross-donor median + data_unavailable paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.pair_selectivity_gate import samecell as SC  # noqa: E402


def _cube(rows):
    """rows: list of (gene_a, gene_b, donor, both, enrichment)."""
    return pd.DataFrame(
        [
            {"gene_a": a, "gene_b": b, "donor_id": d, "both_fraction": both, "enrichment_vs_independence": enr}
            for (a, b, d, both, enr) in rows
        ]
    )


def _patch(monkeypatch, cube):
    monkeypatch.setattr(SC, "_read_cube", lambda manifest_id: cube)


def test_coordinated_call_above_band(monkeypatch):
    _patch(monkeypatch, _cube([("EPCAM", "CEACAM5", "d1", 0.5, 1.5), ("EPCAM", "CEACAM5", "d2", 0.4, 1.4)]))
    r = SC.confirm_pair_samecell("EPCAM", "CEACAM5", "COADREAD")
    assert r["samecell_avidity_call"] == "same_cell_coordinated"  # median enrichment 1.45 >= 1.2
    assert r["samecell_both_fraction_median"] == 0.45
    assert r["n_donors"] == 2


def test_independent_call_in_band(monkeypatch):
    _patch(monkeypatch, _cube([("A", "B", "d1", 0.5, 1.05), ("A", "B", "d2", 0.5, 0.95)]))
    assert SC.confirm_pair_samecell("A", "B", "COADREAD")["samecell_avidity_call"] == "same_cell_independent"


def test_mutual_exclusion_below_band(monkeypatch):
    _patch(monkeypatch, _cube([("A", "B", "d1", 0.02, 0.3), ("A", "B", "d2", 0.01, 0.2)]))
    assert SC.confirm_pair_samecell("A", "B", "COADREAD")["samecell_avidity_call"] == "same_cell_mutually_exclusive"


def test_pair_match_is_order_insensitive(monkeypatch):
    _patch(monkeypatch, _cube([("EPCAM", "CEACAM5", "d1", 0.5, 1.5)]))
    # querying B:A must find the A:B row
    r = SC.confirm_pair_samecell("CEACAM5", "EPCAM", "COADREAD")
    assert r["samecell_avidity_call"] == "same_cell_coordinated"
    assert r["n_donors"] == 1


def test_pair_absent_from_cube_is_data_unavailable(monkeypatch):
    _patch(monkeypatch, _cube([("EPCAM", "CEACAM5", "d1", 0.5, 1.5)]))
    r = SC.confirm_pair_samecell("EPCAM", "NOTINCUBE", "COADREAD")
    assert r["samecell_avidity_call"] == "data_unavailable"
    assert "not in the same-cell cube" in r["_data_note"]


def test_indication_without_cube_is_data_unavailable(monkeypatch):
    # SKCM has no entry in INDICATION_TO_SAMECELL_MANIFEST → data_unavailable before any read.
    # (Was BRCA, but breast now has a landed same-cell cube — sc-samecell-coexpr-brca-wu-v1.)
    r = SC.confirm_pair_samecell("EPCAM", "CEACAM5", "SKCM")
    assert r["samecell_avidity_call"] == "data_unavailable"
    assert "no same-cell coexpr cube" in r["_data_note"]


def test_unreadable_cube_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(SC, "_read_cube", lambda manifest_id: None)
    r = SC.confirm_pair_samecell("EPCAM", "CEACAM5", "COADREAD")
    assert r["samecell_avidity_call"] == "data_unavailable"


def test_enrichment_null_rows_dropped_from_median(monkeypatch):
    # a donor with NULL enrichment (marginal 0) must not poison the cross-donor median
    _patch(monkeypatch, _cube([("A", "B", "d1", 0.4, 1.5), ("A", "B", "d2", 0.0, None)]))
    r = SC.confirm_pair_samecell("A", "B", "COADREAD")
    assert r["samecell_enrichment_median"] == 1.5  # only the non-null donor counts toward enrichment


def test_saturated_high_copresence_is_not_mutually_exclusive(monkeypatch):
    # BP-1 / #357: a saturated high-co-presence pair (both_fraction ~0.60) with degenerate enrichment
    # <=0.8 must NOT be labelled mutually_exclusive (an OPPOSING bispecific signal) — 60% of malignant
    # cells co-express both = excellent avidity. It falls through to same_cell_independent.
    _patch(monkeypatch, _cube([("EPCAM", "CEACAM5", "d1", 0.60, 0.78), ("EPCAM", "CEACAM5", "d2", 0.62, 0.75)]))
    r = SC.confirm_pair_samecell("EPCAM", "CEACAM5", "COADREAD")
    assert r["samecell_avidity_call"] == "same_cell_independent"
    assert r["samecell_avidity_call"] != "same_cell_mutually_exclusive"


def test_low_copresence_low_enrichment_is_still_mutually_exclusive(monkeypatch):
    # the genuine exclusion case is preserved: LOW enrichment AND LOW absolute co-presence.
    _patch(monkeypatch, _cube([("A", "B", "d1", 0.03, 0.4), ("A", "B", "d2", 0.02, 0.3)]))
    assert SC.confirm_pair_samecell("A", "B", "COADREAD")["samecell_avidity_call"] == "same_cell_mutually_exclusive"


def test_n_donors_dedups_on_dataset_donor_grain(monkeypatch):
    # BP-6: cube grain is (dataset_id, donor_id, gene_a, gene_b). A donor recorded twice (here the
    # pair in both orientations for the same dataset+donor) must count as ONE donor, not two rows.
    df = pd.DataFrame(
        [
            {
                "gene_a": "A",
                "gene_b": "B",
                "dataset_id": "ds1",
                "donor_id": "d1",
                "both_fraction": 0.5,
                "enrichment_vs_independence": 1.4,
            },
            {
                "gene_a": "B",
                "gene_b": "A",
                "dataset_id": "ds1",
                "donor_id": "d1",  # dup (orientation flip)
                "both_fraction": 0.5,
                "enrichment_vs_independence": 1.4,
            },
            {
                "gene_a": "A",
                "gene_b": "B",
                "dataset_id": "ds2",
                "donor_id": "d2",
                "both_fraction": 0.5,
                "enrichment_vs_independence": 1.4,
            },
        ]
    )
    _patch(monkeypatch, df)
    r = SC.confirm_pair_samecell("A", "B", "COADREAD")
    assert r["n_donors"] == 2  # (ds1,d1) + (ds2,d2); NOT 3 rows
