"""Reference axis: dependency (strength, certainty) — validated BY CONSTRUCTION.

Per CERTAINTY_MODEL.md, certainty needs NO outcome labels: it's a property of the evidence.
So we assert the construction rules directly — well-powered + concordant → high; thin-n →
low coverage; discordant → low corroboration; insufficient verdict → low. Additive + verdict-inert.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
sys.path.insert(0, str(_RUN.resolve().parents[3]))  # skills/  → _skills_common


def _load():
    spec = importlib.util.spec_from_file_location("fr_run", _RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rc = _load()


def test_strength_maps_verdict_class():
    assert rc._dependency_strength("strongly_dependent") == "strong_positive"
    assert rc._dependency_strength("lineage_selective") == "moderate_positive"
    assert rc._dependency_strength("pan_essential_killer") == "broad_nonselective"
    assert rc._dependency_strength("non_dependent") == "negative"
    assert rc._dependency_strength("insufficient") == "none"


def test_coverage_and_corroboration_thresholds():
    assert rc._coverage_from_n(40) == "high"
    assert rc._coverage_from_n(10) == "medium"
    assert rc._coverage_from_n(3) == "low"
    assert rc._coverage_from_n(None) == "low"
    # corroboration is now VERDICT-DISJOINT Broad↔Sanger cross-consortium (CERTAINTY_MODEL),
    # NOT CRISPR↔RNAi concordance. Independent consortia agreeing (dependent OR non-dependent) → high;
    # discordant → low; single consortium → medium; absent → unmeasured (never a fabricated medium).
    assert rc._corroboration_from_cross_consortium("concordant_dependent") == "high"
    assert rc._corroboration_from_cross_consortium("concordant_non_dependent") == "high"
    assert rc._corroboration_from_cross_consortium("discordant") == "low"
    assert rc._corroboration_from_cross_consortium("single_consortium_only") == "medium"
    assert rc._corroboration_from_cross_consortium("data_unavailable") == "unmeasured"
    assert rc._corroboration_from_cross_consortium(None) == "unmeasured"


def _card(card_id, primary_class="ok_class_value", **extra):
    """A minimal resolved-card dict with a REAL primary (so _unknown_mass counts it as available)."""
    return {"card_id": card_id, "summary": {"some_class": primary_class}, **extra}


def _all_decision_cards_present():
    return [_card(cid) for cid in rc._DECISION_RELEVANT_CARDS]


def test_certainty_weakest_link_by_construction(monkeypatch):
    vals = {"n_cell_lines_evaluated": 40, "fraction_strongly_dependent": 0.6}
    monkeypatch.setattr(rc, "get_card_field", lambda cards, cid, f: vals.get(f))
    full = _all_decision_cards_present()   # all decision cards available → unknown_mass 0.0

    # well-powered + cross-consortium replicated → high
    sc = rc._dependency_strength_certainty(full, "strongly_dependent", "concordant_dependent")
    assert sc["certainty"]["level"] == "high" and sc["strength"] == "strong_positive"
    assert sc["certainty"]["unknown_mass"] == 0.0

    # thin n → coverage low → weakest-link low (even if cross-consortium replicated)
    vals["n_cell_lines_evaluated"] = 3
    sc = rc._dependency_strength_certainty(full, "lineage_selective", "concordant_dependent")
    assert sc["certainty"]["coverage"] == "low" and sc["certainty"]["level"] == "low"

    # cross-consortium discordant → corroboration low → weakest-link low (even if well-powered)
    vals["n_cell_lines_evaluated"] = 40
    sc = rc._dependency_strength_certainty(full, "lineage_selective", "discordant")
    assert sc["certainty"]["corroboration"] == "low" and sc["certainty"]["level"] == "low"

    # single-consortium (unmeasured corroboration) DROPS OUT of the min — level rests on coverage,
    # NOT punished to low as if it were disagreement (absence ≠ disagreement).
    sc = rc._dependency_strength_certainty(full, "lineage_selective", "data_unavailable")
    assert sc["certainty"]["corroboration"] == "unmeasured" and sc["certainty"]["level"] == "high"

    # insufficient verdict → level forced low, strength none
    sc = rc._dependency_strength_certainty(full, "insufficient", "concordant_dependent")
    assert sc["certainty"]["level"] == "low" and sc["strength"] == "none"


def test_unknown_mass_is_measured_coverage_gap():
    """unknown_mass = fraction of decision-relevant cards blind this run — measured, not a
    level-lookup. A card absent / _missing / data_unavailable-primary counts as blind."""
    cards = _all_decision_cards_present()
    assert rc._unknown_mass(cards) == 0.0
    # drop two cards entirely (never measured) → 2/7 blind
    fewer = cards[:-2]
    assert rc._unknown_mass(fewer) == round(2 / 7, 3)
    # a present-but-data_unavailable primary counts as blind
    cards2 = _all_decision_cards_present()
    cards2[0] = {"card_id": rc._DECISION_RELEVANT_CARDS[0], "summary": {"dependency_class": "data_unavailable"}}
    assert rc._unknown_mass(cards2) == round(1 / 7, 3)
    # a _missing flag counts as blind
    cards3 = _all_decision_cards_present()
    cards3[1]["_missing"] = True
    assert rc._unknown_mass(cards3) == round(1 / 7, 3)
    assert rc._unknown_mass([]) == 1.0


def test_corroboration_is_verdict_disjoint(monkeypatch):
    """Disjointness guard (CERTAINTY_MODEL): corroboration must track the VERDICT-DISJOINT
    cross-consortium signal and be INVARIANT to the CRISPR↔RNAi concordance that resolves the verdict.
    Regression guard against re-coupling certainty to the verdict driver."""
    vals = {"n_cell_lines_evaluated": 40, "fraction_strongly_dependent": 0.6}
    monkeypatch.setattr(rc, "get_card_field", lambda cards, cid, f: vals.get(f))
    full = _all_decision_cards_present()
    # corroboration varies with cross_consortium_class …
    assert rc._dependency_strength_certainty(full, "lineage_selective", "concordant_dependent")["certainty"]["corroboration"] == "high"
    assert rc._dependency_strength_certainty(full, "lineage_selective", "discordant")["certainty"]["corroboration"] == "low"
    # … and the function no longer reads the concordance card at all for corroboration.
    assert not hasattr(rc, "_corroboration_from_concordance")
