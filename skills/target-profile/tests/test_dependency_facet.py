"""P2 phase 3-claim: the dependency claim-vector facet plumbing in the composed target-profile.
  1. _dependency_facet reads sub_results['dependency']['synthesis_facet'] (and is None-safe);
  2. functional-requirement's `_synthesis_facet` carries the SIGNAL decomposition (claim_vector +
     key_signals) but NOT the per-axis certainty roll-up — that is the separate certainty_by_axis
     sidecar (reconciliation D1: signal half vs certainty half live in distinct blocks).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from tp_facets import _dependency_facet  # noqa: E402

_FR_RUN = SCRIPTS.parent.parent / "functional-requirement" / "scripts" / "run.py"


def _load_fr():
    sys.path.insert(0, str(_FR_RUN.resolve().parents[2]))   # skills/
    spec = importlib.util.spec_from_file_location("fr_run_facet", _FR_RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_dependency_facet_reads_synthesis_facet_from_sub_results():
    sub_results = {"dependency": {"skill_dir": "functional-requirement",
                                  "synthesis_facet": {"dependency_verdict": "lineage_selective"}}}
    assert _dependency_facet(sub_results) == {"dependency_verdict": "lineage_selective"}
    # None-safe when absent / no dependency sub-skill
    assert _dependency_facet({"dependency": {}}) is None
    assert _dependency_facet({}) is None
    assert _dependency_facet(None) is None


def test_facet_carries_signal_not_certainty():
    """The dependency facet is the SIGNAL half (claim_vector + key_signals); the per-axis certainty
    roll-up (strength_certainty) is the SEPARATE certainty_by_axis sidecar, NOT this facet."""
    fr = _load_fr()
    keys = set(fr._SYNTHESIS_FACET_KEYS)
    assert {"claim_vector", "key_signals", "dependency_verdict"} <= keys
    # de-dup discipline: the certainty object does NOT ride the signal facet
    assert "strength_certainty" not in keys
