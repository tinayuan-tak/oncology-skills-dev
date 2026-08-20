"""Unit tests for pair_selectivity_gate.derive_batch — the amortized bulk pair-selectivity compute.
Pure (synthetic in-memory cubes; no S3)."""
from __future__ import annotations

import sys
from pathlib import Path

# analysis-methods repo root on path (methods/ is a top-level package dir)
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from methods.pair_selectivity_gate.derive_batch import (  # noqa: E402
    derive_bulk_pair_selectivity, best_partner_rollup)

I2S = {"COADREAD": ["COAD"]}


def _cube(spec):
    """spec: {gene: {group: {sample_id: tpm}}} passthrough helper."""
    return spec


def test_and_gate_tumor_selective():
    # A + B both HIGH in COAD tumor (co-positive), both LOW in essential normal (COLON is not essential;
    # use LIVER essential low) → AND gate selective.
    tumor = _cube({
        "A": {"COAD": {"s1": 50.0, "s2": 60.0, "s3": 40.0}},
        "B": {"COAD": {"s1": 30.0, "s2": 45.0, "s3": 20.0}},
    })
    normal = _cube({
        "A": {"LIVER": {"n1": 1.0, "n2": 0.5}},
        "B": {"LIVER": {"n1": 0.2, "n2": 0.1}},
    })
    rows = derive_bulk_pair_selectivity(tumor, normal, "COADREAD", I2S, ["A"], ["B"], gates=("AND",))
    assert len(rows) == 1
    r = rows[0]
    assert r["target"] == "A" and r["partner"] == "B" and r["gate"] == "AND"
    assert r["tumor_fraction"] == 1.0            # all 3 tumor samples co-positive
    assert r["max_essential_normal_fraction"] == 0.0
    assert r["selectivity"] and r["selectivity"] >= 50   # 1.0 / floor(0.01) capped ~100x
    assert "tumor-selective" in r["call"]


def test_and_coverage_gate_zeroes_rare_pairs():
    # co-positive in only 1/5 tumor samples (< AND_GATE_MIN_COFRACTION 0.30) → selectivity 0
    tumor = _cube({
        "A": {"COAD": {f"s{i}": (50.0 if i == 0 else 1.0) for i in range(5)}},
        "B": {"COAD": {f"s{i}": (50.0 if i == 0 else 1.0) for i in range(5)}},
    })
    rows = derive_bulk_pair_selectivity(tumor, {}, "COADREAD", I2S, ["A"], ["B"], gates=("AND",))
    assert rows[0]["tumor_fraction"] == 0.2
    assert rows[0]["selectivity"] == 0.0
    assert "low value" in rows[0]["call"]


def test_not_gate_is_directional():
    # NOT(A, B) = A present AND B truly absent. A high, B absent in tumor → NOT fires;
    # NOT(B, A) = B present AND A absent → B is high but A also high → does NOT fire (A present).
    tumor = _cube({
        "A": {"COAD": {"s1": 50.0, "s2": 50.0}},
        "B": {"COAD": {"s1": 1.0, "s2": 1.0}},     # B truly absent (< 5.0 veto)
    })
    rows = derive_bulk_pair_selectivity(tumor, {}, "COADREAD", I2S, ["A", "B"], ["A", "B"], gates=("NOT",))
    by = {(r["target"], r["partner"]): r for r in rows}
    assert by[("A", "B")]["tumor_fraction"] == 1.0   # A present, B absent everywhere
    assert by[("B", "A")]["tumor_fraction"] == 0.0   # B present but A present too → veto fails


def test_no_self_pairs_and_rollup():
    tumor = _cube({
        "A": {"COAD": {"s1": 50.0, "s2": 50.0}},
        "B": {"COAD": {"s1": 50.0, "s2": 50.0}},
        "C": {"COAD": {"s1": 1.0, "s2": 50.0}},
    })
    rows = derive_bulk_pair_selectivity(tumor, {}, "COADREAD", I2S, ["A"], ["A", "B", "C"], gates=("AND",))
    partners = {r["partner"] for r in rows}
    assert "A" not in partners and partners == {"B", "C"}   # no self-pair
    roll = best_partner_rollup(rows, "A", "COADREAD")
    assert roll["best_and_partner"] == "B"                  # B co-positive 2/2 beats C 1/2
    assert roll["n_partners_scanned"] == 2


def test_cube_from_frame_assembly():
    import pandas as pd
    from methods.pair_selectivity_gate.materialize import cube_from_frame, CLINICAL_SEED_ANTIGENS
    df = pd.DataFrame([
        {"gene_symbol": "EPCAM", "sample_id": "s1", "grp": "COAD", "tpm": 50.0},
        {"gene_symbol": "EPCAM", "sample_id": "s2", "grp": "COAD", "tpm": 40.0},
        {"gene_symbol": "CEACAM5", "sample_id": "s1", "grp": "COAD", "tpm": 30.0},
    ])
    cube = cube_from_frame(df)
    assert cube["EPCAM"]["COAD"] == {"s1": 50.0, "s2": 40.0}
    assert cube["CEACAM5"]["COAD"]["s1"] == 30.0
    # the seed universe is the fixed clinical set (bounded batch)
    assert "EPCAM" in CLINICAL_SEED_ANTIGENS and len(CLINICAL_SEED_ANTIGENS) == 20


def test_reader_data_unavailable_is_shaped_not_raised():
    from methods.pair_selectivity_gate import bulk_read
    # force the "not published" path deterministically
    bulk_read._DERIVED_STATUS = False
    out = bulk_read.read_target_bulk_pair_selectivity("EPCAM", "COADREAD")
    assert out["best_and_partner"] is None and out["n_partners_scanned"] == 0
    assert "unavailable" in out["_data_note"]
    assert out["_data_source"] == "bispecific-bulk-pair-selectivity-per-indication-v1"
    bulk_read._DERIVED_STATUS = None   # reset
