"""Signals-first rollout for tumor-selectivity: narrator LEADS with the signal vector (verdict demoted
to a compressed label) + strength_certainty emits a continuous composite. Verdict-INERT; deterministic.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
RUN_PY = Path(__file__).resolve().parents[1] / "scripts" / "run.py"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


def _ts():
    spec = importlib.util.spec_from_file_location("ts_run", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _decision():
    return {
        "target": "MSLN",
        "indication": "OV",
        "cards": [],
        "headline": {
            "selectivity_class": "tumor_selective",
            "dominant_direction": "up",
            "discordant": False,
            "claim_vector": {
                "WIN": {"signal": "strong", "corroboration": "high", "evidence": "window clean"},
                "SAFE": {"signal": "moderate", "corroboration": "moderate", "evidence": "safe"},
            },
        },
    }


def test_composite_in_strength_certainty():
    ts = _ts()
    sc = ts._strength_certainty([], verdict_pair=("tumor_selective", None))
    assert "composite" in sc and 0.0 <= sc["composite"] <= 1.0
    assert "composite_basis" in sc


# ── #1776 veto-coverage certainty demotion + structured flag ─────────────────────────────────────
# A strong tvn card that alone drives certainty=high (concordant comparators, n>=10, CPTAC protein
# unmeasured so corroboration drops out of the min) — so any demotion is observable.
_STRONG_TVN = {
    "card_id": "tumor-vs-normal-selectivity",
    "summary": {"comparator_concordance": "concordant", "n_tumor": 20, "dominant_direction": "up"},
}


def _veto_cards(*, window="clean_window", sc_normal="not_essential", tphp="not_broad", stromal="not_confounded"):
    """The four verdict-moving veto cards with MEASURED (non-unavailable) class values. Pass a value of
    None or 'data_unavailable' for any arm to simulate that arm going blind (or drop the card entirely)."""
    return [
        {"card_id": "modality-therapeutic-window", "summary": {"therapeutic_window_class": window}},
        {"card_id": "sc-normal-celltype-expression", "summary": {"sc_normal_safety_essential_class": sc_normal}},
        {"card_id": "normal-tissue-protein-abundance-tphp", "summary": {"tphp_normal_protein_liability_class": tphp}},
        {"card_id": "tumor-scrna-celltype-expression", "summary": {"stromal_confound_class": stromal}},
    ]


def test_veto_coverage_fully_vetted_no_demotion():
    """A clean axis-A positive with all four veto arms MEASURED → fully_vetted, certainty NOT demoted."""
    ts = _ts()
    cards = [_STRONG_TVN] + _veto_cards()
    sc = ts._strength_certainty(cards, verdict_pair=("strong_tumor_selective", None))
    vc = sc["veto_coverage"]
    assert vc["status"] == "fully_vetted"
    assert vc["unvetted_arms"] == [] and vc["n_unvetted"] == 0
    assert sc["certainty"]["coverage"] == "high"
    assert sc["certainty"]["level"] == "high"  # no demotion on a measured clean pass


def test_veto_coverage_unvetted_demotes_one_band_and_names_arm():
    """A clean axis-A positive whose sc-normal veto arm is data_unavailable → unvetted, arm named,
    certainty demoted one band (high → medium). This is the core #1776 behaviour."""
    ts = _ts()
    cards = [_STRONG_TVN] + _veto_cards(sc_normal="data_unavailable")
    sc = ts._strength_certainty(cards, verdict_pair=("strong_tumor_selective", None))
    vc = sc["veto_coverage"]
    assert vc["status"] == "unvetted_for_normal_breadth_stromal_confound"
    assert "sc_normal" in vc["unvetted_arms"] and vc["n_unvetted"] == 1
    assert sc["certainty"]["coverage"] == "high"  # measured comparator breadth unchanged
    assert sc["certainty"]["level"] == "medium"  # but reported certainty is demoted one band


def test_veto_coverage_absent_cards_flag_all_four_arms():
    """A clean positive with NO veto cards resolved at all → every arm blind; the flag names all four."""
    ts = _ts()
    sc = ts._strength_certainty([_STRONG_TVN], verdict_pair=("field_effect_tumor_selective", None))
    vc = sc["veto_coverage"]
    assert vc["status"] == "unvetted_for_normal_breadth_stromal_confound"
    assert set(vc["unvetted_arms"]) == {"window", "sc_normal", "tphp_normal_protein", "sc_tumor_stromal"}
    assert vc["n_unvetted"] == 4
    assert sc["certainty"]["level"] == "medium"  # high (concordant tvn) demoted one band


def test_veto_coverage_fail_open_missing_card_does_not_relax_a_kill():
    """FAIL-OPEN: a fired veto (selective_but_broadly_normal) with a MISSING veto card must NOT be
    relaxed by this flag — status is not_applicable, and the demotion is a no-op on a non-positive
    verdict (the flag can only lower certainty on a clean pass, never clear or fabricate a KILL)."""
    ts = _ts()
    cards = [_STRONG_TVN] + _veto_cards(sc_normal="data_unavailable")
    kill = ts._strength_certainty(cards, verdict_pair=("selective_but_broadly_normal", None))
    vc = kill["veto_coverage"]
    assert vc["status"] == "not_applicable"  # a KILL is never re-opened by a coverage census
    # the KILL is a measured negative, so strength stays negative regardless of the census
    assert kill["strength"] == "negative"


def test_veto_coverage_demotion_only_moves_certainty_down():
    """The demotion is monotone-down: for every certainty band, the demoted band is never HIGHER."""
    ts = _ts()
    order = {"low": 0, "medium": 1, "high": 2}
    for band, demoted in ts._CERTAINTY_DEMOTE_ONE_BAND.items():
        assert order[demoted] <= order[band]
