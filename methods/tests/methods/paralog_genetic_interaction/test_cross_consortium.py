"""cross_consortium_paralog_gi_for_gene — the T0-1 corroboration lane. Rows injected (no S3): a
verdict-inert 2nd/3rd-opinion (Dede zdLFC + in4mer normZ) on the DepMap ParalogV2 CODEP call.
"""

from __future__ import annotations

import sys
from pathlib import Path

_METHODS = Path(__file__).resolve().parents[3] / "methods"
if str(_METHODS.parent) not in sys.path:
    sys.path.insert(0, str(_METHODS.parent))

from methods.paralog_genetic_interaction import read as pgi  # noqa: E402
from methods.paralog_genetic_interaction.read import cross_consortium_paralog_gi_for_gene  # noqa: E402


def _row(partner, klass):
    return {"target_gene": "G", "partner_gene": partner, "interaction_class": klass}


def test_corroborated_multi_consortium():
    r = cross_consortium_paralog_gi_for_gene(
        "G",
        dede_rows=(_row("P1", "constitutive_buffering"),),
        in4mer_rows=(_row("P1", "constitutive_buffering"),),
    )
    assert r["cross_consortium_paralog_class"] == "corroborated_multi_consortium"
    assert r["n_consortia_corroborating"] == 2
    assert r["corroborating_partners"] == ["P1"]  # de-duped across consortia


def test_single_consortium_corroboration():
    r = cross_consortium_paralog_gi_for_gene(
        "G",
        dede_rows=(_row("P1", "constitutive_buffering"), _row("P2", "no_interaction")),
        in4mer_rows=(_row("P1", "no_interaction"),),
    )
    assert r["cross_consortium_paralog_class"] == "single_consortium_corroboration"
    assert r["n_consortia_corroborating"] == 1
    assert r["dede_n_sl_partners"] == 1 and r["in4mer_n_sl_partners"] == 0


def test_no_cross_consortium_signal_when_screened_but_not_sl():
    r = cross_consortium_paralog_gi_for_gene(
        "G", dede_rows=(_row("P1", "suppressive"),), in4mer_rows=(_row("P1", "no_interaction"),)
    )
    assert r["cross_consortium_paralog_class"] == "no_cross_consortium_signal"
    assert r["n_consortia_corroborating"] == 0


def test_not_screened_off_panel_when_both_absent():
    r = cross_consortium_paralog_gi_for_gene("G", dede_rows=tuple(), in4mer_rows=tuple())
    assert r["cross_consortium_paralog_class"] == "not_screened_off_panel"


def test_data_unavailable_when_both_read_fail(monkeypatch):
    # both legs' summary read returns None (genuine no-object) → data_unavailable + honest breadcrumb.
    # (dede_rows=None is the DEFAULT "not injected → read" sentinel, so we force the read helper to None.)
    monkeypatch.setattr(pgi, "_read_consortium_summary", lambda *a, **k: None)
    r = cross_consortium_paralog_gi_for_gene("G")
    assert r["cross_consortium_paralog_class"] == "data_unavailable"
    assert "_live_read_error" in r


def test_context_buffering_counts_as_sl():
    r = cross_consortium_paralog_gi_for_gene(
        "G", dede_rows=(_row("P1", "context_buffering"),), in4mer_rows=(_row("P2", "context_buffering"),)
    )
    # in4mer has no context_buffering in real data, but the classifier treats it as SL either way.
    assert r["cross_consortium_paralog_class"] == "corroborated_multi_consortium"
    assert set(r["corroborating_partners"]) == {"P1", "P2"}
