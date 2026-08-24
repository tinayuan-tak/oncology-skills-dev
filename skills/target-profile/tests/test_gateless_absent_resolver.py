"""Gateless axis + absent resolver → degrade, don't abort the composed run (2026-08-24).

Regression for the exit-1 crash a `target-profile --verdict-only` run hit when the target-contracts
checkout predated a newly-merged GATELESS resolver (cis_coherence, added 2026-08-20). resolve_or_raise
fires a "resolver spec missing" RuntimeError, which the fan-out re-raised at fut.result() → the WHOLE
composed run died, even though cis_coherence is verdict-inert to the nomination spine.

_gateless_absent_resolver is the narrow swallow-decision: True IFF the axis is GATELESS (absent from
_SHORT_TO_GATE, so it can never move the spine) AND the RuntimeError is the specific absent-contract
one. It must NOT swallow (a) errors on verdict-bearing gates, nor (b) any other RuntimeError — those
are real faults that must stay fail-loud.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import tp_common  # noqa: E402,F401 — puts the skills root on sys.path so `_skills_common` imports
import tp_fanout  # noqa: E402

_MISSING = RuntimeError(
    "cis_coherence resolver spec missing "
    "(target-contracts/resolvers/cis_coherence.resolver.yaml) — the verdict source of truth is absent.")


def test_gateless_axis_absent_resolver_is_swallowed():
    # cis_coherence / combination_vulnerability / target_intrinsic are all absent from _SHORT_TO_GATE.
    assert "cis_coherence" not in tp_fanout._SHORT_TO_GATE
    assert tp_fanout._gateless_absent_resolver("cis_coherence", _MISSING) is True


def test_gating_axis_absent_resolver_stays_fail_loud():
    # A verdict-bearing gate (in _SHORT_TO_GATE) must NEVER degrade — its verdict drives the spine.
    for gate_short in tp_fanout._SHORT_TO_GATE:
        assert tp_fanout._gateless_absent_resolver(gate_short, _MISSING) is False


def test_other_runtime_error_on_gateless_axis_stays_fail_loud():
    # A genuine sub-skill fault (different message) is a real bug, not an absent contract — propagate.
    real_fault = RuntimeError("cis_coherence: card reader blew up (KeyError 'value')")
    assert tp_fanout._gateless_absent_resolver("cis_coherence", real_fault) is False
