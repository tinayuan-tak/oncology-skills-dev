"""#984 Tier-2: the tumor-selectivity window hand-off breadcrumb is ABUNDANCE-aware — a low-abundance
normal liability (FOLR1-class) is flagged as a workable window despite broad detection; high-abundance
(EPCAM/CEA-class) is the real concern. Still a breadcrumb — presence never adjudicates the window."""

from __future__ import annotations

from _skills_common.presence_claims import presence_key_signals


def _h(abund):
    return {
        "normal_tissue_ihc_breadth_class": "broad_normal_expression",
        "sc_normal_expression_class": "HIGH_LIABILITY",
        "sc_normal_abundance_class": abund,
    }


def test_breadcrumb_low_abundance_flags_workable_window():
    c = presence_key_signals(_h("low_abundance"), [])["caveat"]
    assert "therapeutic-window liability" in c and "LOW normal abundance" in c
    assert "owned by tumor-selectivity" in c


def test_breadcrumb_high_abundance_flags_real_concern():
    assert "HIGH normal abundance" in presence_key_signals(_h("high_abundance"), [])["caveat"]


def test_breadcrumb_without_abundance_is_unchanged():
    c = presence_key_signals(_h(None), [])["caveat"]
    assert "therapeutic-window liability" in c and "normal abundance" not in c
