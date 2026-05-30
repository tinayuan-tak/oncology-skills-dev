"""Tests for the modality_classes.yaml loader.

Pure data-loader tests. No scoring logic exercised here — see
test_phase3_dispatcher.py (commit 3) for the math, and the e2e regression
tests (commit 4) for the full bulk-RNA pipeline.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from modality_registry import ModalityRegistry, ModalityClass  # noqa: E402


@pytest.fixture(scope="module")
def registry() -> ModalityRegistry:
    return ModalityRegistry()


# ---------------------------------------------------------------------------
# Self-consistency: registry loads and every reference resolves
# ---------------------------------------------------------------------------

def test_registry_loads_with_expected_counts(registry: ModalityRegistry) -> None:
    assert len(registry.list_classes()) == 6
    assert len(registry.list_rules()) == 5
    assert registry.version == "1.0.0"


def test_every_class_phase3_rule_exists(registry: ModalityRegistry) -> None:
    """No class points at a phase3_tox_rule that isn't defined."""
    rules = set(registry.list_rules())
    for class_id in registry.list_classes():
        rule = registry.get_class(class_id).phase3_tox_rule
        assert rule in rules, f"{class_id} → undefined rule {rule!r}"


def test_default_class_exists(registry: ModalityRegistry) -> None:
    """Fallback class must itself be a real class."""
    default = registry.resolve_class(None)
    assert default in registry.list_classes()
    assert default == "antibody_naked"


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("alias, expected_class", [
    # antibody_naked
    ("antibody", "antibody_naked"),
    ("Antibody", "antibody_naked"),
    ("naked antibody", "antibody_naked"),
    ("mAb", "antibody_naked"),
    ("monoclonal antibody", "antibody_naked"),
    ("IgG", "antibody_naked"),

    # adc
    ("ADC", "adc"),
    ("antibody-drug conjugate", "adc"),
    ("antibody drug conjugate", "adc"),

    # tce
    ("T-cell engager", "tce"),
    ("TCE", "tce"),
    ("BiTE", "tce"),
    ("CAR-T", "tce"),
    ("CAR-NK", "tce"),

    # small_molecule
    ("small molecule", "small_molecule"),
    ("SMI", "small_molecule"),
    ("kinase inhibitor", "small_molecule"),
    ("TKI", "small_molecule"),

    # degrader
    ("Molecular Glue", "degrader"),
    ("molecular glue", "degrader"),
    ("PROTAC", "degrader"),
    ("protac", "degrader"),
    ("degrader", "degrader"),
    ("TPD", "degrader"),
    ("targeted protein degrader", "degrader"),

    # rnai
    ("RNAi", "rnai"),
    ("siRNA", "rnai"),
    ("ASO", "rnai"),
    ("antisense oligonucleotide", "rnai"),
    ("mRNA", "rnai"),
])
def test_aliases_resolve_to_canonical_class(
    registry: ModalityRegistry, alias: str, expected_class: str
) -> None:
    assert registry.resolve_class(alias) == expected_class


def test_resolve_strips_whitespace(registry: ModalityRegistry) -> None:
    assert registry.resolve_class("  ADC  ") == "adc"
    assert registry.resolve_class("\tProtac\n") == "degrader"


# ---------------------------------------------------------------------------
# Substring resolution: real-world full-modality strings from the integrated
# report markdown should still resolve correctly.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("messy_input, expected_class", [
    # The CRBN integrated report literally has this string.
    ("Selective CRBN-binding small-molecule molecular glue or PROTAC — neosubstrate-specific",
     "degrader"),
    # Antibody/ADC variants.
    ("Naked antibody (IgG1, ADCC-enhanced)", "antibody_naked"),
    ("ADC with DXd payload", "adc"),
    ("Anti-PCDH7 monoclonal antibody", "antibody_naked"),
    # T-cell engager descriptive strings.
    ("CD3xPCDH7 bispecific T-cell engager", "tce"),
    # Small molecule descriptive strings.
    ("Allosteric KRAS G12C small molecule inhibitor", "small_molecule"),
])
def test_substring_resolution_for_messy_inputs(
    registry: ModalityRegistry, messy_input: str, expected_class: str
) -> None:
    assert registry.resolve_class(messy_input) == expected_class


# ---------------------------------------------------------------------------
# Unknown / fallback behavior
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("unknown_input", [
    None,
    "",
    "   ",
    "completely-fictional-modality",
    "radioimmunotherapy",   # legitimate modality not yet in registry
])
def test_unknown_modality_falls_back_to_default(
    registry: ModalityRegistry, unknown_input: str | None
) -> None:
    assert registry.resolve_class(unknown_input) == "antibody_naked"


def test_is_known_modality_returns_false_for_unknown(registry: ModalityRegistry) -> None:
    assert registry.is_known_modality(None) is False
    assert registry.is_known_modality("") is False
    assert registry.is_known_modality("completely-fictional-modality") is False


