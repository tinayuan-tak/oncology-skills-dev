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
    for s in mapped:                                    # a mapped axis must be a real canonical axis
        assert QH[s]["axis"] in AXIS_SHORTS


def test_claim_axes_optional_and_listlike():
    for skill, spec in QH.items():
        for sg in spec["sub_groups"]:
            ca = sg.get("claim_axes")
            assert ca is None or (isinstance(ca, list) and ca and all(isinstance(x, str) for x in ca))
