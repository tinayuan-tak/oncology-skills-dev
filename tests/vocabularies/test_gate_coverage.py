"""gate_coverage vocabulary tests — gate-model v2 / 2.0.0 (L / deciding-axis router).

Pins the two-axis map the target-profile router joins against. v2 (2.0.0) restructures the flat
v1 `gates:` list into three lists (biology_gates / modality_fit / biomarker_facets); see
docs/design/GATE_MODEL_V2_MEMO.md. These tests assert:
  - the three-list shape is well-formed + versioned 2.0.0,
  - biology gates keep letters A–E + are necessity; modality-fit are named (letterless) + sufficiency,
  - biomarker_facets carry a valid grain (sub_skill|card) + role + a reports_into target,
  - every SUB_SKILLS short the composer emits resolves to a ROW entry (biology + modality_fit +
    sub_skill-grain facets) — the router must never hit an unmapped sub-verdict,
  - card-grain facets are NOT in the row set (they render in-section only),
  - the coverage tokens still match the calibration vocabulary,
  - translational is declared unbuilt + blind.
"""
import yaml
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
COV = yaml.safe_load((REPO / "vocabularies" / "gate_coverage.yaml").read_text())

# Shared with known_target_calibration_set reference_profiles + its test's _COVERAGE_VOCAB.
COVERAGE_VOCAB = {"captured", "partial", "blind", "license_blocked", "out_of_scope"}
BANDS = {"necessity", "sufficiency"}
BIOLOGY_LETTERS = set("ABCDE")
AXES = {"biology", "modality_fit"}
ROLES = {"stratification", "corroboration"}
GRAINS = {"sub_skill", "card"}
MODALITIES = {"small_molecule", "degrader", "adc", "bite_tce", "antibody"}

# The sub-verdict slots the target-profile composer emits (SUB_SKILLS shorts + subtype_fit). Every
# one must resolve to a ROW entry (biology gate, modality-fit gate, or sub_skill-grain facet).
SUB_SKILL_SHORTS = {
    "expression", "selectivity", "dependency", "synthetic_lethal_partners", "mechanism",
    "genomic_alteration", "differentiation", "tractability_sm", "surface_modality", "safety",
    "subtype_fit",
}


# --- helpers: mirror the skills-side _flatten_gate_coverage grain rule -------

def _row_entries():
    """The entries that become scorecard rows: biology_gates + modality_fit + sub_skill-grain
    biomarker_facets (card-grain facets excluded — they render in-section, not as a row)."""
    rows = list(COV["biology_gates"]) + list(COV["modality_fit"])
    rows += [f for f in COV["biomarker_facets"] if f.get("grain", "sub_skill") == "sub_skill"]
    return rows


def _all_facets():
    return list(COV["biomarker_facets"])


# --- shape + version ---------------------------------------------------------

def test_wellformed_three_list_v2():
    assert COV["enum_id"] == "gate_coverage"
    assert str(COV["version"]) == "2.0.0"
    for key in ("biology_gates", "modality_fit", "biomarker_facets"):
        assert isinstance(COV[key], list) and COV[key], f"{key} must be a non-empty list"


def test_biology_gates_lettered_necessity():
    for g in COV["biology_gates"]:
        assert g["short"], g
        assert g["axis"] == "biology", g["short"]
        assert g["gate"] in BIOLOGY_LETTERS, f"{g['short']}: bad biology letter {g.get('gate')!r}"
        assert g["band"] == "necessity", f"{g['short']}: biology gate must be necessity"
        assert g["framework_can_evidence"] in COVERAGE_VOCAB, g["short"]
        assert g.get("evidences"), f"{g['short']}: must state what it evidences"


def test_modality_fit_named_letterless_sufficiency():
    for g in COV["modality_fit"]:
        assert g["short"], g
        assert g["axis"] == "modality_fit", g["short"]
        assert "gate" not in g, f"{g['short']}: modality-fit gates are letterless in v2"
        assert g.get("gate_name"), f"{g['short']}: modality-fit gate needs a name"
        assert g["band"] == "sufficiency", f"{g['short']}: modality-fit must be sufficiency"
        assert g["framework_can_evidence"] in COVERAGE_VOCAB, g["short"]
        mr = g.get("modality_relevance")
        if mr is not None:
            assert set(mr) <= MODALITIES, f"{g['short']}: bad modality {set(mr) - MODALITIES}"


