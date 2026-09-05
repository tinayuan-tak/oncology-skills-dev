"""Drift-guard: the Tahoe drug-perturbation MoA facet must keep flowing through mechanism-and-
pharmacology's _headline (a 2026-08-11 facet-drop that silently dropped a card from a skill's CARDS
list motivated this class of guard). Tahoe is a verdict-INERT target-ENGAGEMENT/MoA lens — it feeds
NO resolver, and this test pins BOTH that it is emitted AND that it never perturbs the verdict.
Offline: pure _headline over synthetic cards, no S3/reader.

_headline reads several cards via get_card_field, which RAISES on a missing card_id — so a valid call
must supply every card the skill declares (me.CARDS); we populate only the tahoe one.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

me = load_run_py(Path(__file__).resolve().parent.parent, "me_run")

# summary uses the SOURCE field names (n_perturbing_drugs, strongest_mover_drug, ...); _headline maps
# them to the tahoe_-prefixed output keys.
_TAHOE_SUMMARY = {
    "tahoe_perturbation_class": "drug_suppressed",
    "n_perturbing_drugs": 12,
    "strongest_mover_drug": "Trametinib",           # the DUSP6->MEK-inhibitor Pilot-2 anchor
    "strongest_mover_log2fc": -2.3,
    "top_suppressing_drugs": [{"drug": "Trametinib", "median_log2fc": -2.3}],
    "top_inducing_drugs": [],
}


def _cards(tahoe_summary):
    """All cards the skill declares (empty summaries) with the tahoe card populated — so every
    get_card_field lookup in _headline resolves."""
    cards = [{"card_id": cid, "summary": {}} for cid in me.CARDS]
    for c in cards:
        if c["card_id"] == "tahoe-drug-perturbation":
            c["summary"] = dict(tahoe_summary)
    return cards


def test_tahoe_card_registered():
    """facet-drop guard: the card must stay in the skill's CARDS list."""
    assert "tahoe-drug-perturbation" in me.CARDS


def test_headline_emits_all_six_tahoe_fields():
    h = me._headline(_cards(_TAHOE_SUMMARY), [], None)
    assert h["tahoe_perturbation_class"] == "drug_suppressed"
    assert h["tahoe_n_perturbing_drugs"] == 12
    assert h["tahoe_strongest_mover_drug"] == "Trametinib"
    assert h["tahoe_strongest_mover_log2fc"] == -2.3
    assert h["tahoe_top_suppressing_drugs"] == [{"drug": "Trametinib", "median_log2fc": -2.3}]
    assert "tahoe_top_inducing_drugs" in h            # emitted even when empty


def test_tahoe_is_verdict_inert():
    """Tahoe is display-only: mechanism_verdict identical with a populated vs empty tahoe card, and
    the fields degrade to None (never raise) when the tahoe data is absent."""
    vp = ("well_characterized", "some-rule")
    with_tahoe = me._headline(_cards(_TAHOE_SUMMARY), [], vp)
    empty_tahoe = me._headline(_cards({}), [], vp)
    assert with_tahoe["mechanism_verdict"] == empty_tahoe["mechanism_verdict"] == "well_characterized"
    assert empty_tahoe["tahoe_perturbation_class"] is None
    assert empty_tahoe["tahoe_n_perturbing_drugs"] is None