def test_is_known_modality_returns_true_for_alias(registry: ModalityRegistry) -> None:
    assert registry.is_known_modality("ADC") is True
    assert registry.is_known_modality("Molecular Glue") is True
    # Substring match also counts as known.
    assert registry.is_known_modality("Anti-HER2 monoclonal antibody") is True


# ---------------------------------------------------------------------------
# get_class returns a typed record with all expected fields
# ---------------------------------------------------------------------------

def test_get_class_for_degrader(registry: ModalityRegistry) -> None:
    c = registry.get_class("degrader")
    assert isinstance(c, ModalityClass)
    assert c.class_id == "degrader"
    assert c.phase3_tox_rule == "expression_floor_only"
    assert c.expression_floor_rna == 2.0
    assert c.expression_floor_protein is None
    assert c.requires_surface_localization is False
    assert c.safety_flags == []
    assert "neosubstrate" in c.description.lower()


def test_get_class_for_tce(registry: ModalityRegistry) -> None:
    c = registry.get_class("tce")
    assert c.phase3_tox_rule == "any_normal_expression_blocks"
    assert c.expression_floor_rna == 3.5
    assert c.expression_floor_protein == "Medium"
    assert c.requires_surface_localization is True
    assert "cns_expression_excludes" in c.safety_flags


def test_get_class_unknown_raises(registry: ModalityRegistry) -> None:
    with pytest.raises(KeyError):
        registry.get_class("not-a-real-class")


# ---------------------------------------------------------------------------
# Rule config lookup
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rule_name, key, expected", [
    ("tumor_vs_normal_strict", "tox_penalty_by_risk", {"Low": 0, "Medium": 1, "High": 2}),
    ("tumor_vs_normal_very_strict", "tox_penalty_by_risk", {"Low": 0, "Medium": 2, "High": 3}),
    ("tumor_vs_normal_relaxed", "tox_penalty_by_risk", {"Low": 0, "Medium": 0, "High": 1}),
    ("expression_floor_only", "tox_penalty_by_risk", {"Low": 0, "Medium": 0, "High": 0}),
    ("any_normal_expression_blocks", "tox_penalty_by_risk", {"Low": 1, "Medium": 3, "High": 4}),
])
def test_rule_penalty_tables(
    registry: ModalityRegistry, rule_name: str, key: str, expected: dict
) -> None:
    config = registry.get_rule_config(rule_name)
    assert config[key] == expected


def test_rule_config_unknown_raises(registry: ModalityRegistry) -> None:
    with pytest.raises(KeyError):
        registry.get_rule_config("not-a-real-rule")


# ---------------------------------------------------------------------------
# Subcellular compatibility (used by protein-skill cross-validation, task 15)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("class_id, location, expected", [
    # Compatible: surface modalities + plasma membrane / cell junctions.
    ("antibody_naked", "Plasma membrane", True),
    ("adc", "Plasma membrane", True),
    ("tce", "Plasma membrane", True),
    ("antibody_naked", "Cell Junctions", True),
    ("adc", "Cell Junctions", True),

    # Incompatible: surface modalities for nuclear/cytosolic targets.
    ("antibody_naked", "Nucleoplasm", False),
    ("adc", "Cytosol", False),
    ("tce", "Mitochondria", False),

    # Compatible: small molecule / degrader for intracellular.
    ("small_molecule", "Cytosol", True),
    ("small_molecule", "Nucleoplasm", True),
    ("degrader", "Cytosol", True),
    ("degrader", "Nucleoplasm", True),

    # ADC for vesicles (internalization-competent).
    ("adc", "Vesicles", True),
    ("antibody_naked", "Vesicles", False),  # naked Ab has no internalization mechanism

    # TCE only for surface — never for vesicles (no triggered cytotoxicity from inside).
    ("tce", "Vesicles", False),
    ("tce", "Cell Junctions", False),  # no — TCE in registry only allows Plasma membrane
])
def test_subcellular_compatibility(
    registry: ModalityRegistry, class_id: str, location: str, expected: bool
) -> None:
    assert registry.is_compatible_subcellular(class_id, location) is expected


def test_subcellular_unknown_location_does_not_block(registry: ModalityRegistry) -> None:
    """For HPA locations not in the registry, default to 'compatible' rather
    than blocking. Conservative — the registry covers canonical locations."""
    assert registry.is_compatible_subcellular("antibody_naked", "Made-Up Compartment") is True


# ---------------------------------------------------------------------------
# All aliases are unique across classes
# ---------------------------------------------------------------------------

def test_aliases_are_unique(registry: ModalityRegistry) -> None:
    """No alias may resolve to two different classes — would create
    ambiguous routing."""
    seen: dict[str, str] = {}
    for alias_lc, cid in registry.all_aliases().items():
        if alias_lc in seen and seen[alias_lc] != cid:
            pytest.fail(f"alias {alias_lc!r} resolves to both {seen[alias_lc]} and {cid}")
        seen[alias_lc] = cid