def test_altered_gate_split_out_of_v1_overload():
    """The v1 A/C overload (slashed 'Present (alteration) / Required (biomarker-stratified)') is
    retired: genomic_alteration is now its own biology gate E 'Altered' that reports into Required."""
    ga = next(g for g in COV["biology_gates"] if g["short"] == "genomic_alteration")
    assert ga["gate"] == "E" and ga["gate_name"] == "Altered"
    assert "dependency" in ga.get("reports_into", [])
    # no slashed gate_name survives anywhere
    for g in COV["biology_gates"] + COV["modality_fit"]:
        assert "/" not in g.get("gate_name", ""), f"{g['short']}: slashed gate_name not retired"


# --- biomarker facets --------------------------------------------------------

def test_facets_carry_grain_role_and_reports_into():
    for f in _all_facets():
        assert f.get("grain") in GRAINS, f"{f['short']}: bad/missing grain {f.get('grain')!r}"
        assert f.get("role") in ROLES, f"{f['short']}: bad role {f.get('role')!r}"
        assert f.get("reports_into"), f"{f['short']}: a facet must declare reports_into"
        assert f["short"] not in f.get("reports_into", []), f"{f['short']}: self reports_into"


def test_card_grain_facets_declare_a_card_id():
    """card-grain facets bind to a specific evidence card. `card_id` is machine-readable (promoted
    from a YAML comment) so a consumer (dashboard breadcrumb) can resolve the card→gate edge from
    the contract instead of hardcoding it. sub_skill-grain facets need no card_id (they're rows)."""
    for f in _all_facets():
        if f.get("grain") == "card":
            assert f.get("card_id"), f"{f['short']}: card-grain facet must declare a card_id"


def test_reports_into_names_real_row_shorts():
    """reports_into edges must point at a row entry (a gate or sub_skill facet), no dangling ref."""
    row_shorts = {g["short"] for g in _row_entries()}
    for f in _all_facets():
        for tgt in f.get("reports_into", []):
            assert tgt in row_shorts, f"{f['short']}: reports_into unknown short {tgt!r}"


def test_sub_skill_facets_are_rows_card_facets_are_not():
    row_shorts = {g["short"] for g in _row_entries()}
    # the two sub_skill-grain facets are rows (they were v1 rows)
    for s in ("synthetic_lethal_partners", "subtype_fit"):
        assert s in row_shorts, f"{s} (sub_skill grain) must be a scorecard row"
    # the card-grain facets are NOT rows
    card_facets = {f["short"] for f in _all_facets() if f.get("grain") == "card"}
    assert card_facets, "expected some card-grain facets"
    assert not (card_facets & row_shorts), f"card-grain facets leaked into rows: {card_facets & row_shorts}"


# --- router join contract ----------------------------------------------------

def test_every_sub_skill_short_resolves_to_a_row():
    """The router must never encounter a composer sub-verdict with no coverage row."""
    covered = {g["short"] for g in _row_entries()}
    missing = SUB_SKILL_SHORTS - covered
    assert not missing, f"sub-skill shorts with no gate_coverage row: {missing}"


def test_translational_unbuilt_blind():
    unbuilt = {u["short"]: u for u in COV.get("unbuilt", [])}
    assert "translational" in unbuilt, "translational must be declared in unbuilt"
    assert unbuilt["translational"]["framework_can_evidence"] == "blind"
    assert unbuilt["translational"]["band"] == "sufficiency"


def test_headline_fidelity_most_sufficiency_is_not_captured():
    """The framework is authoritative on necessity + abstaining on sufficiency — so most
    sufficiency (modality-fit) gates are NOT captured."""
    suff = list(COV["modality_fit"])
    not_captured = [g for g in suff if g["framework_can_evidence"] != "captured"]
    assert len(not_captured) >= len(suff) // 2, \
        "expected most modality-fit gates to be partial/blind/license_blocked (the fidelity fact)"
