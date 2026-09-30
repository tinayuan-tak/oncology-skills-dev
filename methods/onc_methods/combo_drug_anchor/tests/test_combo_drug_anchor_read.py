"""Tests for the combo_drug_anchor read layer (read.py) — the transient-cache-poisoning fix.

Pins T3 Part B: the success-only module cache must NOT memoize a transient read failure. The old
`@lru_cache` over a function that returns None on exception latched that None for the whole process
lifetime, so one S3 blip mid-batch silently returned data_unavailable for that target forever. Here
a raise-once-then-succeed sequence must return data on the retry. Also pins that a read failure
surfaces data_unavailable + a _live_read_error breadcrumb (never a benign coverage gap).

The S3 read is monkeypatched at the pyarrow boundary — no live creds needed (noted: live S3 not
exercised)."""

from __future__ import annotations

import pyarrow.fs as fs
import pyarrow.parquet as pq
import pytest

from onc_methods.combo_drug_anchor import read as r


class _FakeTable:
    def __init__(self, rows):
        self._rows = list(rows)

    @property
    def num_rows(self):
        return len(self._rows)

    def to_pylist(self):
        return self._rows


class _FakeS3FS:
    def __init__(self, *a, **k):
        pass


_GOOD_ROWS = [
    {
        "inhibited_target": "KRAS",
        "co_target_gene": "PTPN11",
        "anchor_drug": "MRTX1133",
        "mechanism": "KRAS-G12D inhibitor",
        "n_models": 8,
        "mean_effect_shift": -0.4,
        "min_effect_shift": -0.7,
        "n_models_significant": 6,
        "frac_models_significant": 0.75,
        "combination_class": "robust_combination",
    }
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    r._ROWS_CACHE.clear()
    monkeypatch.setattr(fs, "S3FileSystem", _FakeS3FS)
    yield
    r._ROWS_CACHE.clear()


def test_read_failure_is_data_unavailable_with_breadcrumb(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("expired STS credentials")

    monkeypatch.setattr(pq, "read_table", _boom)
    out = r.combination_opportunities_for_gene("KRAS")
    assert out["combination_opportunity_class"] == "data_unavailable"
    # transient failure is DISTINGUISHED from genuine-absence and carries the real cause
    breadcrumb = str(out.get("_live_read_error", ""))
    assert "transient" in breadcrumb
    assert "expired STS credentials" in breadcrumb


def test_transient_failure_not_permanently_cached(monkeypatch):
    """The regression this fix targets: first call raises -> data_unavailable; second call
    (S3 recovered) -> real data. The old @lru_cache would have pinned data_unavailable forever."""
    calls = {"n": 0}

    def _flaky(path, filesystem=None, filters=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient S3 blip")
        return _FakeTable(_GOOD_ROWS)

    monkeypatch.setattr(pq, "read_table", _flaky)
    first = r.combination_opportunities_for_gene("KRAS")
    assert first["combination_opportunity_class"] == "data_unavailable"
    second = r.combination_opportunities_for_gene("KRAS")  # retry after recovery
    assert second["combination_opportunity_class"] == "strong_combination_opportunity"
    assert second["strongest_co_target"] == "PTPN11"
    assert calls["n"] == 2  # genuinely re-attempted


def test_successful_read_is_cached(monkeypatch):
    """Success path unchanged: a hit is cached (one physical read for repeated calls)."""
    calls = {"n": 0}

    def _counting(path, filesystem=None, filters=None):
        calls["n"] += 1
        return _FakeTable(_GOOD_ROWS)

    monkeypatch.setattr(pq, "read_table", _counting)
    r.combination_opportunities_for_gene("KRAS")
    r.combination_opportunities_for_gene("KRAS")
    assert calls["n"] == 1


def test_empty_absence_is_cached_and_no_anchor_screen(monkeypatch):
    """A genuine 0-row absence is a coverage gap (no_anchor_screen) and IS safe to cache."""
    calls = {"n": 0}

    def _empty(path, filesystem=None, filters=None):
        calls["n"] += 1
        return _FakeTable([])

    monkeypatch.setattr(pq, "read_table", _empty)
    out = r.combination_opportunities_for_gene("NOSCREEN")
    assert out["combination_opportunity_class"] == "no_anchor_screen"
    assert "_live_read_error" not in out
    r.combination_opportunities_for_gene("NOSCREEN")
    assert calls["n"] == 1  # empty absence cached (definitive)


# ── min-cell-line power floor (thin-panel artifact guard) ────────────────────────────────────────
def _row(co, klass, n_models, shift=-0.6, nsig=None):
    nsig = nsig if nsig is not None else max(1, round(0.6 * n_models))
    return {
        "inhibited_target": "XPO1",
        "co_target_gene": co,
        "anchor_drug": "Eltanexor",
        "mechanism": "XPO1 inhibitor",
        "n_models": n_models,
        "mean_effect_shift": shift,
        "min_effect_shift": shift - 0.2,
        "n_models_significant": nsig,
        "frac_models_significant": nsig / n_models,
        "combination_class": klass,
    }


def test_underpowered_robust_is_capped_at_context_with_prefloor_audit():
    """A robust co-target resting on n_models < MIN_POWERED_MODELS (the XPO1 n=2 artifact) is capped
    at context, but the raw pre-floor call + the underpowered flag are preserved for audit."""
    out = r.combination_opportunities_for_gene("XPO1", rows=(_row("STRAP", "robust_combination", 2),))
    assert out["combination_opportunity_class"] == "context_combination_opportunity"
    assert out["combination_opportunity_class_prefloor"] == "strong_combination_opportunity"
    assert out["drug_anchor_underpowered"] is True
    assert out["drug_anchor_n_models_max"] == 2
    assert "UNDERPOWERED" in out["combination_context"]


def test_powered_robust_is_unchanged_and_not_flagged():
    """A robust co-target on a sufficient panel (n_models >= MIN_POWERED_MODELS) is unchanged and
    NOT flagged underpowered — the floor only moves the thin panels (KRAS n=6 / KIT n=3 stay)."""
    out = r.combination_opportunities_for_gene("KIT", rows=(_row("BORA", "robust_combination", 3),))
    assert out["combination_opportunity_class"] == "strong_combination_opportunity"
    assert out["combination_opportunity_class_prefloor"] == "strong_combination_opportunity"
    assert out["drug_anchor_underpowered"] is False


def test_underpowered_signal_is_never_erased_to_no_signal():
    """An underpowered positive co-target is capped at context, never dropped to no_combination_signal
    (a measured co-target is a conditional hypothesis, not absence)."""
    out = r.combination_opportunities_for_gene("XPO1", rows=(_row("X", "supported_combination", 2),))
    assert out["combination_opportunity_class"] == "context_combination_opportunity"
    assert out["combination_opportunity_class_prefloor"] == "combination_opportunity"
    assert out["drug_anchor_underpowered"] is True
