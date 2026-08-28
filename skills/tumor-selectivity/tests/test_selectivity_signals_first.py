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
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _decision():
    return {"target": "MSLN", "indication": "OV", "cards": [],
            "headline": {"selectivity_class": "tumor_selective", "dominant_direction": "up", "discordant": False,
                         "claim_vector": {
                             "WIN": {"signal": "strong", "corroboration": "high", "evidence": "window clean"},
                             "SAFE": {"signal": "moderate", "corroboration": "moderate", "evidence": "safe"}}}}


def test_composite_in_strength_certainty():
    ts = _ts()
    sc = ts._strength_certainty([], verdict_pair=("tumor_selective", None))
    assert "composite" in sc and 0.0 <= sc["composite"] <= 1.0
    assert "composite_basis" in sc
