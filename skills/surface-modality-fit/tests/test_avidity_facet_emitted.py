"""Drift-guard: the surface-colocalization-avidity facet (same-cell avidity + tumor-vs-NORMAL
selectivity window for AND-gate bispecifics) must keep flowing through surface-modality-fit's
_headline, and must NEVER perturb the verdict. Wired 2026-08-20 (un-retiring a partially-true
2026-08-19 supersession: bispecific-pair-scan covers tumor per-pair avidity ONLY; this card uniquely
adds the normal selectivity window + target-centric best-partner rollup). Its 5 rules are in NO
resolver → additive signal facet, verdict byte-stable. Mirror of test_tahoe_facet_emitted.py.

Offline: pure _headline over synthetic cards, no S3/reader. _headline reads several cards via
get_card_field, which RAISES on a missing card_id — so a valid call must supply every card the skill
declares (me.CARDS); we populate only the avidity one.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

me = load_run_py(Path(__file__).resolve().parent.parent, "smf_run")

_AVIDITY_SUMMARY = {
    "samecell_avidity_class": "same_cell_coordinated",
    "best_partner": "MUC1",
    "best_enrichment_median": 1.8,
    "best_both_fraction_median": 0.41,
    "n_partners_tested": 6,
    "n_coordinated_partners": 2,
    "window_verdict": "window_open",
    "window_best_partner": "MUC1",
    "selectivity_margin": 0.39,
    "n_window_open": 1,
    "normal_liability_locus": None,
}


def _cards(avidity_summary):
    """All cards the skill declares (empty summaries) with the avidity card populated — so every
    get_card_field lookup in _headline resolves."""
    cards = [{"card_id": cid, "summary": {}} for cid in me.CARDS]
    for c in cards:
        if c["card_id"] == "surface-colocalization-avidity":
            c["summary"] = dict(avidity_summary)
    return cards


def test_avidity_card_registered():
    """facet-drop guard: the card must stay in the skill's CARDS list."""
    assert "surface-colocalization-avidity" in me.CARDS


def test_headline_emits_avidity_fields():
    h = me._headline(_cards(_AVIDITY_SUMMARY), [], ("both_viable", "some-rule"))
    assert h["samecell_avidity_class"] == "same_cell_coordinated"
    assert h["samecell_best_partner"] == "MUC1"
    assert h["samecell_best_both_fraction_median"] == 0.41
    assert h["samecell_n_coordinated_partners"] == 2
    # the tumor-vs-NORMAL selectivity window — the capability unique to this card
    assert h["samecell_window_verdict"] == "window_open"
    assert h["samecell_selectivity_margin"] == 0.39
    assert h["samecell_n_window_open"] == 1
    assert "samecell_normal_liability_locus" in h  # emitted even when None


def test_avidity_is_verdict_inert():
    """Display-only: surface_modality_verdict is identical with a populated vs empty avidity card, and
    every non-avidity headline key is byte-stable (the avidity fields are additive)."""
    vp = ("both_viable", "some-rule")
    with_av = me._headline(_cards(_AVIDITY_SUMMARY), [], vp)
    empty_av = me._headline(_cards({}), [], vp)
    assert with_av["surface_modality_verdict"] == empty_av["surface_modality_verdict"] == "both_viable"
    assert with_av["fit_class"] == empty_av["fit_class"]
    # avidity fields degrade to None (never raise) when the card data is absent
    assert empty_av["samecell_avidity_class"] is None
    assert empty_av["samecell_window_verdict"] is None
    # every NON-avidity key is unchanged between the two runs (the facet is purely additive)
    non_avidity = {k: v for k, v in with_av.items() if not k.startswith("samecell_")}
    for k, v in non_avidity.items():
        assert empty_av.get(k) == v, f"non-avidity headline key {k!r} changed when avidity card populated"
