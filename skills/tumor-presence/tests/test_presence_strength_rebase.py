"""Re-based composite STRENGTH (PR-2): strength is derived from the integrated claim_vector (peak
positive signal) floored by presence_state, NOT from the collapsed one-word verdict. This fixes the
ALB-style false-strong — a single tumor-vs-adjacent contrast wins the ladder (verdict
`strongly_upregulated_in_tumor`) but the integrated signal package is weak — which previously ranked
albumin at composite 1.0, ABOVE validated ERBB2. Verdict-INERT sidecar.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))                     # skills/
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))         # run.py
from _skills_common.presence_claims import presence_strength_from_state
import run as tp  # noqa: E402


def _cv(a, b, c, d):
    return {"A": {"signal": a}, "B": {"signal": b}, "C": {"signal": c}, "D": {"signal": d}}


# strong/moderate/weak/absent/negative/unmeasured
_ERBB2_CV = _cv("strong", "strong", "strong", "moderate")
_ERBB2_ST = {"present": "yes", "conflict": False}
_ALB_CV = _cv("absent", "weak", "absent", "weak")
_ALB_ST = {"present": "protein_only_rna_absent", "conflict": True}


def test_peak_signal_drives_strength():
    assert presence_strength_from_state({"present": "yes"}, _cv("strong", "absent", "absent", "absent")) == "strong_positive"
    assert presence_strength_from_state({"present": "yes"}, _cv("moderate", "weak", "absent", "absent")) == "moderate_positive"
    assert presence_strength_from_state({"present": "rna_only"}, _cv("weak", "absent", "absent", "absent")) == "weak_positive"


def test_presence_state_floors():
    assert presence_strength_from_state({"present": "no"}, _cv("strong", "strong", "strong", "strong")) == "negative"
    assert presence_strength_from_state({"present": "untested"}, _cv("strong", "strong", "strong", "strong")) == "none"
    # a protein<->RNA conflict is never strong, even with a strong claim signal
    assert presence_strength_from_state({"present": "rna_only_protein_absent", "conflict": True},
                                        _cv("strong", "strong", "strong", "strong")) == "weak_positive"


def test_alb_is_not_strong_despite_strong_upregulation_verdict():
    """The core fix: ALB's ladder verdict is strongly_upregulated_in_tumor, but its integrated signal
    package peaks at weak → the re-based strength is weak_positive, not strong_positive."""
    assert presence_strength_from_state(_ALB_ST, _ALB_CV) == "weak_positive"
    sc = tp._strength_certainty([], verdict_pair=("strongly_upregulated_in_tumor", "rid"),
                                claim_vector=_ALB_CV, presence_state=_ALB_ST)
    assert sc["strength"] == "weak_positive"          # was strong_positive under the verdict-keyed basis


def test_erbb2_outranks_alb_composite_regression():
    """ERBB2 (validated) must rank ABOVE ALB (contamination artifact). Under the OLD verdict-keyed
    strength both read strong_positive and ALB even tied/beat ERBB2 at composite 1.0."""
    erbb2 = tp._strength_certainty([], verdict_pair=("broadly_high_expression", "rid"),
                                   claim_vector=_ERBB2_CV, presence_state=_ERBB2_ST)
    alb = tp._strength_certainty([], verdict_pair=("strongly_upregulated_in_tumor", "rid"),
                                 claim_vector=_ALB_CV, presence_state=_ALB_ST)
    assert erbb2["strength"] == "strong_positive"
    assert alb["strength"] == "weak_positive"
    assert erbb2["composite"] > alb["composite"]


def test_falls_back_to_verdict_basis_without_vector():
    """Legacy 3-arg call (no claim_vector/presence_state) keeps the verdict-keyed strength, so any
    caller that hasn't migrated is unchanged."""
    sc = tp._strength_certainty([], verdict_pair=("strongly_upregulated_in_tumor", "rid"))
    assert sc["strength"] == "strong_positive"

# NOTE: standalone _headline emission of strength_certainty (with the re-based strength) is covered by
# the full-fixture replay suite (test_tumor_presence_replay.py) — _headline reads every card via the
# raise-on-missing get_card_field, so it needs the complete card set, not a synthetic stub.
