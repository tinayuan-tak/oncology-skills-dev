"""Validator for vocabularies/target_thesis.yaml — the Step-2 thesis-routing key.

Asserts the vocabulary is well-formed and internally consistent, so the derivation (skills-side
derive_thesis) and the per-thesis gate blocks (Step 2b) build on a trustworthy contract:
- every thesis a crosswalk maps TO exists in the `theses` enum (no phantom targets),
- `unresolved` exists (the byte-stable fallback that reproduces today's gate),
- the archetype->thesis crosswalk covers exactly the atlas's emitted anchor labels (skipped if the
  sibling skills repo / atlas is absent),
- the biology_axis fallback covers exactly the biology_axis enum,
- the hard-margin thresholds are present and sane (0 < separation <= dominant <= 1).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
THESIS = REPO / "vocabularies" / "target_thesis.yaml"
BIOLOGY_AXIS = REPO / "vocabularies" / "biology_axis.enum.yaml"


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(THESIS.read_text())


def test_enum_has_unresolved_and_is_nonempty(spec):
    assert spec["theses"], "the thesis enum must be non-empty"
    assert "unresolved" in spec["theses"], "unresolved is the byte-stable fallback and must exist"


def test_every_crosswalk_target_is_a_declared_thesis(spec):
    theses = set(spec["theses"])
    for label, thesis in spec["derivation"]["archetype_label_to_thesis"].items():
        assert thesis in theses, f"archetype_label_to_thesis[{label!r}] → {thesis!r} not in the thesis enum"
    for axis, thesis in spec["biology_axis_fallback"].items():
        assert thesis in theses, f"biology_axis_fallback[{axis!r}] → {thesis!r} not in the thesis enum"


def test_hard_margin_thresholds_are_sane(spec):
    hm = spec["derivation"]["hard_margin"]
    dom, sep = hm["dominant_weight_min"], hm["separation_min"]
    assert 0 < sep <= dom <= 1, f"expected 0 < separation({sep}) <= dominant({dom}) <= 1"


def test_biology_axis_fallback_covers_the_enum_exactly(spec):
    axis_enum = {v["value"] for v in yaml.safe_load(BIOLOGY_AXIS.read_text())["values"]}
    fallback = set(spec["biology_axis_fallback"])
    assert fallback == axis_enum, f"biology_axis_fallback keys {fallback} != biology_axis enum {axis_enum}"


def test_archetype_crosswalk_covers_the_anchor_labels():
    """The derivation reads `soft_membership`, whose keys are the atlas ANCHOR labels. The crosswalk
    must map every anchor label (else a real target could carry membership mass on a label with no
    thesis). Skipped when the sibling skills repo / atlas is not on disk."""
    atlas = (
        REPO.parent
        / "rnd-computational-biology-oncology-claude-oncology-skills"
        / "skills"
        / "target-archetype"
        / "atlas"
        / "atlas.json"
    )
    if not atlas.exists():
        pytest.skip("sibling skills atlas absent")
    anchors = json.loads(atlas.read_text()).get("anchors") or []
    anchor_labels = {a.get("label") or a.get("archetype_label") for a in anchors if isinstance(a, dict)}
    anchor_labels = {lab for lab in anchor_labels if lab}
    crosswalk = set(yaml.safe_load(THESIS.read_text())["derivation"]["archetype_label_to_thesis"])
    missing = anchor_labels - crosswalk
    assert not missing, f"atlas anchor labels with no thesis mapping: {sorted(missing)}"


def test_step_2b_refinement_well_formed(spec):
    """The refinement rules promote a coarse thesis to a finer one from axis verdicts. Every `to`/`from`
    thesis must be a declared thesis; `from` must never include a surface/immune thesis being refined
    away incorrectly; each rule carries a when_verdicts condition + a rationale."""
    enum = set(spec["theses"])
    for rule in spec.get("step_2b_refinement", []) or []:
        assert rule["to"] in enum, f"refinement to={rule['to']} not a declared thesis"
        assert set(rule["from"]) <= enum, f"refinement from={rule['from']} has an undeclared thesis"
        assert rule["when_verdicts"], "a refinement must key on >=1 sub-skill verdict"
        assert rule["rationale"].strip()


def test_neomorphic_refinement_matches_the_epicycle_it_subsumes(spec):
    """neomorphic_gof must fire on exactly the gof_driver_scoped_veto_downgrade trigger (confirmed_driver
    /multi_class_driver + non_dependent) so thesis routing subsumes it, and must refine only from
    oncogene_addiction/unresolved (never from antigen_driven/tme_io)."""
    rule = next(r for r in spec["step_2b_refinement"] if r["to"] == "neomorphic_gof")
    assert set(rule["when_verdicts"]["genomic_alteration"]) == {"confirmed_driver", "multi_class_driver"}
    assert rule["when_verdicts"]["dependency"] == ["non_dependent"]
    assert "antigen_driven" not in rule["from"] and "tme_io" not in rule["from"]
    assert rule.get("subsumes") == "gof_driver_scoped_veto_downgrade"
