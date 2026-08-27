"""Phase 4 — invert primacy: the presence narrator LEADS with the signal vector and demotes the
collapsed presence_verdict to a trailing compressed label. Deterministic (prompt-string) assertions —
no Bedrock. The verdict token is still present (nothing dropped); only its POSITION + framing change.
Verdict-INERT: build_user_prompt never touches the spine.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import synthesis as SYN  # noqa: E402


def _decision():
    return {
        "target": "EPCAM", "indication": "COADREAD", "cards": [],
        "headline": {
            "presence_verdict": "tumor_broadly_expressed", "driving_rule_id": "tumor-expression-broadly-high-supportive",
            "claim_vector": {
                "A": {"signal": "strong", "corroboration": "high", "evidence": "99.7th all-gene pct"},
                "B": {"signal": "absent", "corroboration": "moderate", "evidence": "DGE flat"},
                "C": {"signal": "strong", "corroboration": "high", "evidence": "malignant 0.89"},
                "D": {"signal": "moderate", "corroboration": "high", "evidence": "multi-cohort"},
            },
        },
    }


def test_signal_vector_leads_verdict_trails():
    p = SYN.build_user_prompt(_decision())
    assert "SIGNAL VECTOR" in p and "COLLAPSED VERDICT" in p
    # signals lead; the collapsed verdict is demoted to the tail
    assert p.index("SIGNAL VECTOR") < p.index("COLLAPSED VERDICT")
    assert p.index("signal=strong") < p.index("presence_verdict:")


def test_verdict_still_present_nothing_dropped():
    p = SYN.build_user_prompt(_decision())
    assert "tumor_broadly_expressed" in p           # verdict retained, just repositioned
    assert "tumor-expression-broadly-high-supportive" in p


def test_system_prompt_orders_signals_first():
    s = SYN._SYSTEM.lower()
    assert "lead with the ranked signal vector" in s
    assert "compressed label" in s
