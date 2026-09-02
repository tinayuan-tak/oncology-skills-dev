"""Regression: LUAD/LUSC (finer OncoTree codes) must resolve to the NSCLC patient-cohort partition.

The patient-cohort SNV products (MC3, GENIE, pooled) are materialised at the framework canonical grain
(indication_crosswalk.yaml): lung is pooled as NSCLC, so the products' `indication` column is `NSCLC`,
never `LUAD`. But DepMap-side reads accept `LUAD` directly, so a skill invoked with `indication="LUAD"`
reached these readers with a code that has no partition → the pushdown matched 0 rows → a spurious
`data_unavailable` (EGFR/LUAD looked un-mutated). These pin the LUAD/LUSC -> NSCLC canonicalization at the
cohort-read entry, before path resolution and the pushdown filter. Mirrors test_paad_canonical_key.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.indication_aliases import to_cohort_canonical  # noqa: E402
from methods.gdc_somatic_hotspot import read as R           # noqa: E402


def test_alias_maps_lung_subcodes_to_nsclc():
    assert to_cohort_canonical("LUAD") == "NSCLC"
    assert to_cohort_canonical("LUSC") == "NSCLC"


def test_alias_is_identity_for_canonical_and_unknown():
    for code in ("NSCLC", "COADREAD", "PAAD", "STAD", "SomethingElse", ""):
        assert to_cohort_canonical(code) == code


def test_read_hotspot_summary_pushes_down_nsclc_for_luad(monkeypatch):
    """read_hotspot_summary('EGFR', 'LUAD') must filter the MC3 product on indication == NSCLC."""
    captured = {}

    def _fake_read_product_table(aggregate_path, manifest, filters=None, columns=None):
        captured["filters"] = filters
        return None  # None -> caller returns the data_unavailable dict; no network

    # Avoid network/creds and the independent GENIE+pooled cohort reads (canonicalization for those is
    # covered by their own tests); this isolates the MC3 pushdown filter.
    monkeypatch.setattr(R, "_read_product_table", _fake_read_product_table)
    monkeypatch.setattr(R, "ensure_aws_profile", lambda: None)
    monkeypatch.setattr(R, "_genie_recurrence_fields", lambda target, indication: {})
    monkeypatch.setattr(R, "_pooled_recurrence_fields", lambda target, indication: {})

    R.read_hotspot_summary("EGFR", "LUAD")

    ind_filter = dict((col, val) for col, _op, val in captured["filters"])["indication"]
    assert ind_filter == "NSCLC", f"expected NSCLC pushdown for LUAD, got {ind_filter!r}"
