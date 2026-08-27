"""Signals-first rollout for tractability-small-molecule: narrator LEADS with the signal vector
(POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER), verdicts demoted to compressed labels. Verdict-INERT.

NOTE: no `composite` here — tractability has NO strength_certainty sidecar (its certainty is
coverage-only, no verdict-disjoint corroborator by design), so the continuous ranking primitive the
other four lenses gained does not apply. Only the narrator inversion is in scope.
"""
from __future__ import annotations

from pathlib import Path
import sys

SKILLS_ROOT = Path(__file__).resolve().parents[2]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common import synthesis_tractability_sm as ST    # noqa: E402


def _decision():
    return {"target": "KRAS", "indication": "COADREAD", "cards": [],
            "headline": {"druggability_snapshot": "tractable", "driving_rule_id": "rid",
                         "degrader_snapshot": "degrader_plausible", "degrader_driving_rule_id": "rid2",
                         "degradability_machinery": "present",
                         "claim_vector": {
                             "POTENCY": {"signal": "strong", "corroboration": "high", "evidence": "nM"},
                             "DRUG": {"signal": "moderate", "corroboration": "moderate", "evidence": "tool cpd"}}}}


def test_narrator_leads_with_signal_vector():
    p = ST.build_user_prompt(_decision())
    assert "SIGNAL VECTOR" in p and "COLLAPSED VERDICT" in p
    assert p.index("SIGNAL VECTOR") < p.index("COLLAPSED VERDICT")
    assert "signal=strong" in p
    assert "tractable" in p                          # verdict retained, just repositioned/reframed
