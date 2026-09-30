"""Tests for the Tahoe transcriptional-resistance ADAPTATION sub-signal (verdict-inert).

tahoe_adaptation_for_target is pure over an injected DataFrame. Validates: a resistance program is
flagged INDUCED when its genes clear the induction floor (the MEK-inhibitor HMOX1/NQO1/ABCB1 pattern
from the live check), an unmapped target returns not_in_tahoe, and the sub-signal is verdict-inert
(it never appears in the primary resistance class).
"""

from __future__ import annotations

import pandas as pd

from onc_methods.resistance_emergence import tahoe_adaptation as TA


def _df(rows):
    return pd.DataFrame(rows, columns=["gene_name", "drug", "log2FoldChange", "padj", "Cell_ID_DepMap"])


def _induced_rows():
    rows = []
    # HMOX1 + NQO1 (oxidative_stress) and ABCB1 (efflux) INDUCED under Trametinib; MCL1 DOWN (efficacy)
    for i in range(5):
        rows.append(["HMOX1", "Trametinib", 1.1, 1e-5, f"ACH-{i:06d}"])
        rows.append(["NQO1", "Trametinib", 0.7, 1e-4, f"ACH-{i:06d}"])
        rows.append(["ABCB1", "Trametinib", 0.9, 1e-3, f"ACH-{i:06d}"])
        rows.append(["MCL1", "Trametinib", -0.8, 1e-6, f"ACH-{i:06d}"])
    return rows


def test_unmapped_target_is_not_in_tahoe():
    out = TA.tahoe_adaptation_for_target("EGFR")  # not in TARGET_TO_TAHOE_DRUGS
    assert out["tahoe_adaptation_class"] == "not_in_tahoe"
    assert out["induced_programs"] == []


def test_data_unavailable_on_fetch_failure(monkeypatch):
    """A read failure in _fetch_program_rows (returns None) → data_unavailable + breadcrumb."""
    monkeypatch.setattr(TA, "_fetch_program_rows", lambda drugs: None)
    out = TA.tahoe_adaptation_for_target("KRAS")  # mapped target, but fetch fails
    assert out["tahoe_adaptation_class"] == "data_unavailable"
    assert out["_live_read_error"] == "tahoe_adaptation_read_failed"


def test_induced_programs_detected():
    out = TA.tahoe_adaptation_for_target("KRAS", df=_df(_induced_rows()))
    assert out["tahoe_adaptation_class"] == "induced_resistance_programs"
    progs = {p["program"] for p in out["induced_programs"]}
    assert "oxidative_stress" in progs
    assert "efflux" in progs
    # MCL1 (anti_apoptotic) went DOWN → NOT flagged as induced (drug working, not resistance)
    assert "anti_apoptotic" not in progs
    # ordered by max_induction desc; oxidative_stress (HMOX1 +1.1) should lead
    assert out["induced_programs"][0]["program"] == "oxidative_stress"


def test_no_induced_when_all_suppressed():
    rows = [["MCL1", "Trametinib", -0.8, 1e-6, f"ACH-{i:06d}"] for i in range(5)]
    out = TA.tahoe_adaptation_for_target("KRAS", df=_df(rows))
    assert out["tahoe_adaptation_class"] == "no_induced_programs"
    assert out["induced_programs"] == []


def test_verdict_inert_integration(monkeypatch):
    """The Tahoe sub-signal attaches as facet fields but the PRIMARY resistance class is unchanged."""
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    from onc_methods.resistance_emergence import read as R

    class _T:
        def __init__(self, rows):
            self._rows = rows

        @property
        def num_rows(self):
            return len(self._rows)

        def to_pylist(self):
            return self._rows

    monkeypatch.setattr(fs, "S3FileSystem", lambda *a, **k: None)
    R._ROWS_CACHE.clear()
    good = [
        {
            "inhibited_target": "KRAS",
            "rescuer_gene": "NF1",
            "anchor_drug": "MRTX1133",
            "mechanism": "KRAS-G12D inhibitor",
            "n_models": 5,
            "mean_effect_shift": 0.84,
            "max_effect_shift": 0.9,
            "n_models_significant": 5,
            "frac_models_significant": 1.0,
            "resistance_class": "robust_resistance_mediator",
        }
    ]
    monkeypatch.setattr(pq, "read_table", lambda *a, **k: _T(good))
    # force the Tahoe sub-signal to a known value (avoid live S3)
    monkeypatch.setattr(
        TA,
        "tahoe_adaptation_for_target",
        lambda sym: {
            "tahoe_adaptation_class": "induced_resistance_programs",
            "induced_programs": [{"program": "efflux", "max_induction": 0.9}],
            "tahoe_adaptation_note": "test",
        },
    )
    out = R.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=True)
    # primary class from DepMap genetic rescue — UNCHANGED by the Tahoe sub-signal
    assert out["resistance_emergence_class"] == "strong_resistance_signal"
    assert out["strongest_mediator"] == "NF1"
    # Tahoe sub-signal present as inert facet fields
    assert out["tahoe_adaptation_class"] == "induced_resistance_programs"
    assert out["tahoe_induced_programs"][0]["program"] == "efflux"
    R._ROWS_CACHE.clear()
