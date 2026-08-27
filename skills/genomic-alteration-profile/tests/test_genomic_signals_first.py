"""Signals-first rollout for genomic-alteration-profile: narrator LEADS with the signal vector
(verdict demoted to a compressed label) + strength_certainty emits a composite. Verdict-INERT."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
RUN_PY = Path(__file__).resolve().parents[1] / "scripts" / "run.py"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import synthesis_genomic as SG          # noqa: E402


def _ga():
    spec = importlib.util.spec_from_file_location("ga_run", RUN_PY)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def _decision():
    return {"target": "ERBB2", "indication": "STAD", "cards": [],
            "headline": {"genomic_alteration_profile": "amplification_driven", "driving_rule_id": "rid",
                         "claim_vector": {
                             "CN": {"signal": "strong", "corroboration": "high", "evidence": "focal amp"},
                             "SNV": {"signal": "absent", "corroboration": "moderate", "evidence": "no recurrent"}}}}


def test_narrator_leads_with_signal_vector():
    p = SG.build_user_prompt(_decision())
    assert "SIGNAL VECTOR" in p and "COLLAPSED VERDICT" in p
    assert p.index("SIGNAL VECTOR") < p.index("COLLAPSED VERDICT")
    assert "signal=strong" in p
    assert "amplification_driven" in p


def test_composite_in_strength_certainty():
    ga = _ga()
    sc = ga._strength_certainty([], verdict_pair=("amplification_driven", None))
    assert "composite" in sc and 0.0 <= sc["composite"] <= 1.0
    assert "composite_basis" in sc
