"""Phase 3 — the EMITTED presence_verdict is reconciled with presence_state so the one word can't
DISAGREE with the signal package. Surgical: only disagreeing POSITIVES demote (stromal-only / protein↔RNA
conflict / not-present); agreeing positives and raw negatives are byte-stable. The RAW ladder collapse
(_verdict) is untouched, so its golden-spine / ladder-invariant / flip-matrix tests stay byte-stable.
"""
from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_reconcile")


def test_agreeing_positive_is_byte_stable():
    # EPCAM/ERBB2: present=yes, malignant=yes → the nuanced ladder word is kept unchanged.
    for raw in ("tumor_broadly_expressed", "broadly_high_expression", "strongly_upregulated_in_tumor"):
        assert tp.reconcile_presence_verdict(raw, {"present": "yes", "malignant_intrinsic": "yes"}) == raw


def test_tier3_capped_to_tier2_when_claim_a_moderate():
    # USP8/NSCLC: cell-line ladder fires broadly_high (tier 3) but claim-A abundance signal is only
    # weak/moderate → the emitted word is capped DOWN to its tier-2 lens sibling (INV-1 / signals-first).
    st = {"present": "yes", "malignant_intrinsic": "yes"}
    for a_sig in ("weak", "moderate"):
        cv = {"A": {"signal": a_sig}}
        assert tp.reconcile_presence_verdict("broadly_high_expression", st, cv) == "broadly_moderate_expression"
        assert tp.reconcile_presence_verdict("strongly_upregulated_in_tumor", st, cv) == "modestly_upregulated_in_tumor"
        assert tp.reconcile_presence_verdict("tumor_broadly_expressed", st, cv) == "tumor_moderately_expressed"


def test_tier3_not_capped_when_claim_a_strong():
    # EPCAM: A=strong → tier 3 is signal-supported → NO cap (byte-stable), EVEN IF a low absolute-abundance
    # floor is present (abundance_floor is orthogonal — it must not demote a strongly-present target).
    st = {"present": "yes", "malignant_intrinsic": "yes", "abundance_level": "low"}
    cv = {"A": {"signal": "strong"}}
    assert tp.reconcile_presence_verdict("broadly_high_expression", st, cv) == "broadly_high_expression"
    assert tp.reconcile_presence_verdict("tumor_broadly_expressed", st, cv) == "tumor_broadly_expressed"


def test_no_cap_without_claim_vector():
    # No claim_vector supplied → cap cannot fire → byte-stable (the enrichment is best-effort).
    st = {"present": "yes", "malignant_intrinsic": "yes"}
    assert tp.reconcile_presence_verdict("broadly_high_expression", st) == "broadly_high_expression"


def test_tier2_raw_is_never_capped():
    # A tier-2 word already agrees with a moderate signal → left alone (cap only touches tier-3).
    st = {"present": "yes", "malignant_intrinsic": "yes"}
    cv = {"A": {"signal": "weak"}}
    assert tp.reconcile_presence_verdict("broadly_moderate_expression", st, cv) == "broadly_moderate_expression"


def test_stromal_demotes():
    # PECAM1: raw positive but the signal is microenvironment/stromal, not malignant-cell.
    assert tp.reconcile_presence_verdict(
        "tumor_broadly_expressed", {"present": "yes", "malignant_intrinsic": "stroma"}
    ) == tp.STROMAL_MICROENVIRONMENT_PRESENT


def test_protein_rna_conflict_demotes():
    # ALB: raw positive (single tumor-vs-adjacent contrast) but abundance/sc absent, protein present.
    assert tp.reconcile_presence_verdict(
        "strongly_upregulated_in_tumor", {"present": "protein_only_rna_absent", "malignant_intrinsic": "no"}
    ) == tp.CONFLICTED_PROTEIN_PRESENT_RNA_ABSENT


def test_not_present_demotes_to_absent():
    assert tp.reconcile_presence_verdict(
        "strongly_upregulated_in_tumor", {"present": "no"}) == "absent"


def test_raw_negative_is_left_alone():
    # a raw measured-negative already agrees with the state → never rewritten
    assert tp.reconcile_presence_verdict("broadly_low_expression", {"present": "no"}) == "broadly_low_expression"


def test_gap_and_missing_state_are_safe():
    assert tp.reconcile_presence_verdict("data_unavailable", {"present": "no"}) == "data_unavailable"
    assert tp.reconcile_presence_verdict("tumor_broadly_expressed", None) == "tumor_broadly_expressed"


def test_new_token_polarity():
    assert tp._presence_verdict_polarity(tp.STROMAL_MICROENVIRONMENT_PRESENT) == "neutral"
    assert tp._presence_verdict_polarity(tp.CONFLICTED_PROTEIN_PRESENT_RNA_ABSENT) == "neutral"
    assert tp._presence_verdict_polarity("absent") == "negative"
    assert tp._presence_verdict_polarity("tumor_broadly_expressed") == "positive"
