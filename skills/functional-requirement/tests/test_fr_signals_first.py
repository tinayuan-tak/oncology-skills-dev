"""Signals-first rollout for functional-requirement (mirrors the tumor-presence pilot):
the dependency narrator LEADS with the signal vector (verdict demoted to a trailing label) and the
strength_certainty sidecar emits a continuous composite. Verdict-INERT; deterministic assertions.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
RUN_PY = Path(__file__).resolve().parents[1] / "scripts" / "run.py"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import synthesis_dependency as SD          # noqa: E402
from _skills_common.signals_first import render_signal_vector, certainty_composite  # noqa: E402


def _fr():
    spec = importlib.util.spec_from_file_location("fr_run", RUN_PY)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _decision():
    return {"target": "KRAS", "indication": "COADREAD", "cards": [],
            "headline": {"dependency_verdict": "selective_dependent", "driving_rule_id": "rid",
                         "claim_vector": {
                             "DEP": {"signal": "strong", "corroboration": "high", "evidence": "Chronos -1.2"},
                             "SEL": {"signal": "moderate", "corroboration": "moderate", "evidence": "lineage"}}}}


def test_narrator_leads_with_signal_vector():
    p = SD.build_user_prompt(_decision())
    assert "SIGNAL VECTOR" in p and "COLLAPSED VERDICT" in p
    assert p.index("SIGNAL VECTOR") < p.index("COLLAPSED VERDICT")
    assert p.index("signal=strong") < p.index("dependency_verdict:")
    assert "selective_dependent" in p                      # verdict retained, just repositioned


def test_composite_in_strength_certainty():
    fr = _fr()
    cards = [{"card_id": "pan-cancer-crispr-dependency-distribution",
              "summary": {"n_cell_lines_evaluated": 500, "fraction_strongly_dependent": 0.4}}]
    sc = fr._dependency_strength_certainty(cards, "selective_dependent", None)
    assert "composite" in sc and 0.0 <= sc["composite"] <= 1.0
    assert "composite_basis" in sc


def test_shared_helpers():
    assert certainty_composite("strong_positive", "high") == 1.0
    assert certainty_composite("none", "high") == 0.0
    assert certainty_composite("broad_nonselective", "low") == 0.5   # broad dependency, low certainty
    block = render_signal_vector({"DEP": {"signal": "strong", "corroboration": "high", "evidence": "x"},
                                  "_disclaimer": "ignore me"})
    assert "DEP" in block and "_disclaimer" not in block             # metadata keys skipped
