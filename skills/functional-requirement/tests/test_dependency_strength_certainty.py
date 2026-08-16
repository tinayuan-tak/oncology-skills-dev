"""Step-3 reference axis: dependency (strength, certainty) — validated BY CONSTRUCTION.

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
    assert rc._corroboration_from_concordance("concordant_dependent") == "high"
    assert rc._corroboration_from_concordance("discordant") == "low"
    assert rc._corroboration_from_concordance(None) == "medium"


def test_certainty_weakest_link_by_construction(monkeypatch):
    vals = {"n_cell_lines_evaluated": 40, "fraction_strongly_dependent": 0.6}
    monkeypatch.setattr(rc, "get_card_field", lambda cards, cid, f: vals.get(f))

    # well-powered + concordant → high
    sc = rc._dependency_strength_certainty({}, "strongly_dependent", "concordant_dependent")
    assert sc["certainty"]["level"] == "high" and sc["strength"] == "strong_positive"
    assert sc["certainty"]["unknown_mass"] == 0.1

    # thin n → coverage low → weakest-link low (even if concordant)
    vals["n_cell_lines_evaluated"] = 3
    sc = rc._dependency_strength_certainty({}, "lineage_selective", "concordant_dependent")
    assert sc["certainty"]["coverage"] == "low" and sc["certainty"]["level"] == "low"

    # discordant → corroboration low → weakest-link low (even if well-powered)
    vals["n_cell_lines_evaluated"] = 40
    sc = rc._dependency_strength_certainty({}, "lineage_selective", "discordant")
    assert sc["certainty"]["corroboration"] == "low" and sc["certainty"]["level"] == "low"

    # insufficient verdict → level forced low, strength none
    sc = rc._dependency_strength_certainty({}, "insufficient", "concordant_dependent")
    assert sc["certainty"]["level"] == "low" and sc["strength"] == "none"
