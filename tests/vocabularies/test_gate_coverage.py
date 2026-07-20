"""gate_coverage vocabulary tests (L / deciding-axis router, 2026-07-20).

Pins the static map the target-profile router joins against: every gate declares a
necessity/sufficiency band + a baseline framework_can_evidence standing, the coverage tokens
match the calibration vocabulary (so a fix-driven blind→captured flip is one reviewed edit in
one vocab family), and every SUB_SKILLS short the composer emits has a coverage row (so the
router can never hit an unmapped sub-verdict).
"""
import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COV = yaml.safe_load((REPO / "vocabularies" / "gate_coverage.yaml").read_text())

# Shared with known_target_calibration_set reference_profiles + its test's _COVERAGE_VOCAB.
COVERAGE_VOCAB = {"captured", "partial", "blind", "license_blocked", "out_of_scope"}
BANDS = {"necessity", "sufficiency"}
GATE_LETTERS = set("ABCDEFGH")

# The sub-verdict slots the target-profile composer emits (SUB_SKILLS shorts + subtype_fit).
# The router joins gate_coverage against these — every one must have a row.
SUB_SKILL_SHORTS = {
    "expression", "selectivity", "dependency", "synthetic_lethal_partners", "mechanism",
    "genomic_alteration", "differentiation", "tractability_sm", "surface_modality", "safety",
    "subtype_fit",
}


def test_wellformed():
    assert COV["enum_id"] == "gate_coverage"
    assert COV["version"]
    assert isinstance(COV["gates"], list) and COV["gates"]


def test_every_gate_row_wellformed():
    for g in COV["gates"]:
        assert g["short"], g
        assert g["gate"] in GATE_LETTERS, f"{g['short']}: bad gate letter {g.get('gate')!r}"
        assert g["band"] in BANDS, f"{g['short']}: bad band {g.get('band')!r}"
        assert g["framework_can_evidence"] in COVERAGE_VOCAB, \
            f"{g['short']}: bad framework_can_evidence {g.get('framework_can_evidence')!r}"
        assert g.get("evidences"), f"{g['short']}: must state what it evidences"


def test_necessity_sufficiency_bands_match_reframe_1():
    """A/B/C/D = necessity, E/F/G/H = sufficiency (Reframe 1). genomic_alteration is dual-role
    (A present + C biomarker) but banded necessity; subtype_fit is a C sub-rung → necessity."""
    band_of = {g["short"]: (g["gate"], g["band"]) for g in COV["gates"]}
    for short, (gate, band) in band_of.items():
        if gate in set("ABCD"):
            assert band == "necessity", f"{short} (gate {gate}) should be necessity"
        else:
            assert band == "sufficiency", f"{short} (gate {gate}) should be sufficiency"


def test_every_sub_skill_short_has_a_coverage_row():
    """The router must never encounter a sub-verdict with no coverage mapping."""
    covered = {g["short"] for g in COV["gates"]}
    missing = SUB_SKILL_SHORTS - covered
    assert not missing, f"sub-skill shorts with no gate_coverage row: {missing}"


def test_unbuilt_gate_H_declared_blind():
    """H (Translational) has no sub-skill — it must be declared as an unbuilt, blind gate so
    the router treats a decision-hinges-on-H target as blind rather than silently unmapped."""
    unbuilt = {u["gate"]: u for u in COV.get("unbuilt_gates", [])}
    assert "H" in unbuilt, "gate H must be declared in unbuilt_gates"
    assert unbuilt["H"]["framework_can_evidence"] == "blind"
    assert unbuilt["H"]["band"] == "sufficiency"


def test_headline_fidelity_most_sufficiency_is_not_captured():
    """Sanity mirror of the calibration headline: the framework is authoritative on necessity
    and abstaining on sufficiency — so most sufficiency gates are NOT `captured`."""
    suff = [g for g in COV["gates"] if g["band"] == "sufficiency"]
    not_captured = [g for g in suff if g["framework_can_evidence"] != "captured"]
    assert len(not_captured) >= len(suff) // 2, \
        "expected most sufficiency gates to be partial/blind/license_blocked (the fidelity fact)"
