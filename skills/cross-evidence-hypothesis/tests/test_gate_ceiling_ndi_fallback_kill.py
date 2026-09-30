"""`not_dependent_in_indication` (ndi) must be a kill token on BOTH the fallback kill-scan
AND in `_NON_DEPENDENT_TOKENS`.

Regression for #1606. ndi is the corpus-dominant dependency veto token (325/504 carry it as
the dependency sub-verdict; disposition `gated` in target-contracts nomination_verdict_gate.yaml).
It was missing from two hardcoded sets in hypothesis_core.py:

(A) The FALLBACK kill-scan (the path taken when `hard_gates` is absent/empty) only scanned
    `{"pan_essential_killer", "non_dependent"}`, so a fallback-routed package carrying an ndi
    dependency veto LOST it — ceiling fail-OPEN from `declined` to advanceable. The hard_gates
    loop keys the veto on `short in _VETO_GATE_AXES` and DID catch ndi, so the two paths
    disagreed on the framework's most common dependency veto.

(B) `_NON_DEPENDENT_TOKENS` (the mechanism-conditioning set) omitted ndi, so the
    mutant-selective mechanism-exclusion on the fired-veto path was skipped for ndi.

Dormant on the 20260920 corpus (all 504 packages carry hard_gates; 0 fallback hits, 0 combo
hits) — these tests exercise the paths directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # skills/
sys.path.insert(0, str(_ROOT / "cross-evidence-hypothesis" / "scripts"))

import hypothesis_core as hc  # noqa: E402


def _fallback_pkg(*, safety=None, svbm=None):
    """A package with NO hard_gates block (fallback path) whose dependency sub-verdict is ndi.
    `svbm`, when given, is set as the safety sub-verdict's `safety_verdict_by_modality` block (the
    post-v2.0.0 mutant-selective/allele-selective-escape signal, #1576 — the retired
    `wt_*_mechanism_mismatch` scalar `safety` token no longer carries it)."""
    safety_entry = {"verdict": safety}
    if svbm is not None:
        safety_entry["safety_verdict_by_modality"] = svbm
    return {
        "synthesis": {
            "sub_verdicts": {
                "safety": safety_entry,
                "dependency": {"verdict": "not_dependent_in_indication"},
            },
            "recommendation_gate": {
                # no hard_gates key at all -> fallback kill-scan
                "fired": False,
                "suppressed_vetoes": [],
            },
        }
    }


def test_ndi_on_fallback_path_is_caught():
    """The defect case: a fallback-routed package carrying an ndi dependency veto must be caught
    (fail-CLOSED) -> declined, not fail-open to advanceable."""
    g = hc.gate_ceiling(_fallback_pkg())
    assert g["hard_gates_present"] is False, g
    assert g["ceiling"] == "declined", g
    assert "dependency:not_dependent_in_indication" in g["active_vetoes"], g


def test_ndi_on_fallback_path_mechanism_excluded_for_mutant_selective():
    """Mirror the hard_gates path: an ndi veto on a mutant-selective driver — signalled (post-v2.0.0
    retirement of the wt_*_mechanism_mismatch scalar safety token, #1576) by the per-modality safety
    action clearing to `conditional` — is mechanism-excluded, not a fallback kill."""
    svbm = {"small_molecule": {"action": "conditional", "wt_engagement": "conditional", "driving_rules": []}}
    g = hc.gate_ceiling(_fallback_pkg(safety="human_genetics_safety_concern", svbm=svbm), modality="small_molecule")
    assert g["hard_gates_present"] is False, g
    assert "dependency:not_dependent_in_indication" not in g["active_vetoes"], g


def test_ndi_in_non_dependent_tokens():
    """`_NON_DEPENDENT_TOKENS` (consumed by the mechanism-conditioning exclusion) must include ndi,
    so a fired ndi veto on a mutant-selective driver is mechanism-excluded on the hard_gates path."""
    assert "not_dependent_in_indication" in hc._NON_DEPENDENT_TOKENS
