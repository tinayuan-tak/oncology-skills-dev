"""combo_drug_anchor.read — hermetic tests (injected rows, no S3).

Pins combination_opportunity_class precedence, the no_anchor_screen coverage-gap default
(NOT no-combination), the data_unavailable-vs-no_anchor distinction, and co-target ranking.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.combo_drug_anchor.read import combination_opportunities_for_gene  # noqa: E402


def _co(gene, shift, klass, **kw):
    base = {"inhibited_target": "KRAS", "co_target_gene": gene, "anchor_drug": "MRTX1133",
            "mechanism": "KRAS-G12D inhibitor", "n_models": 6, "mean_effect_shift": shift,
            "min_effect_shift": shift - 0.2, "n_models_significant": 5,
            "frac_models_significant": 0.83, "combination_class": klass}
    base.update(kw)
    return base


def test_robust_wins():
    rows = (_co("WEAKER", -0.30, "supported_combination"),
            _co("PTPN11", -0.70, "robust_combination"))
    r = combination_opportunities_for_gene("KRAS", rows=rows)
    assert r["combination_opportunity_class"] == "strong_combination_opportunity"
    assert r["strongest_co_target"] == "PTPN11"      # most-negative shift ranks first


def test_supported_when_no_robust():
    rows = (_co("GRB2", -0.35, "supported_combination"),)
    r = combination_opportunities_for_gene("KRAS", rows=rows)
    assert r["combination_opportunity_class"] == "combination_opportunity"


def test_context_only():
    rows = (_co("X", -0.55, "context_combination", n_models_significant=1, frac_models_significant=0.17),)
    r = combination_opportunities_for_gene("KRAS", rows=rows)
    assert r["combination_opportunity_class"] == "context_combination_opportunity"


def test_no_anchor_screen_is_coverage_gap_not_negative():
    r = combination_opportunities_for_gene("EGFR", rows=tuple())
    assert r["combination_opportunity_class"] == "no_anchor_screen"
    assert "coverage gap" in r["combination_context"].lower()


def test_read_failure_is_data_unavailable(monkeypatch):
    # GENUINE absence: the reader returns None on NoSuchKey/404 -> data_unavailable (unchanged).
    # (A transient/creds read failure now RE-RAISES instead of masking — see
    # tests/methods/combo_drug_anchor/test_read_rows_absence.py.) rows=None here means "read live",
    # so monkeypatch the reader to the genuine-absence result to keep this test hermetic.
    import methods.combo_drug_anchor.read as _m
    monkeypatch.setattr(_m, "_read_rows", lambda target: None)
    r = combination_opportunities_for_gene("KRAS", rows=None)
    assert r["combination_opportunity_class"] == "data_unavailable"


def test_ranking_ascending_by_shift():
    rows = (_co("HI", -0.30, "supported_combination"),
            _co("LO", -0.80, "robust_combination"),
            _co("MID", -0.50, "supported_combination"))
    r = combination_opportunities_for_gene("KRAS", rows=rows)
    assert [p["co_target_gene"] for p in r["top_co_targets"]] == ["LO", "MID", "HI"]
