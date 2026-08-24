"""tp_gates exists-safe-modality (VERDICT_REPRESENTATION.md Layer-2b/3): the safety WT-loss concern
(now emitted RAW by the resolver) is cleared at the gate iff the per-modality safety verdict shows an
admissible safe channel. Verifies the swap is behavior-PRESERVING for nomination: GoF point-mutation
drivers are rescued (stay nominable), amplification-driven / non-GoF constrained targets are NOT."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tp_gates

_HIT = [{"short": "safety", "verdict": "highly_constrained_safety_concern", "action": "hold"}]

# GoF point-mutation driver (KRAS-shape): eligible, not disqualified.
_GOF = [{"rule_id": "highly-constrained-safety-warning"},
        {"rule_id": "activating-driver-role-safety-context"},
        {"rule_id": "oncogene-role-safety-context"}]
# Amplification-driven oncogene (ERBB2-shape): eligible role BUT disqualified (no selectable point mut).
_AMP = _GOF + [{"rule_id": "copy-number-amplified-oncogene-safety-context"}]
# Non-GoF constrained (TP53-shape): concern only, no allele-selective eligibility.
_NONGOF = [{"rule_id": "highly-constrained-safety-warning"}]


def _survives(fired, modality=None):
    survivors, supp = tp_gates._suppressed_gate_hits(
        list(_HIT), {"safety": {"fired": fired, "verdict": ("highly_constrained_safety_concern", "x")}},
        modality)
    return any(h["short"] == "safety" for h in survivors), supp


def test_gof_point_mutation_rescued():
    survives, supp = _survives(_GOF)
    assert not survives, "GoF driver safety hold should be cleared (small_molecule=conditional exists)"
    assert any(s.get("suppressed_by", {}).get("kind") == "exists_safe_modality" for s in supp)


def test_amplification_driven_not_rescued():
    survives, _ = _survives(_AMP)
    assert survives, "amplification-driven oncogene has no allele-selective escape → hold must stand"


def test_nongof_constrained_not_rescued():
    survives, _ = _survives(_NONGOF)
    assert survives, "non-GoF constrained target has no safe modality → hold must stand"


def test_degrader_scoped_run_keeps_hold():
    # --modality degrader: the degrader channel engages WT → hold stands even for a GoF driver.
    survives, _ = _survives(_GOF, modality="degrader")
    assert survives, "degrader-scoped run must keep the WT-loss hold (degrader depletes WT)"


def test_sm_scoped_run_rescued():
    survives, _ = _survives(_GOF, modality="small_molecule")
    assert not survives, "small_molecule-scoped GoF driver is allele-selective-rescuable"
