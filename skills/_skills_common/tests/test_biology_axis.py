"""biology_axis loader — resolve a target's curated axis + plausible modalities, and render
the modality-emphasis governance block. Pure local vocabulary read (no network)."""

from __future__ import annotations

import sys
from pathlib import Path

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common.biology_axis import (  # noqa: E402
    resolve_biology_axis,
    format_axis_governance_block,
)


def test_intracellular_target_resolves_to_sm_degrader():
    info = resolve_biology_axis("KRAS")
    assert info["biology_axis"] == "intracellular_intrinsic"
    assert info["curated"] is True
    assert info["plausible_modalities"] == ["small_molecule", "degrader"]
    assert info["multi_axis"] is False


def test_surface_target_resolves_via_primary_and_alias():
    primary = resolve_biology_axis("TACSTD2")
    alias = resolve_biology_axis("TROP2")
    assert primary["biology_axis"] == "surface_intrinsic"
    assert alias["biology_axis"] == "surface_intrinsic"
    assert alias["plausible_modalities"] == ["adc", "bite_tce", "antibody"]


def test_multi_axis_target_is_flagged_not_erased():
    info = resolve_biology_axis("EGFR")
    assert info["biology_axis"] == "intracellular_intrinsic"  # primary
    assert info["multi_axis"] is True
    assert info["multi_axis_note"] and "surface" in info["multi_axis_note"].lower()


def test_uncurated_target_is_unknown_with_empty_modalities():
    info = resolve_biology_axis("ZZZ_NOT_A_GENE")
    assert info["biology_axis"] == "unknown"
    assert info["curated"] is False
    assert info["plausible_modalities"] == []


def test_governance_block_steers_intracellular_away_from_surface():
    block = format_axis_governance_block(resolve_biology_axis("KRAS"))
    assert "intracellular_intrinsic" in block
    assert "small_molecule, degrader" in block
    # modality talk is constrained (not foregrounded) + surface is not applicable absent an override
    assert "not applicable to this intracellular target" in block


def test_governance_block_is_secondary_not_foregrounded():
    """Altitude fix: the block must frame modality as SECONDARY, not the lead."""
    block = format_axis_governance_block(resolve_biology_axis("KRAS"))
    assert "SECONDARY to" in block
    assert "FOREGROUND" not in block  # old foreground-modality framing is gone


def test_governance_block_surface_target_lists_surface_modalities():
    block = format_axis_governance_block(resolve_biology_axis("TACSTD2"))
    assert "surface modalities (ADC" in block


def test_governance_block_notes_multi_axis():
    block = format_axis_governance_block(resolve_biology_axis("EGFR"))
    assert "MULTI-AXIS" in block


def test_governance_block_uncurated_makes_no_modality_assumption():
    block = format_axis_governance_block(resolve_biology_axis("ZZZ_NOT_A_GENE"))
    assert "uncurated" in block.lower()
    assert "do NOT assume a class" in block


def test_resolution_never_raises_on_bad_contracts_root():
    # a nonexistent contracts root must degrade to unknown, not raise
    info = resolve_biology_axis("KRAS", contracts_root="/nonexistent/path/xyz")
    assert info["biology_axis"] == "unknown"
    assert info["curated"] is False
