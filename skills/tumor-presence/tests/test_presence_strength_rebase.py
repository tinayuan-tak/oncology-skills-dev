"""Re-based composite STRENGTH (PR-2): strength is derived from the integrated claim_vector (peak
positive signal) floored by presence_state, NOT from the collapsed one-word verdict. This fixes the
ALB-style false-strong — a single tumor-vs-adjacent contrast wins the ladder (verdict
`strongly_upregulated_in_tumor`) but the integrated signal package is weak — which previously ranked
albumin at composite 1.0, ABOVE validated ERBB2. Verdict-INERT sidecar.
"""

from pathlib import Path

from _skills_common.presence_claims import presence_strength_from_state
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_rebase")


def _cv(a, b, c, d):
    return {"A": {"signal": a}, "B": {"signal": b}, "C": {"signal": c}, "D": {"signal": d}}


# strong/moderate/weak/absent/negative/unmeasured
_ERBB2_CV = _cv("strong", "strong", "strong", "moderate")
_ERBB2_ST = {"present": "yes", "conflict": False}
_ALB_CV = _cv("absent", "weak", "absent", "weak")
_ALB_ST = {"present": "protein_only_rna_absent", "conflict": True}


def test_peak_signal_drives_strength():
    assert (
        presence_strength_from_state({"present": "yes"}, _cv("strong", "absent", "absent", "absent"))
        == "strong_positive"
    )
    assert (
        presence_strength_from_state({"present": "yes"}, _cv("moderate", "weak", "absent", "absent"))
        == "moderate_positive"
    )
    assert (
        presence_strength_from_state({"present": "rna_only"}, _cv("weak", "absent", "absent", "absent"))
        == "weak_positive"
    )


def test_presence_state_floors():
    assert presence_strength_from_state({"present": "no"}, _cv("strong", "strong", "strong", "strong")) == "negative"
    assert presence_strength_from_state({"present": "untested"}, _cv("strong", "strong", "strong", "strong")) == "none"
    # a protein<->RNA conflict is never strong, even with a strong claim signal
    assert (
        presence_strength_from_state(
            {"present": "rna_only_protein_absent", "conflict": True}, _cv("strong", "strong", "strong", "strong")
        )
        == "weak_positive"
    )


def test_alb_is_not_strong_despite_strong_upregulation_verdict():
    """The core fix: ALB's ladder verdict is strongly_upregulated_in_tumor, but its integrated signal
    package peaks at weak → the re-based strength is weak_positive, not strong_positive."""
    assert presence_strength_from_state(_ALB_ST, _ALB_CV) == "weak_positive"
    sc = tp._strength_certainty(
        [], verdict_pair=("strongly_upregulated_in_tumor", "rid"), claim_vector=_ALB_CV, presence_state=_ALB_ST
    )
    assert sc["strength"] == "weak_positive"  # was strong_positive under the verdict-keyed basis


def test_erbb2_outranks_alb_composite_regression():
    """ERBB2 (validated) must rank ABOVE ALB (contamination artifact). Under the OLD verdict-keyed
    strength both read strong_positive and ALB even tied/beat ERBB2 at composite 1.0."""
    erbb2 = tp._strength_certainty(
        [], verdict_pair=("broadly_high_expression", "rid"), claim_vector=_ERBB2_CV, presence_state=_ERBB2_ST
    )
    alb = tp._strength_certainty(
        [], verdict_pair=("strongly_upregulated_in_tumor", "rid"), claim_vector=_ALB_CV, presence_state=_ALB_ST
    )
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


# ── the subset_high rung across all three "strength" channels (2026-09-18, phase 2 of 3) ───────────
# Three differently-named things here are called strength, and only ONE of them separates a 10%-high
# target from a 60%-high one. Pinned together so the distinction cannot quietly rot:
#   1. presence_strength_from_state(presence_state, claim_vector) — the PRIMARY basis. Claim-vector
#      derived, so the verdict token does not floor it (a subset_high target with a strong abundance
#      package still reads strong_positive; prevalence is NOT an abundance statement).
#   2. _presence_strength(verdict) — the verdict-keyed LEGACY FALLBACK for 3-arg callers. Here the new
#      token must read moderate_positive: strong abundance, narrow population.
#   3. presence_signal_strength = _presence_signal_strength(driving_rule_id, verdict) — keyed on the
#      rule-id SUFFIX. Both rungs are `-supportive`, so it cannot separate them AND IS NOT MEANT TO.
# What actually separates them is the verdict token itself plus the `tumor_high_fraction` headline key.
_SUBSET_V = "tumor_subset_high_expression"


def test_subset_high_reads_moderate_on_the_verdict_keyed_fallback():
    """Channel 2. A 3-arg caller (no claim_vector) must not get strong_positive for a minority-high
    subset — that would carry the over-claim one layer below the verdict."""
    assert tp._presence_strength(_SUBSET_V) == "moderate_positive"
    assert tp._pres_direction(_SUBSET_V) == "supports", "a positive rung must not read direction-neutral"
    sc = tp._strength_certainty([], verdict_pair=(_SUBSET_V, "rid"))
    assert sc["strength"] == "moderate_positive"


def test_subset_high_strength_is_not_floored_by_the_verdict_token():
    """Channel 1, asserted so the design is explicit rather than incidental: prevalence is not an
    abundance claim, so the claim-vector basis still governs and a strong package reads strong_positive.
    A reader wanting the population reads `tumor_high_fraction`, never `strength`."""
    st = {"present": "yes", "conflict": False}
    strong = tp._strength_certainty(
        [],
        verdict_pair=(_SUBSET_V, "rid"),
        claim_vector=_cv("strong", "strong", "strong", "moderate"),
        presence_state=st,
    )
    moderate = tp._strength_certainty(
        [],
        verdict_pair=(_SUBSET_V, "rid"),
        claim_vector=_cv("moderate", "weak", "moderate", "weak"),
        presence_state=st,
    )
    assert strong["strength"] == "strong_positive"
    assert moderate["strength"] == "moderate_positive"
    assert strong["composite"] > moderate["composite"], "the two vectors must be distinguishable"


def test_signal_strength_channel_deliberately_cannot_separate_the_two_rungs():
    """Channel 3, pinned as a KNOWN limitation rather than left as a surprise: both rungs end in
    `-supportive`, so this channel reads `supportive` for both. Documented in CONTRACT.md. If someone
    later 'fixes' it by renaming the subset rule's suffix, that would move it out of the positive tier
    (_SUPPORTIVE_RIDS is derived from the suffix) — hence this test, which names the intent."""
    assert tp._presence_signal_strength("tumor-expression-subset-high-supportive", _SUBSET_V) == "supportive"
    assert tp._presence_signal_strength("tumor-expression-broadly-high-supportive", "tumor_broadly_expressed") == (
        "supportive"
    )


def test_subset_high_is_not_tier3_capped_but_broad_still_is():
    """The INV-1 abundance cap is a TIER-3 mechanism. The new token is tier 2 — already at the tier a
    weak claim-A supports — so it must pass through unchanged, while tumor_broadly_expressed (tier 3)
    is still demoted. Both directions asserted: a cap that fired on neither would also pass a
    one-sided check."""
    st = {"present": "yes", "conflict": False}
    weak = _cv("weak", "weak", "weak", "weak")
    assert tp.reconcile_presence_verdict(_SUBSET_V, st, weak) == _SUBSET_V
    assert tp.reconcile_presence_verdict("tumor_broadly_expressed", st, weak) == "tumor_moderately_expressed"
