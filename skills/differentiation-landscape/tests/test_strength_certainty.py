"""differentiation (strength, certainty) sidecar — CERTAINTY_MODEL. Coverage+unknown_mass only
(corroboration unmeasured until the TCGA<->GENIE per-source concordance field is emitted). Verdict-inert."""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

diff = load_run_py(Path(__file__).resolve().parent.parent, "diff_run_strength")


def _cards(n_pairs=None):
    return [{"card_id": "co-mutation-and-mutual-exclusivity",
             "summary": {"n_pairs_panel_intersect_eligible": n_pairs}}] if n_pairs is not None else \
           [{"card_id": "co-mutation-and-mutual-exclusivity", "summary": {}}]


def test_strong_pattern_well_powered():
    sc = diff._strength_certainty(_cards(n_pairs=80), verdict_pair=("strong_cooccurring", "x"))
    assert sc["strength"] == "strong_pattern"          # pattern TYPE, informational (not good/bad)
    assert sc["certainty"]["coverage"] == "high"        # 80 poolable pairs
    assert sc["certainty"]["corroboration"] == "unmeasured"
    assert sc["certainty"]["level"] == "high"           # = coverage (corroboration drops out)
    assert sc["certainty"]["unknown_mass"] == 0.0


def test_thin_power_is_low():
    sc = diff._strength_certainty(_cards(n_pairs=4), verdict_pair=("modest_cooccurring", "x"))
    assert sc["strength"] == "moderate_pattern"
    assert sc["certainty"]["coverage"] == "low"
    assert sc["certainty"]["level"] == "low"


def test_ns_verdict_none_and_low():
    sc = diff._strength_certainty(_cards(n_pairs=80), verdict_pair=("ns", "x"))
    assert sc["strength"] == "none"
    assert sc["certainty"]["level"] == "low"


def test_card_absent_unknown_mass_one():
    sc = diff._strength_certainty([], verdict_pair=("data_unavailable", None))
    assert sc["certainty"]["unknown_mass"] == 1.0
    assert sc["certainty"]["level"] == "low"
