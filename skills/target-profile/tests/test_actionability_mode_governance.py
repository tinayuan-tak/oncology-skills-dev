"""Phase-2 tests for format_mode_governance_block — the actionability_mode EMPHASIS steer in the
synthesis prompt. Verdict-inert: it reorders narrative emphasis, never changes the verdict."""
import sys
from pathlib import Path

_SK = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(_SK), str(_SK / "target-profile" / "scripts")]
import tp_synthesis_prompt as P  # noqa: E402


def test_empty_when_absent_or_insufficient():
    assert P.format_mode_governance_block(None) == ""
    assert P.format_mode_governance_block({}) == ""
    assert P.format_mode_governance_block({"dominant": "insufficient"}) == ""   # neutral == today


def test_cis_block_leads_with_genomic_and_flags_emphasis_only():
    blk = P.format_mode_governance_block({"dominant": "cis_feature", "secondary": None,
                                          "arms": {"cis_feature": "dominant"}, "confidence": "high"})
    assert blk and "cis_feature" in blk
    assert "EMPHASIS ONLY" in blk and "never changes the verdict" in blk
    assert "genomic" in blk.lower() and "biomarker" in blk.lower()


def test_abundance_block_notes_expected_non_dependent():
    blk = P.format_mode_governance_block({"dominant": "abundance", "arms": {"abundance": "dominant"}, "confidence": "high"})
    assert "non_dependent" in blk and "EXPECTED" in blk


def test_mixed_block_keeps_both_stories():
    blk = P.format_mode_governance_block({"dominant": "mixed", "arms": {"cis_feature": "dominant", "abundance": "dominant"}, "confidence": "high"})
    assert "BOTH" in blk and "bury" in blk.lower()


def test_block_appears_in_user_prompt():
    """The block is actually threaded into the composed prompt when a mode is passed."""
    prompt = P._build_user_prompt("KRAS", "COADREAD", {},
                                  actionability_mode={"dominant": "cis_feature", "arms": {"cis_feature": "dominant"}, "confidence": "high"})
    assert "Actionability mode" in prompt
    # and absent when no mode passed (byte-stable default)
    prompt0 = P._build_user_prompt("KRAS", "COADREAD", {})
    assert "Actionability mode" not in prompt0
