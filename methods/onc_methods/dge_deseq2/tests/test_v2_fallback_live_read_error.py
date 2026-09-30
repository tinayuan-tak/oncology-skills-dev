"""#797: the legacy v2 selectivity fallback (`_read_tvn_selectivity_v2_fallback`) wrapped its
child reads in blanket `except Exception: = None`, collapsing a transient/creds error to a clean
`data_unavailable`-shaped record with no `_live_read_error` breadcrumb — a silent verdict drop on
the resolver-spine card — and re-caught (defeated) the child reader's own `is_definitively_absent`
re-raise (the #783 pattern).

These tests pin BOTH directions so the fix can't over-correct:
  1. genuine absence (FileNotFoundError / a definitively-absent ClientError) must still degrade
     to a clean data_unavailable record with NO `_live_read_error`.
  2. a non-definitive failure (transient / creds / broken-env) on EITHER child read must surface
     `_live_read_error` on the composite record, never a silent data_unavailable.
"""

from __future__ import annotations

from onc_methods.dge_deseq2 import read as r


class _FakeThrottling(Exception):
    """Stand-in for a transient/creds botocore error — NOT a genuine-absence signal."""


def _force_v2_fallback(monkeypatch):
    # Sensitivity product not landed for this indication -> composite takes the v2 path.
    monkeypatch.setattr(r, "read_tumor_vs_normal_sensitivity_gene_row", lambda t, i: None)
    # COADREAD has an adj manifest configured (_INDICATION_TO_ADJ_MANIFEST), so both child
    # reads are actually attempted.
    monkeypatch.setattr(r, "_INDICATION_TO_ADJ_MANIFEST", {"COADREAD": "coadread-dge-df06320"})


def test_v2_fallback_genuine_absence_stays_clean(monkeypatch):
    """Both children definitively absent -> clean data_unavailable, no _live_read_error."""
    _force_v2_fallback(monkeypatch)

    def _raise_not_found(*a, **k):
        raise FileNotFoundError("no such object")

    monkeypatch.setattr(r, "read_dge_gene_row", _raise_not_found)
    monkeypatch.setattr(r, "read_tumor_vs_gtex_gene_row", _raise_not_found)

    out = r.read_tumor_vs_normal_selectivity("EPCAM", "COADREAD")
    assert "_live_read_error" not in out
    assert out["selectivity_class"] is not None  # composite still always returns a shaped dict
    assert out["cells_ran"] is None  # honest: neither product landed


def test_v2_fallback_transient_on_adjacent_read_surfaces_live_read_error(monkeypatch):
    """A transient (non-definitive) failure reading the adjacent-TCGA product must surface
    _live_read_error on the composite record — not collapse to a silent data_unavailable."""
    _force_v2_fallback(monkeypatch)

    def _raise_transient(*a, **k):
        raise _FakeThrottling("SlowDown: please reduce request rate")

    monkeypatch.setattr(r, "read_dge_gene_row", _raise_transient)
    monkeypatch.setattr(r, "read_tumor_vs_gtex_gene_row", lambda t, i: None)

    out = r.read_tumor_vs_normal_selectivity("EPCAM", "COADREAD")
    assert "_live_read_error" in out
    assert "adj" in out["_live_read_error"]


def test_v2_fallback_transient_on_gtex_read_surfaces_live_read_error(monkeypatch):
    """Same, but the failure is on the GTEx child read (which itself re-raises transients per
    #783 — the outer composite must not re-catch and defeat that re-raise)."""
    _force_v2_fallback(monkeypatch)

    def _raise_transient(*a, **k):
        raise _FakeThrottling("ExpiredToken")

    monkeypatch.setattr(r, "read_dge_gene_row", lambda t, m: None)
    monkeypatch.setattr(r, "read_tumor_vs_gtex_gene_row", _raise_transient)

    out = r.read_tumor_vs_normal_selectivity("EPCAM", "COADREAD")
    assert "_live_read_error" in out
    assert "gtex" in out["_live_read_error"]
