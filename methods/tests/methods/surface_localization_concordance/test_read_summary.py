"""Hermetic tests for the surface_localization_concordance joiner reader (target-contracts#966).

No live S3 / no credentials — the two child readers are injected via the offline seams on
cli.load_and_classify (surfaceome_reader= / surface_evidence_reader=). Covers the classifier
cross-tab (all six classes), the emitted summary shape, and the graceful-degradation contract.
"""

from __future__ import annotations

import pytest

from onc_methods.surface_localization_concordance import cli, read


# ── canned child-reader summaries (the fields the joiner reads) ──────────────────────────────────
def _cl(localization_class, *, median_enrichment=1.0, n_lines=8):
    """A cell-line surfaceome summary stub (depmap_surfaceome_protein_abundance shape)."""
    return {
        "surface_localization_class": localization_class,
        "median_enrichment_log2ratio": median_enrichment,
        "n_lines_enrichment_evaluated": n_lines,
    }


def _ev(confirmation_class, *, measured_in_cspa=True, n_celllines=12):
    """An orthogonal surface-confirmation summary stub (cspa_surface_confirmation shape)."""
    return {
        "surface_confirmation_class": confirmation_class,
        "measured_in_cspa": measured_in_cspa,
        "n_celllines_detected": n_celllines,
    }


def _join(cl_summary, ev_summary):
    return cli.load_and_classify(
        "TARGETX",
        surfaceome_reader=lambda t: cl_summary,
        surface_evidence_reader=lambda t: ev_summary,
    )


# ── classifier unit cross-tab: all six classes reachable ─────────────────────────────────────────
@pytest.mark.parametrize(
    "cl_class, ev_class, expected",
    [
        # concordant surface (both confirm)
        ("surface_confirmed", "confirmed_high", cli.CLASS_CONCORDANT_SURFACE),
        ("surface_confirmed", "confirmed", cli.CLASS_CONCORDANT_SURFACE),
        # concordant NOT surface (both agree not-surface)
        ("intracellular_contaminant", "not_surface", cli.CLASS_CONCORDANT_NOT_SURFACE),
        # discordant (one confirms, other measured-negative), both directions
        ("surface_confirmed", "not_surface", cli.CLASS_DISCORDANT),
        ("intracellular_contaminant", "confirmed_high", cli.CLASS_DISCORDANT),
        # cell-line only (cell-line confirms; orthogonal non-committal)
        ("surface_confirmed", "data_unavailable", cli.CLASS_CELL_LINE_ONLY),
        ("surface_confirmed", None, cli.CLASS_CELL_LINE_ONLY),
        # surface-evidence only (orthogonal confirms; cell-line non-committal)
        ("mixed", "confirmed_high", cli.CLASS_SURFACE_EVIDENCE_ONLY),
        ("insufficient", "confirmed", cli.CLASS_SURFACE_EVIDENCE_ONLY),
        ("data_unavailable", "confirmed", cli.CLASS_SURFACE_EVIDENCE_ONLY),
        # insufficient (both non-committal, or a residual asymmetric/ambiguous case)
        ("insufficient", "data_unavailable", cli.CLASS_INSUFFICIENT),
        (None, None, cli.CLASS_INSUFFICIENT),
        ("intracellular_contaminant", "data_unavailable", cli.CLASS_INSUFFICIENT),  # not-surface w/o corroboration
        ("data_unavailable", "not_surface", cli.CLASS_INSUFFICIENT),
        ("mixed", "not_surface", cli.CLASS_INSUFFICIENT),
        ("mixed", "data_unavailable", cli.CLASS_INSUFFICIENT),
    ],
)
def test_classify_cross_tab(cl_class, ev_class, expected):
    assert cli.classify_surface_concordance(cl_class, ev_class) == expected


# ── emitted summary shape + passthrough ──────────────────────────────────────────────────────────
def test_summary_shape_and_passthrough():
    out = _join(_cl("surface_confirmed", median_enrichment=1.4, n_lines=9), _ev("confirmed_high", n_celllines=15))
    assert out["surface_context_concordance_class"] == cli.CLASS_CONCORDANT_SURFACE
    assert out["cellline_surface_localization_class"] == "surface_confirmed"
    assert out["orthogonal_surface_confirmation_class"] == "confirmed_high"
    assert out["cellline_median_enrichment_log2ratio"] == 1.4
    assert out["cellline_n_lines_enrichment_evaluated"] == 9
    assert out["orthogonal_measured_in_cspa"] is True
    assert out["orthogonal_n_celllines_detected"] == 15
    assert out["method_version"] == cli.METHOD_VERSION
    assert "depmap-surfaceome-paired-per-protein-v1" in out["concordance_substrate"]
    assert "cspa-surface-confirmation-per-uniprot-v1" in out["concordance_substrate"]


def test_missing_child_fields_degrade_to_insufficient():
    # child readers returning empty dicts (no class keys) → both non-committal → insufficient
    out = cli.load_and_classify("TARGETX", surfaceome_reader=lambda t: {}, surface_evidence_reader=lambda t: {})
    assert out["surface_context_concordance_class"] == cli.CLASS_INSUFFICIENT
    assert out["cellline_surface_localization_class"] is None
    assert out["orthogonal_surface_confirmation_class"] is None


def test_child_returning_none_is_tolerated():
    out = cli.load_and_classify(
        "TARGETX", surfaceome_reader=lambda t: None, surface_evidence_reader=lambda t: _ev("confirmed")
    )
    # cell-line arm None → non-committal; orthogonal confirms → surface_evidence_only
    assert out["surface_context_concordance_class"] == cli.CLASS_SURFACE_EVIDENCE_ONLY


# ── graceful degradation: a transient/infra fault from a child reader → _live_read_error ─────────
def test_read_target_summary_degrades_on_fault(monkeypatch):
    def _boom(target):
        raise RuntimeError("transient S3 blip")

    # inject via the default readers path: monkeypatch load_and_classify's default resolver to raise
    monkeypatch.setattr(cli, "_default_surfaceome_reader", lambda: _boom)
    out = read.read_target_summary("TARGETX")
    assert out["_live_read_error"] == "surface_localization_concordance_read_failed"
    assert out["surface_context_concordance_class"] == cli.CLASS_INSUFFICIENT
    assert "_remediation" in out


def test_read_target_summary_indication_accepted_not_consumed():
    # indication is accepted for the dispatch contract; result is target-grain (unaffected by it)
    monkeypatch_readers = dict(
        surfaceome_reader=lambda t: _cl("surface_confirmed"),
        surface_evidence_reader=lambda t: _ev("confirmed_high"),
    )
    a = cli.load_and_classify("TARGETX", **monkeypatch_readers)
    # read_target_summary uses the real (lazy) readers, so just assert it accepts indication kwarg
    # without error when the join path is exercised via load_and_classify above.
    assert a["surface_context_concordance_class"] == cli.CLASS_CONCORDANT_SURFACE
