"""report_render — report-level overview blocks (signals_overview diverging strip + risk_6dim tiles),
absorbed from the tp_dashboard v2 design and re-sourced from the spine."""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render._fixtures import make_decision_json, make_nomination
from _skills_common.report_render import build_ir, build_ir_for_skill, render_report, resolve_spec, vocab


def _overview_kinds(ir):
    return [b.kind for b in ir.overview]


def test_build_ir_emits_both_overview_blocks_at_full():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    assert vocab.SIGNALS_OVERVIEW in _overview_kinds(ir)
    assert vocab.RISK_6DIM in _overview_kinds(ir)


def test_signals_overview_rows_are_scored_skills_killer_first():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    sov = next(b for b in ir.overview if b.kind == vocab.SIGNALS_OVERVIEW)
    shorts = [r["short"] for r in sov.payload["rows"]]
    assert shorts[0] == "safety"                       # killer (level -3) sorts to the top
    assert "dependency" in shorts                       # supportive gating skill
    assert "Target-intrinsic dossier" in sov.payload["descriptive"]  # descriptive → footnote (title), not a bar
    assert sov.payload["counts"]["against"] >= 1 and sov.payload["counts"]["support"] >= 1


def test_risk_6dim_has_ordered_dims_with_bins():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    r6 = next(b for b in ir.overview if b.kind == vocab.RISK_6DIM)
    dims = {d["dim"]: d for d in r6.payload["dims"]}
    assert dims["safety"]["rank"] == 3 and dims["safety"]["bin"] == "HIGH"
    assert dims["commercial"]["rank"] is None          # ENGINE-BLIND → off-scale rank
    assert [d["dim"] for d in r6.payload["dims"]][:2] == ["biological", "druggability"]  # canonical order


def test_level_gates_overview():
    # signals_overview is L0 (the lead); risk_6dim is L1+
    l0 = _overview_kinds(build_ir(make_nomination(), resolve_spec(level="L0")))
    assert vocab.SIGNALS_OVERVIEW in l0 and vocab.RISK_6DIM not in l0
    l1 = _overview_kinds(build_ir(make_nomination(), resolve_spec(level="L1")))
    assert vocab.RISK_6DIM in l1


def test_single_skill_has_no_overview():
    ir = build_ir_for_skill(make_decision_json()["headline"]["skill_report"], resolve_spec("full"),
                            skill_name="on-target-safety-liability")
    assert ir.overview == []


def test_html_renders_svg_strip_and_risk_tiles():
    html = render_report(make_nomination(), preset="full", backend="html")
    assert "<svg" in html and "signal-strip" in html          # the diverging strip
    assert "risk-tiles" in html and "risk-tile" in html        # the risk tiles
    assert "Signals across skills" in html


def test_text_and_json_render_overview():
    txt = render_report(make_nomination(), preset="full", backend="text")
    assert "Signals across skills" in txt and "risk by dimension" in txt.lower()
    import json
    obj = json.loads(render_report(make_nomination(), preset="full", backend="json"))
    kinds = [b["kind"] for b in obj["overview"]]
    assert vocab.SIGNALS_OVERVIEW in kinds and vocab.RISK_6DIM in kinds


def test_overview_failsoft_without_risk_or_signals():
    # a nomination with no risk_6dim and no gating skills → no overview blocks, no crash
    nom = {"target_report": {"skill_reports": {
        "target_intrinsic": {"role": "descriptive", "polarity": "not_scored", "call": None,
                             "honest_phrase": "x", "claim_chips": [], "provenance": {}},
    }}}
    ir = build_ir(nom, resolve_spec("full"))
    assert ir.overview == []
    assert render_report(nom, preset="full", backend="html")  # renders fine
