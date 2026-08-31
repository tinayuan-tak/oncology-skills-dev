"""Phase 3 — the EMITTED presence_verdict is reconciled with presence_state so the one word can't
DISAGREE with the signal package. Surgical: only disagreeing POSITIVES demote (stromal-only / protein↔RNA
conflict / not-present); agreeing positives and raw negatives are byte-stable. The RAW ladder collapse
(_verdict) is untouched, so its golden-spine / ladder-invariant / flip-matrix tests stay byte-stable.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import run as tp  # noqa: E402


def test_agreeing_positive_is_byte_stable():
    # EPCAM/ERBB2: present=yes, malignant=yes → the nuanced ladder word is kept unchanged.
    for raw in ("tumor_broadly_expressed", "broadly_high_expression", "strongly_upregulated_in_tumor"):
        assert tp.reconcile_presence_verdict(raw, {"present": "yes", "malignant_intrinsic": "yes"}) == raw


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
