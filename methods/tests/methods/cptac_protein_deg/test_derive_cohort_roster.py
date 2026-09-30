"""sweep2 Fix 3: cptac_protein_deg.derive.stage_02 must require EVERY requested cohort to succeed.

Before this, stage_02 only raised at n_ok < 3, so 3-9 of 10 cohorts could fail silently and still
ship a product with no record of which cohorts are present. The gate now trips unless n_ok ==
len(cohorts), naming the failed cohorts. stage_02_cohort (the subprocess runner) is stubbed so the
test needs no R / MSstatsTMT / S3.
"""

from __future__ import annotations

import importlib

import pytest

derive = importlib.import_module("onc_methods.cptac_protein_deg.derive")


def _stub_outcomes(monkeypatch, ok_map):
    """Patch stage_02_cohort to return a deterministic (cohort, secs, ok) per ok_map[cohort]."""

    def _fake(cohort, work_dir, min_normal):
        return (cohort, 0.1, ok_map[cohort])

    monkeypatch.setattr(derive, "stage_02_cohort", _fake)


def test_stage_02_all_ok_passes(monkeypatch, tmp_path):
    cohorts = ["BRCA", "COAD", "LUAD"]
    _stub_outcomes(monkeypatch, {c: True for c in cohorts})
    # no raise
    derive.stage_02(tmp_path, cohorts, parallel=1, min_normal=5)


def test_stage_02_one_failure_raises_with_roster(monkeypatch, tmp_path):
    cohorts = ["BRCA", "COAD", "LUAD", "OV"]
    _stub_outcomes(monkeypatch, {"BRCA": True, "COAD": True, "LUAD": True, "OV": False})
    with pytest.raises(RuntimeError) as exc:
        derive.stage_02(tmp_path, cohorts, parallel=1, min_normal=5)
    msg = str(exc.value)
    assert "3/4" in msg
    assert "OV" in msg  # the failed cohort is named


def test_stage_02_seven_of_ten_would_have_passed_old_gate_now_raises(monkeypatch, tmp_path):
    """The exact silent-ship case: 7/10 succeed. Old gate (n_ok<3) shipped it; new gate raises."""
    cohorts = list(derive.CPTAC_COHORTS)  # 10 cohorts
    fails = {"GBM", "OV", "UCEC"}
    _stub_outcomes(monkeypatch, {c: (c not in fails) for c in cohorts})
    with pytest.raises(RuntimeError) as exc:
        derive.stage_02(tmp_path, cohorts, parallel=2, min_normal=5)
    msg = str(exc.value)
    assert "7/10" in msg
    for f in fails:
        assert f in msg
