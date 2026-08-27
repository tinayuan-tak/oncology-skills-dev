"""Signals-first rollout for surface-modality-fit: narrator LEADS with the signal vector (verdict
demoted to a compressed label) + strength_certainty emits a composite. Verdict-INERT."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
RUN_PY = Path(__file__).resolve().parents[1] / "scripts" / "run.py"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import synthesis_surface_modality as SM   # noqa: E402


def _sm():
    spec = importlib.util.spec_from_file_location("sm_run", RUN_PY)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _decision():
    return {"target": "FOLR1", "indication": "OV", "cards": [],
            "headline": {"surface_modality_verdict": "ADC_preferred", "fit_class": "ADC_preferred",
                         "driving_rule_id": "rid",
                         "claim_vector": {
                             "TOPOLOGY": {"signal": "strong", "corroboration": "high", "evidence": "type-I"},
                             "SAFETY": {"signal": "moderate", "corroboration": "moderate", "evidence": "ok"}}}}


def test_narrator_leads_with_signal_vector():
    p = SM.build_user_prompt(_decision())
    assert "SIGNAL VECTOR" in p and "COLLAPSED VERDICT" in p
    assert p.index("SIGNAL VECTOR") < p.index("COLLAPSED VERDICT")
    assert "signal=strong" in p
    assert "ADC_preferred" in p


def test_composite_in_strength_certainty():
    sm = _sm()
    sc = sm._strength_certainty([], verdict_pair=("ADC_preferred", None))
    assert "composite" in sc and 0.0 <= sc["composite"] <= 1.0
    assert "composite_basis" in sc
