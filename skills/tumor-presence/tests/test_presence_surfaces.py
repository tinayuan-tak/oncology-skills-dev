"""Phase 2 — human/LLM SURFACES consume presence_state instead of the raw collapsed word.

presence_state_phrase is the honest headline text; presence_key_signals lets the decisive
presence_state reads (protein↔RNA conflict, stromal-only, not-present) OVERRIDE its signal-only
headline + caveat. All verdict-INERT (display only).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from _skills_common.presence_claims import presence_state_phrase, presence_key_signals


def test_phrase_covers_each_state():
    assert presence_state_phrase({"present": "yes", "abundance_level": "high", "elevated_vs_normal": "yes",
                                  "malignant_intrinsic": "yes"}) == "Abundantly present in tumor and tumor-elevated"
    assert "low absolute abundance" in presence_state_phrase(
        {"present": "yes", "abundance_level": "low", "elevated_vs_normal": "no", "malignant_intrinsic": "yes"})
    assert "microenvironment" in presence_state_phrase(
        {"present": "yes", "malignant_intrinsic": "stroma", "abundance_level": "low", "elevated_vs_normal": "no"})
    assert presence_state_phrase({"present": "no"}) == "Not present in tumor"
    assert "Conflicting" in presence_state_phrase({"present": "protein_only_rna_absent", "conflict": True})
    assert "confirm protein" in presence_state_phrase({"present": "rna_only_protein_absent", "conflict": True})
    assert presence_state_phrase({}) == "Presence not assessed"


def _hl(A, B, C, pcs, scc):
    return {"claim_vector": {"A": {"signal": A}, "B": {"signal": B}, "C": {"signal": C}, "D": {"signal": "weak"}},
            "protein_confirmation_state": pcs, "sc_expression_class": scc}


def test_key_signals_stroma_overrides_headline_and_caveat():
    ks = presence_key_signals(_hl("weak", "absent", "negative", "confirmed", "microenvironment_dominant"), [])
    assert "microenvironment" in ks["headline"].lower()
    assert "stromal" in (ks["caveat"] or "").lower()


def test_key_signals_conflict_overrides_caveat():
    ks = presence_key_signals(_hl("absent", "weak", "absent", "confirmed", "broadly_low"), [])
    assert "conflict" in (ks["caveat"] or "").lower()
    assert "conflicting" in ks["headline"].lower()


def test_key_signals_not_present_headline():
    ks = presence_key_signals(_hl("absent", "absent", "absent", "untested", "broadly_low"), [])
    assert ks["headline"] == "Not present in tumor"
