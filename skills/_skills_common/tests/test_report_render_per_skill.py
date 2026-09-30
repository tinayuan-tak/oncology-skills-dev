"""report_render — per-skill rendering: a single standalone skill (decision.json or bare skill_report)
renders to a one-section report across all backends, with the same tiering + fail-soft."""

import pytest
from _skills_common.report_render import (
    build_ir_auto,
    build_ir_for_skill,
    render_skill_report,
    resolve_spec,
    string_backend_names,
)
from _skills_common.report_render._fixtures import make_decision_json, make_nomination


def test_build_ir_for_skill_makes_one_section_with_resolved_title():
    dj = make_decision_json("on-target-safety-liability")
    ir = build_ir_for_skill(
        dj["headline"]["skill_report"],
        resolve_spec("full"),
        skill_name=dj["skill"],
        target=dj["target"],
        indication=dj["indication"],
    )
    assert len(ir.sections) == 1
    sec = ir.sections[0]
    assert sec.short == "safety"  # full name → short via SUB_SKILLS map
    assert sec.title == "On-target safety"
    assert ir.header.payload["single_skill"] is True
    assert ir.header.payload["recommendation"] is None  # no target-level decision for one skill


def test_auto_detect_decision_json_vs_nomination():
    # a decision.json → single-skill IR; a nomination → composed multi-section IR
    dj_ir = build_ir_auto(make_decision_json(), resolve_spec("full"))
    nom_ir = build_ir_auto(make_nomination(), resolve_spec("full"))
    assert len(dj_ir.sections) == 1
    assert len(nom_ir.sections) >= 2


@pytest.mark.parametrize("backend", string_backend_names())
def test_render_skill_report_all_string_backends(backend):
    out = render_skill_report(make_decision_json(), preset="reviewer-dossier", backend=backend)
    assert isinstance(out, str) and out.strip()
    assert "On-target safety" in out or "safety" in out


def test_render_skill_report_from_bare_skill_report():
    sr = make_decision_json()["headline"]["skill_report"]
    out = render_skill_report(sr, preset="exec-brief", backend="text", skill_name="on-target-safety-liability")
    assert "On-target safety" in out


def test_per_skill_failsoft_empty_and_gateless():
    # a gateless, empty skill_report (call=None, no evidence) must render, not crash
    dj = make_decision_json(
        "target-intrinsic", with_evidence=False, call=None, role="descriptive", polarity="not_scored"
    )
    for backend in string_backend_names():
        out = render_skill_report(dj, preset="full", backend=backend)
        assert out.strip() and "None" not in out


def test_unknown_skill_name_falls_back_to_titleized_short():
    ir = build_ir_for_skill(
        make_decision_json()["headline"]["skill_report"], resolve_spec(level="L1"), skill_name="brand-new-skill"
    )
    assert ir.sections[0].short == "brand-new-skill"
    assert ir.sections[0].title == "Brand new skill"
