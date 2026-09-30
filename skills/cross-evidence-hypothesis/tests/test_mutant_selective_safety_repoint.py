"""Regression for #1576: `_MUTANT_SELECTIVE_SAFETY` matched only the `wt_human_genetics_mechanism_mismatch`
/ `wt_constraint_mechanism_mismatch` scalar `safety` tokens, both RETIRED from the safety resolver at
v2.0.0 — the real resolver never emits them, so the mutant-selective mechanism-conditioning of the
dependency veto (gate_ceiling AND coherence_violations) was permanently dead in every live package.

The fix repoints both consumers to the post-retirement source of the same signal: the per-modality
safety action clearing to `conditional` (the allele-selective-escape channel, mirrored by
`_SAFETY_MODALITY_SAFE_ACTIONS`).

These tests pin the PRODUCTION-SHAPED failure mode directly: a package carrying ONLY the (now-dead)
scalar token, with no per-modality block, must NOT get the mutant-selective relief (proves the old
path is truly gone, not just re-routed); a package carrying the per-modality clear DOES get the relief
(proves the new path fires).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # skills/
sys.path.insert(0, str(_ROOT / "cross-evidence-hypothesis" / "scripts"))

import hypothesis_core as hc  # noqa: E402


def _hard_gates_pkg(safety_entry):
    return {
        "synthesis": {
            "sub_verdicts": {"safety": safety_entry},
            "recommendation_gate": {
                "hard_gates": [
                    {
                        "short": "dependency",
                        "verdict": "non_dependent",
                        "live_verdict": "non_dependent",
                        "status": "fired",
                    },
                    {"short": "safety", "verdict": None, "live_verdict": None, "status": "latent"},
                ],
                "suppressed_vetoes": [],
            },
        }
    }


def test_retired_scalar_token_alone_gives_no_relief_gate_ceiling():
    """A package carrying ONLY the retired scalar token (no safety_verdict_by_modality block) must
    NOT get mutant-selective relief — proves the dead `_MUTANT_SELECTIVE_SAFETY` scalar path is gone,
    not merely re-routed to something else that still keys off the retired token."""
    g = hc.gate_ceiling(_hard_gates_pkg({"verdict": "wt_human_genetics_mechanism_mismatch"}), modality="small_molecule")
    assert "dependency:non_dependent" in g["active_vetoes"], g
    assert not any(t.startswith("dependency:") for t in g["excluded"]), g


def test_modality_clear_gives_relief_gate_ceiling():
    """The post-retirement source: a per-modality safety action of `conditional` for this channel IS
    the mutant-selective/allele-selective-escape signal and mechanism-excludes the dependency veto."""
    svbm = {"small_molecule": {"action": "conditional", "wt_engagement": "conditional", "driving_rules": []}}
    g = hc.gate_ceiling(
        _hard_gates_pkg({"verdict": "human_genetics_safety_concern", "safety_verdict_by_modality": svbm}),
        modality="small_molecule",
    )
    assert "dependency:non_dependent" not in g["active_vetoes"], g
    assert any(t.startswith("dependency:") for t in g["excluded"]), g


def test_retired_scalar_token_alone_gives_no_relief_coherence():
    """Same production-shaped check for coherence_violations: the retired scalar token, with no sv/
    modality passed, gives no relief (fail-closed default)."""
    clauses = {"therapeutic_hypothesis": {"support": ["dependency"], "surfaced": []}}
    conv = {"safety": "wt_human_genetics_mechanism_mismatch", "dependency": "non_dependent"}
    v = hc.coherence_violations(clauses, conv, [], [], set())
    assert v, "retired scalar safety token must not silence the dependency contradiction"


def test_modality_clear_gives_relief_coherence():
    clauses = {"therapeutic_hypothesis": {"support": ["dependency"], "surfaced": []}}
    conv = {"safety": "human_genetics_safety_concern", "dependency": "non_dependent"}
    sv = {
        "safety": {
            "verdict": "human_genetics_safety_concern",
            "safety_verdict_by_modality": {
                "small_molecule": {"action": "conditional", "wt_engagement": "conditional", "driving_rules": []},
            },
        }
    }
    v = hc.coherence_violations(clauses, conv, [], [], set(), sv=sv, modality="small_molecule")
    assert not v, f"modality-cleared mutant-selective driver should be benign, got {v}"


def test_mutant_selective_safety_frozenset_removed():
    """The dead frozenset itself is gone (not merely unused) — confirms the cleanup half of #1576."""
    assert not hasattr(hc, "_MUTANT_SELECTIVE_SAFETY")
