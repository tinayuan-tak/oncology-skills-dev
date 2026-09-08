"""Guard A — resolver verdicts must stay classified by their Python consumers.

Bug class: a new verdict is added to a target-contracts resolver YAML, but a stale Python
consumer (an annotation whitelist / note-gate) is never updated, so a real, reachable verdict
silently falls through a branch that assumes it cannot occur. Two confirmed instances:
  - functional-requirement._DEPENDENCY_CALL_VERDICTS omitted partner_conditional_dependent
  - on-target-safety-liability._MECHANISM_MISMATCH_VERDICTS omitted wt_human_genetics_mechanism_mismatch
These tests read each resolver's verdict enum and assert the consumer sets stay exhaustive/aligned,
so the next such omission fails in CI instead of shipping. Skips cleanly when target-contracts is
not checked out (load_resolver returns None).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _skills_common.resolver import load_resolver
from _test_support import load_run_py

SKILLS_DIR = Path(__file__).resolve().parent.parent


def _resolver_verdicts(gate: str):
    """The full set of verdicts a resolver spec can emit (every rung + the default)."""
    spec = load_resolver(gate)
    if not isinstance(spec, dict):
        return None
    vs = {
        r["verdict"] for r in (spec.get("resolve") or []) if isinstance(r, dict) and isinstance(r.get("verdict"), str)
    }
    if isinstance(spec.get("default"), str):
        vs.add(spec["default"])
    return vs or None


def _load_skill_run(skill_name: str):
    return load_run_py(SKILLS_DIR / skill_name, f"_guarda_{skill_name.replace('-', '_')}_run")


_DEP = _resolver_verdicts("dependency")
_SAF = _resolver_verdicts("safety")


@pytest.mark.skipif(_DEP is None, reason="dependency.resolver.yaml unavailable (target-contracts not checked out)")
def test_dependency_verdicts_are_exhaustively_classified():
    fr = _load_skill_run("functional-requirement")
    calls = set(fr._DEPENDENCY_CALL_VERDICTS)
    noncalls = set(fr._NON_CALL_VERDICTS)
    assert calls.isdisjoint(noncalls), f"verdict in BOTH call and non-call sets: {sorted(calls & noncalls)}"
    unclassified = _DEP - calls - noncalls
    assert not unclassified, (
        f"dependency.resolver.yaml emits verdict(s) {sorted(unclassified)} that "
        f"functional-requirement/run.py classifies as NEITHER a call nor a non-call. Add each to "
        f"_DEPENDENCY_CALL_VERDICTS (a real dependency call) or _NON_CALL_VERDICTS (predictability "
        f"annotation stays neutral)."
    )
    stale = (calls | noncalls) - _DEP
    assert not stale, f"consumer lists verdict(s) no longer in dependency.resolver.yaml: {sorted(stale)}"


@pytest.mark.skipif(_SAF is None, reason="safety.resolver.yaml unavailable (target-contracts not checked out)")
def test_safety_mechanism_mismatch_set_matches_resolver():
    saf = _load_skill_run("on-target-safety-liability")
    by_name = {v for v in _SAF if "mechanism_mismatch" in v}
    # RETIRED 2026-08-24 (VERDICT_REPRESENTATION.md Layer-2b/3): the role-proxy scalar mutant-selective
    # downgrade was removed from safety.resolver.yaml — the resolver emits the raw WT-loss concern and
    # the modality-conditional downgrade moved to tp_gates exists-safe-modality. Guard now asserts the
    # resolver emits ZERO *_mechanism_mismatch verdicts and the consumer set is correspondingly empty.
    assert not by_name, (
        f"expected ZERO *_mechanism_mismatch verdicts post-retirement, found {by_name} — a scalar "
        f"role-proxy downgrade has crept back; modality-conditionality belongs in the per-modality verdict."
    )
    assert set(saf._MECHANISM_MISMATCH_VERDICTS) == by_name == set(), (
        f"_MECHANISM_MISMATCH_VERDICTS {set(saf._MECHANISM_MISMATCH_VERDICTS)} must be empty post-retirement."
    )
