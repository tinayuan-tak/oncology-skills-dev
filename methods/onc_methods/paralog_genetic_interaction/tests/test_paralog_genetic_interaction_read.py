"""Tests for the paralog_genetic_interaction read layer (read.py) — the transient-cache fix.

Pins T3 Part B: the success-only module cache must NOT memoize a transient read failure. The old
`@lru_cache` over a function returning None on exception latched that None for the whole process, so
one S3 blip mid-batch silently returned data_unavailable for that target forever. A raise-once-then-
succeed sequence must return data on the retry. Also pins data_unavailable + _live_read_error on a
read failure (never a benign coverage gap).

The S3 read is monkeypatched at the pyarrow boundary — no live creds needed (noted: live S3 not
exercised). _bucket_keys() resolves offline from the local data-catalog manifest."""

from __future__ import annotations

import pyarrow.fs as fs
import pyarrow.parquet as pq
import pytest

from onc_methods.paralog_genetic_interaction import read as r


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
        "target_gene": "CDK4",
        "partner_gene": "CDK6",
        "pair_id": "CDK4_CDK6",
        "n_lines": 50,
        "mean_gi": -0.8,
        "median_gi": -0.7,
        "gi_ttest_pvalue": 1e-6,
        "frac_lines_strong_gi": 0.6,
        "min_gi": -1.5,
        "min_gi_lineage": "Lung",
        "n_lineages_strong": 3,
        "interaction_class": "constitutive_buffering",
    }
]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    r._SUMMARY_CACHE.clear()
    monkeypatch.setattr(fs, "S3FileSystem", _FakeS3FS)
    yield
    r._SUMMARY_CACHE.clear()


def test_read_failure_is_data_unavailable_with_breadcrumb(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("expired STS credentials")

    monkeypatch.setattr(pq, "read_table", _boom)
    out = r.combinatorial_dependency_for_gene("CDK4")
    assert out["combinatorial_dependency_class"] == "data_unavailable"
    # transient failure is DISTINGUISHED from genuine-absence and carries the real cause
    breadcrumb = str(out.get("_live_read_error", ""))
    assert "transient" in breadcrumb
    assert "expired STS credentials" in breadcrumb


def test_transient_failure_not_permanently_cached(monkeypatch):
    calls = {"n": 0}

    def _flaky(path, filesystem=None, filters=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient S3 blip")
        return _FakeTable(_GOOD_ROWS)

    monkeypatch.setattr(pq, "read_table", _flaky)
    first = r.combinatorial_dependency_for_gene("CDK4")
    assert first["combinatorial_dependency_class"] == "data_unavailable"
    second = r.combinatorial_dependency_for_gene("CDK4")  # retry after recovery
    assert second["combinatorial_dependency_class"] == "strong_synthetic_lethal"
    assert second["strongest_partner"] == "CDK6"
    assert calls["n"] == 2


def test_successful_read_is_cached(monkeypatch):
    calls = {"n": 0}

    def _counting(path, filesystem=None, filters=None):
        calls["n"] += 1
        return _FakeTable(_GOOD_ROWS)

    monkeypatch.setattr(pq, "read_table", _counting)
    r.combinatorial_dependency_for_gene("CDK4")
    r.combinatorial_dependency_for_gene("CDK4")
    assert calls["n"] == 1


def test_empty_absence_is_cached_and_no_paralog_screened(monkeypatch):
    """A genuine 0-row absence is a coverage gap (no_paralog_screened) and IS safe to cache."""
    calls = {"n": 0}

    def _empty(path, filesystem=None, filters=None):
        calls["n"] += 1
        return _FakeTable([])

    monkeypatch.setattr(pq, "read_table", _empty)
    out = r.combinatorial_dependency_for_gene("NOTINLIB")
    assert out["combinatorial_dependency_class"] == "no_paralog_screened"
    assert "_live_read_error" not in out
    r.combinatorial_dependency_for_gene("NOTINLIB")
    assert calls["n"] == 1


# ── _partner_class cutpoint regression guard (deferred-debt hardening) ────────────────────────────
# The reader-authoritative GI thresholds — especially FRAC_STRONG_CONSTITUTIVE=0.4, which gates the
# constitutive->context demotion and is justified anecdotally (MARK2/3 frac_strong=0.58 survives; the
# over-called artifacts sit at 0.19-0.29) — are UNCALIBRATED. These tests freeze the current boundary
# behaviour so a silent threshold change is caught (they do NOT endorse recalibration; that needs a
# labelled paralog-SL truth set).
def _pc(mean_gi, frac_strong, min_gi=None):
    return r._partner_class({"mean_gi": mean_gi, "frac_lines_strong_gi": frac_strong, "min_gi": min_gi})


def test_partner_class_cutpoints_are_pinned():
    assert r.FRAC_STRONG_CONSTITUTIVE == 0.4  # the load-bearing eyeballed gate
    assert r.CONSTITUTIVE_MEAN == -0.25
    # MARK2/3-style survivor: broad negative + majority-ish strong lines -> constitutive
    assert _pc(-0.30, 0.58) == "constitutive_buffering"
    # the demoted artifact band (frac below 0.4) -> context, NOT constitutive
    assert _pc(-0.30, 0.25) == "context_buffering"
    # exact boundary: frac==0.4 clears; 0.39 does not
    assert _pc(-0.30, 0.40) == "constitutive_buffering"
    assert _pc(-0.30, 0.39) == "context_buffering"
    # positive GI -> suppressive (masking); a single very-strong line -> context; else no_interaction
    assert _pc(0.30, 0.0) == "suppressive"
    assert _pc(-0.10, 0.05, min_gi=-1.5) == "context_buffering"
    assert _pc(-0.10, 0.05, min_gi=-0.5) == "no_interaction"
