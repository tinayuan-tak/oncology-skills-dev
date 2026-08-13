"""Tests for pair_selectivity_gate.window — the tumor-vs-normal AND-gate combiner.

Monkeypatch the two upstream readers (confirm_pair_samecell, normal_max_both) with canned payloads
and assert the verdict truth table + margin. No S3."""

import pytest

import methods.pair_selectivity_gate.window as W


def _tumor(both, call="same_cell_coordinated"):
    return {"samecell_avidity_call": call, "samecell_both_fraction_median": both,
            "samecell_enrichment_median": 1.4, "n_donors": 50}


def _normal(cls, nmb, locus=None):
    return {"normal_selectivity_class": cls, "normal_max_both_fraction": nmb,
            "normal_liability_locus": locus, "support_floor": {"min_donors": 3, "min_cells": 10}}


def _patch(monkeypatch, tumor, normal):
    monkeypatch.setattr(W, "confirm_pair_samecell", lambda t, p, i: tumor)
    monkeypatch.setattr(W, "normal_max_both", lambda t, p: normal)


def test_window_open_high_tumor_clean_normal(monkeypatch):
    _patch(monkeypatch, _tumor(0.60), _normal("selectivity_clean", 0.01))
    r = W.pair_selectivity_window("FOLR1", "MSLN", "OV")
    assert r["window_verdict"] == "window_open"
    assert r["selectivity_margin"] == 0.59


def test_no_window_normal_liability(monkeypatch):
    locus = {"tissue": "kidney", "cell_type": "proximal tubule", "both_fraction_median": 0.4}
    _patch(monkeypatch, _tumor(0.60), _normal("normal_liability", 0.40, locus))
    r = W.pair_selectivity_window("FOLR1", "MSLN", "OV")
    assert r["window_verdict"] == "no_window"
    assert r["normal_liability_locus"]["tissue"] == "kidney"
    assert r["selectivity_margin"] == 0.20


def test_selectivity_unproven_when_normal_under_powered(monkeypatch):
    _patch(monkeypatch, _tumor(0.60), _normal("under_powered", None))
    r = W.pair_selectivity_window("FOLR1", "MSLN", "OV")
    assert r["window_verdict"] == "selectivity_unproven"   # NOT window_open, NOT no_window
    assert r["selectivity_margin"] is None


def test_window_marginal_borderline_normal(monkeypatch):
    _patch(monkeypatch, _tumor(0.60), _normal("normal_borderline", 0.05))
    assert W.pair_selectivity_window("FOLR1", "MSLN", "OV")["window_verdict"] == "window_marginal"


def test_insufficient_tumor_below_tau(monkeypatch):
    _patch(monkeypatch, _tumor(0.10), _normal("selectivity_clean", 0.0))
    assert W.pair_selectivity_window("FOLR1", "MSLN", "OV")["window_verdict"] == "insufficient_tumor_engagement"


def test_insufficient_tumor_not_coordinated(monkeypatch):
    # both >= TAU but avidity is independent (not coordinated) -> avidity gate won't co-engage
    _patch(monkeypatch, _tumor(0.60, call="same_cell_independent"), _normal("selectivity_clean", 0.0))
    assert W.pair_selectivity_window("FOLR1", "MSLN", "OV")["window_verdict"] == "insufficient_tumor_engagement"


def test_tau_boundary_inclusive(monkeypatch):
    _patch(monkeypatch, _tumor(W.TUMOR_ENGAGEMENT_MIN), _normal("selectivity_clean", 0.0))
    assert W.pair_selectivity_window("FOLR1", "MSLN", "OV")["window_verdict"] == "window_open"


def test_tumor_data_unavailable(monkeypatch):
    _patch(monkeypatch, {"samecell_avidity_call": "data_unavailable", "samecell_both_fraction_median": None},
           _normal("selectivity_clean", 0.0))
    assert W.pair_selectivity_window("FOLR1", "MSLN", "OV")["window_verdict"] == "data_unavailable"


def test_normal_data_unavailable_when_tumor_engages(monkeypatch):
    _patch(monkeypatch, _tumor(0.60), {"normal_selectivity_class": "data_unavailable",
                                       "normal_max_both_fraction": None, "normal_liability_locus": None})
    assert W.pair_selectivity_window("FOLR1", "MSLN", "OV")["window_verdict"] == "data_unavailable"


def test_target_centric_best_partner(monkeypatch):
    # FOLR1: MSLN window_open (margin .59), MUC16 no_window. Headline = window_open / MSLN.
    monkeypatch.setattr(W, "read_target_samecell_avidity",
                        lambda t, i: {"partners": [{"partner": "MSLN"}, {"partner": "MUC16"}]},
                        raising=False)
    def fake_window(target, partner, indication):
        if partner == "MSLN":
            return {"partner": "MSLN", "window_verdict": "window_open", "selectivity_margin": 0.59,
                    "tumor_both_fraction": 0.6, "normal_max_both_fraction": 0.01, "normal_liability_locus": None}
        return {"partner": "MUC16", "window_verdict": "no_window", "selectivity_margin": 0.2,
                "tumor_both_fraction": 0.6, "normal_max_both_fraction": 0.4, "normal_liability_locus": {"tissue": "ovary"}}
    monkeypatch.setattr(W, "pair_selectivity_window", fake_window)
    r = W.read_target_selectivity_window("FOLR1", "OV")
    assert r["n_partners_tested"] == 2
    assert r["window_verdict"] == "window_open"
    assert r["best_partner"] == "MSLN"
    assert r["n_window_open"] == 1
