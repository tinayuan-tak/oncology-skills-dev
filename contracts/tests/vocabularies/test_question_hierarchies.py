"""Governed question_hierarchies (target_profiling_axes.yaml) — the MIDDLE decomposition levels
(sub-group → question → measurement_type), consolidated here as the single source of truth from which
each skill's question_hierarchy.yaml is generated (skills-repo drift-CI). These tests pin connectivity
+ references so a measurement_type rename can no longer silently orphan a question."""

import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from validators.validate_question_hierarchies import validate  # noqa: E402

AXES = yaml.safe_load((REPO / "vocabularies" / "target_profiling_axes.yaml").read_text())
QH = AXES.get("question_hierarchies") or {}
AXIS_SHORTS = {q["short"] for q in AXES["questions"]}
_AUX = {"immune-context", "target-intrinsic", "cis-feature-coherence"}


def test_connectivity_and_references_clean():
    """Every question binds a known measurement_type; every sub-group has a question; axis links resolve."""
    errors = validate()
    assert errors == [], "question_hierarchies defects:\n" + "\n".join(errors)


def test_all_thirteen_skills_present():
    assert len(QH) == 13, f"expected 13 skill hierarchies, got {sorted(QH)}"


def test_axis_mapped_and_auxiliary_split():
    mapped = {s for s, spec in QH.items() if spec.get("axis") is not None}
    aux = {s for s, spec in QH.items() if spec.get("axis") is None}
    assert aux == _AUX, f"auxiliary (axis:null) skills unexpected: {aux}"
    assert len(mapped) == 10
    for s in mapped:  # a mapped axis must be a real canonical axis
        assert QH[s]["axis"] in AXIS_SHORTS


def test_genomic_exon_skip_is_its_own_sub_group_not_fusion():
    """`splice_exon_skip` is a SPL sub-group of its own, never a FUS measurement_type.

    Sub-group `measurement_types` are what `derive_subgroups` (skills `_skills_common`) SCORES per
    sub-group; `context_types` are deliberately NOT scored. While `splice_exon_skip` sat under FUS, a
    METex14 exon-skipping read was scored into the FUSION signal — but the skill computes and publishes a
    SEPARATE exon-skip driver claim (its own resolver rung `splice-exon-skip-driver-supportive`, its own
    scope-map entry, its own `genomic_claims._spl_signal`, its own `splice_driver` question on axis SPL in
    `genomic-alteration-profile/questions.yaml`). One nomination therefore carried a fusion signal lifted
    by splice evidence alongside an independent splice claim.

    `tumor_splice_dysregulation` is a `context_type` here, not a measurement_type, and that is load-bearing
    twice over: it is a splice-FORM read that must not be scored on ANY axis (it was scored into FUS for the
    same reason), and the skill routes it to an axis-LESS `display_only` question so it stays out of the SPL
    literature crosswalk. Omitting it from the hierarchy entirely is NOT the alternative — the skills-side
    connectivity guard would then flag its card as a same-question orphan.
    """
    sgs = {sg["id"]: sg for sg in QH["genomic-alteration-profile"]["sub_groups"]}
    assert set(sgs) == {"SNV", "CN", "FUS", "SPL", "DEP"}
    spl_scored = {mt for q in sgs["SPL"]["questions"] for mt in q["measurement_types"]}
    assert spl_scored == {"splice_exon_skip"}
    assert sgs["SPL"]["context_types"] == ["tumor_splice_dysregulation"]
    fus_scored = {mt for q in sgs["FUS"]["questions"] for mt in q["measurement_types"]}
    assert fus_scored == {"fusion_rearrangement", "fusion_stratified_dependency"}
    for sg_id, sg in sgs.items():
        scored = {mt for q in sg["questions"] for mt in q["measurement_types"]}
        assert "tumor_splice_dysregulation" not in scored, (
            f"tumor_splice_dysregulation is a splice-FORM display read; scoring it under {sg_id} makes it "
            "evidence for a driver call it does not measure"
        )
        if sg_id != "SPL":
            assert "splice_exon_skip" not in scored | set(sg.get("context_types") or [])


def test_claim_axes_optional_and_listlike():
    for skill, spec in QH.items():
        for sg in spec["sub_groups"]:
            ca = sg.get("claim_axes")
            assert ca is None or (isinstance(ca, list) and ca and all(isinstance(x, str) for x in ca))
