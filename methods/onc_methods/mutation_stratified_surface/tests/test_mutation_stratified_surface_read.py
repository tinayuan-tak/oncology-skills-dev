"""Tests for the mutation_stratified_surface read layer (read.py) — the error-vs-absence fix.

Pins T3 Part A: a read that RAISES must map to `data_unavailable` + a `_live_read_error`
breadcrumb (NOT the benign `not_in_product` coverage-gap class — the "bare-except masks broken
env" failure class). A genuine 0-row absence still maps to `not_in_product`. And a transient
failure is not permanently latched: raise-once-then-succeed returns data on the retry.

The S3 read (_read_row) is monkeypatched — no live creds needed (noted: live S3 not exercised)."""

from __future__ import annotations

from onc_methods.mutation_stratified_surface import read as r


def test_read_failure_is_data_unavailable_not_coverage_gap(monkeypatch):
    """A read exception -> data_unavailable + _live_read_error, NEVER not_in_product."""

    def _boom(target, driver, indication):
        return r._ReadError("OSError: expired STS credentials")

    monkeypatch.setattr(r, "_read_row", _boom)
    out = r.read_mutation_stratified_surface("EGFR")
    assert out["mutant_stratified_surface_class"] == "data_unavailable"
    assert out["mutant_stratified_surface_class"] != "not_in_product"
    assert "_live_read_error" in out
    assert "expired STS credentials" in out["_live_read_error"]


def test_genuine_absence_is_still_not_in_product(monkeypatch):
    """A genuine 0-row absence (None) keeps the benign coverage-gap class — no breadcrumb."""
    monkeypatch.setattr(r, "_read_row", lambda *a, **k: None)
    out = r.read_mutation_stratified_surface("SOMEGENE")
    assert out["mutant_stratified_surface_class"] == "not_in_product"
    assert "_live_read_error" not in out


def test_transient_failure_not_permanently_latched(monkeypatch):
    """Raise-once-then-succeed: the second call returns real data (no permanent poisoning).
    _read_row is uncached here, but this pins that a transient failure never latches."""
    calls = {"n": 0}
    good_row = {
        "mutant_stratified_surface_class": "mutant_up_surface",
        "driver_gene": "KRAS",
        "indication": "NSCLC",
        "delta_log2": 1.2,
        "q_value": 0.01,
        "n_mutant": 40,
        "n_wt": 60,
    }

    def _flaky(target, driver, indication):
        calls["n"] += 1
        if calls["n"] == 1:
            return r._ReadError("RuntimeError: transient S3 blip")
        return good_row

    monkeypatch.setattr(r, "_read_row", _flaky)
    first = r.read_mutation_stratified_surface("EGFR")
    assert first["mutant_stratified_surface_class"] == "data_unavailable"
    second = r.read_mutation_stratified_surface("EGFR")
    assert second["mutant_stratified_surface_class"] == "mutant_up_surface"
    assert calls["n"] == 2


def test_injected_row_success_path_unchanged():
    """The success path (row injected) is unchanged — verdict class flows from the record."""
    row = {
        "mutant_stratified_surface_class": "mutant_up_surface",
        "driver_gene": "KRAS",
        "indication": "NSCLC",
        "delta_log2": 0.9,
        "q_value": 0.02,
        "n_mutant": 30,
        "n_wt": 50,
    }
    out = r.read_mutation_stratified_surface("ANTIGEN", row=row)
    assert out["mutant_stratified_surface_class"] == "mutant_up_surface"
    assert out["delta_log2"] == 0.9
    assert "_live_read_error" not in out
