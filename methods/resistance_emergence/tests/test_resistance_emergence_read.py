"""Tests for the resistance_emergence read layer (read.py).

Mirrors combo_drug_anchor's transient-cache-poisoning pins (a read failure must NOT be permanently
cached; success/empty are cached) and adds the resistance-specific pin: the self-target row
(rescuer_gene == inhibited_target) is dropped before classify/rank (a KO of the drug's own target is
a self-consistency artifact, not a resistance mediator).

The S3 read is monkeypatched at the pyarrow boundary — no live creds needed (live S3 not exercised).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import pyarrow.parquet as pq  # noqa: E402
import pyarrow.fs as fs  # noqa: E402
import pytest  # noqa: E402

from methods.resistance_emergence import read as r  # noqa: E402


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


def _row(rescuer, klass, mean_shift, nsig=5, nm=5):
    return {
        "inhibited_target": "KRAS", "rescuer_gene": rescuer, "anchor_drug": "MRTX1133",
        "mechanism": "KRAS-G12D inhibitor", "n_models": nm, "mean_effect_shift": mean_shift,
        "max_effect_shift": mean_shift + 0.1, "n_models_significant": nsig,
        "frac_models_significant": nsig / nm, "resistance_class": klass,
    }


_GOOD_ROWS = [
    _row("NF1", "robust_resistance_mediator", 0.84),
    _row("KEAP1", "robust_resistance_mediator", 0.59),
    _row("KRAS", "robust_resistance_mediator", 0.64),   # self-target — must be dropped
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
    out = r.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    assert out["resistance_emergence_class"] == "data_unavailable"
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
    first = r.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    assert first["resistance_emergence_class"] == "data_unavailable"
    second = r.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)   # retry after recovery
    assert second["resistance_emergence_class"] == "strong_resistance_signal"
    assert second["strongest_mediator"] == "NF1"
    assert calls["n"] == 2


def test_self_target_row_is_dropped(monkeypatch):
    """KRAS (rescuer==inhibited_target) must be dropped; NF1/KEAP1 remain, and the KRAS self-row
    must never surface as the strongest mediator."""
    def _read(path, filesystem=None, filters=None):
        return _FakeTable(_GOOD_ROWS)

    monkeypatch.setattr(pq, "read_table", _read)
    out = r.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    genes = [m["rescuer_gene"] for m in out["top_resistance_mediators"]]
    assert "KRAS" not in genes                      # self-target dropped
    assert out["n_resistance_mediators"] == 2       # NF1 + KEAP1 only
    assert out["strongest_mediator"] == "NF1"       # most-positive shift among non-self
    assert out["resistance_emergence_class"] == "strong_resistance_signal"


def test_successful_read_is_cached(monkeypatch):
    calls = {"n": 0}

    def _counting(path, filesystem=None, filters=None):
        calls["n"] += 1
        return _FakeTable(_GOOD_ROWS)

    monkeypatch.setattr(pq, "read_table", _counting)
    r.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    r.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    assert calls["n"] == 1


def test_empty_absence_is_cached_and_no_anchor_screen(monkeypatch):
    calls = {"n": 0}

    def _empty(path, filesystem=None, filters=None):
        calls["n"] += 1
        return _FakeTable([])

    monkeypatch.setattr(pq, "read_table", _empty)
    out = r.resistance_mediators_for_gene("NOSCREEN", include_tahoe_adaptation=False)
    assert out["resistance_emergence_class"] == "no_anchor_screen"
    assert "_live_read_error" not in out
    r.resistance_mediators_for_gene("NOSCREEN", include_tahoe_adaptation=False)
    assert calls["n"] == 1


def test_all_self_target_becomes_no_resistance_signal(monkeypatch):
    """If the ONLY row is the self-target, dropping it leaves an anchor-screened-but-empty set =>
    no_resistance_signal (a REAL negative), NOT no_anchor_screen (a coverage gap). This is the
    distinction _classify preserves by taking both raw rows and post-self mediators."""
    def _only_self(path, filesystem=None, filters=None):
        return _FakeTable([_row("KRAS", "robust_resistance_mediator", 0.64)])

    monkeypatch.setattr(pq, "read_table", _only_self)
    out = r.resistance_mediators_for_gene("KRAS", include_tahoe_adaptation=False)
    assert out["resistance_emergence_class"] == "no_resistance_signal"
    assert out["n_resistance_mediators"] == 0
    assert out["anchor_drug"] == "MRTX1133"     # anchor metadata still surfaced from raw row


# ── min-cell-line power floor (thin-panel artifact guard) ────────────────────────────────────────
def test_underpowered_robust_resistance_is_capped_at_context_with_prefloor_audit():
    """A robust rescuer resting on n_models < MIN_POWERED_MODELS (the XPO1 n=2 artifact) is capped at
    context_resistance_signal; the raw pre-floor call + underpowered flag are preserved for audit."""
    rows = (_row("FEN1", "robust_resistance_mediator", 0.8, nsig=1, nm=2),)
    out = r.resistance_mediators_for_gene("XPO1", rows=rows, include_tahoe_adaptation=False)
    assert out["resistance_emergence_class"] == "context_resistance_signal"
    assert out["resistance_emergence_class_prefloor"] == "strong_resistance_signal"
    assert out["drug_anchor_underpowered"] is True
    assert out["drug_anchor_n_models_max"] == 2
    assert "UNDERPOWERED" in out["resistance_context"]


def test_powered_robust_resistance_unchanged_and_not_flagged():
    """A robust rescuer on a sufficient panel (n_models >= MIN_POWERED_MODELS) is unchanged and NOT
    flagged underpowered (KRAS n=6 / KIT n=3 keep their strong call)."""
    rows = (_row("BORA", "robust_resistance_mediator", 0.8, nsig=2, nm=3),)
    out = r.resistance_mediators_for_gene("KIT", rows=rows, include_tahoe_adaptation=False)
    assert out["resistance_emergence_class"] == "strong_resistance_signal"
    assert out["resistance_emergence_class_prefloor"] == "strong_resistance_signal"
    assert out["drug_anchor_underpowered"] is False


def test_underpowered_resistance_never_erased_to_no_signal():
    """An underpowered positive rescuer is capped at context, never dropped to no_resistance_signal."""
    rows = (_row("Y", "supported_resistance_mediator", 0.4, nsig=1, nm=2),)
    out = r.resistance_mediators_for_gene("XPO1", rows=rows, include_tahoe_adaptation=False)
    assert out["resistance_emergence_class"] == "context_resistance_signal"
    assert out["resistance_emergence_class_prefloor"] == "resistance_signal"
    assert out["drug_anchor_underpowered"] is True
