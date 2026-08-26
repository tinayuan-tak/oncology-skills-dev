"""PR-3 — the composed-dashboard view model. Pins the single ordered block list + mode/flag selection
that both renderers and the nav consume (so section set/order can't drift). Pure logic (no render/S3)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_vm", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_load()                    # bootstraps scripts/ onto sys.path
import tp_view_model as vm  # noqa: E402


def _ctx(**kw):
    base = dict(target="KRAS", indication="COADREAD", sub_results={"expression": {}}, llm_output={})
    base.update(kw)
    return vm.RenderContext(**base)


def test_canonical_order_full_report():
    ks = vm.present_kinds(_ctx(scorecard=[{"short": "expression"}], ordinal_matrix={"axes": {}, "rows": []},
                               deciding_axis={"routing": "x"}, risk_rollup={"x": 1}, risk_assessment={"d": 1}))
    # risk-by-category leads (present here) before synthesis; about is last.
    assert ks[0] == "risk_by_category" and ks[1] == "synthesis" and ks[-1] == "about"
    assert ks.index("subskill_sections") < ks.index("tension") < ks.index("provenance_trace") < ks.index("about")
    assert ks.index("evidence_summary") < ks.index("modality_matrix") < ks.index("deciding_axis")


def test_synthesis_leads_when_no_risk_rollup():
    ks = vm.present_kinds(_ctx())    # no risk_rollup → synthesis is the lead block
    assert ks[0] == "synthesis"


def test_optional_blocks_gated_by_inputs():
    ks = vm.present_kinds(_ctx())   # minimal: no matrix/deciding/risk/lit inputs
    assert "risk_by_category" not in ks and "literature_risk" not in ks
    assert "modality_matrix" not in ks and "deciding_axis" not in ks
    # evidence_summary is gated on sub_results (not scorecard) — present here (matches its emitter).
    for k in ("synthesis", "evidence_summary", "subskill_sections", "tension", "provenance_trace", "about"):
        assert k in ks


def test_hypothesis_body_replaces_exec_and_suppresses_tension():
    # a hypothesis with a BODY replaces the exec summary (nav → s-hypothesis) + suppresses tension.
    hyp = {"headline": "h", "hypothesis": {"causal_rationale": {"statement": "x"}}}
    blocks = vm.build_view_model(_ctx(hypothesis=hyp))
    syn = next(b for b in blocks if b.kind == "synthesis")
    assert syn.id == "s-hypothesis"
    assert "tension" not in vm.present_kinds(_ctx(hypothesis=hyp))


def test_bodyless_hypothesis_keeps_exec_and_tension():
    # a hypothesis WITHOUT a body must NOT swap the nav (emitter falls back to exec) and must NOT
    # suppress tension — else a dead #s-hypothesis anchor + a missing tension section.
    hyp = {"headline": "h", "verdict": {"computed": "declined"}}   # no "hypothesis" body
    blocks = vm.build_view_model(_ctx(hypothesis=hyp))
    syn = next(b for b in blocks if b.kind == "synthesis")
    assert syn.id == "s-exec"
    assert "tension" in vm.present_kinds(_ctx(hypothesis=hyp))


def test_presence_only_is_single_section():
    ks = vm.present_kinds(_ctx(presence_only=True))
    assert ks == ["subskill_sections"]


def test_deciding_axis_suppressible():
    assert "deciding_axis" not in vm.present_kinds(_ctx(deciding_axis={"routing": "x"}, show_deciding_axis=False))
    assert "deciding_axis" in vm.present_kinds(_ctx(deciding_axis={"routing": "x"}, show_deciding_axis=True))


# --- Contract: the HTML renderer must emit every block the view model declares present (no silent drop).
import tp_render_html as tph  # noqa: E402

_KIND_ANCHOR = {
    "risk_by_category": "s-risk-rollup", "synthesis": "s-exec", "literature_risk": "s-litrisk",
    "evidence_summary": "s-evidence", "modality_matrix": "s-matrix", "deciding_axis": "s-deciding",
    "subskill_sections": "s-skill-expression", "tension": "s-tension",
    "provenance_trace": "s-provenance", "about": "s-about",
}


def test_html_renders_every_present_block():
    sr = {"expression": {"skill_dir": "tumor-presence",
                         "cards": [{"card_id": "rna", "summary": {"x": 1}}],
                         "verdict": ("tumor_broadly_expressed", "r-x"), "fired": []}}
    llm = {"executive_summary": {"value": "e"}, "overall_recommendation": {"value": "hold"},
           "confidence": {"value": "high"}, "tension_analysis": {"value": "t"}}
    kinds = ["expression"]
    scorecard = [{"short": "expression", "status": "supportive", "verdict": "tumor_broadly_expressed"}]
    h = tph._render_target_profile_html(
        "KRAS", "COADREAD", sr, llm, {}, scorecard=scorecard,
        ordinal_matrix={"axes": {"columns": ["small_molecule"]}, "rows": [], "legend":
                        {"on_scale": {}, "off_scale": []}, "_disclaimer": "d"},
        deciding_axis={"routing": "r", "basis": "positive_signal", "deciding_axes": []},
        risk_rollup={"biological": {"level": "LOW", "driver": "d"}},
        risk_assessment={"dimensions": {"biological": {"risk_level": "LOW", "justification": "j",
                                                       "interpretation": "i", "cited_pmids": []}}})
    ctx = _ctx(sub_results=sr, scorecard=scorecard, ordinal_matrix={"axes": {}, "rows": []},
               deciding_axis={"routing": "r"}, risk_rollup={"x": 1}, risk_assessment={"d": 1})
    for kind in vm.present_kinds(ctx):
        anchor = _KIND_ANCHOR[kind]
        assert anchor in h, f"view-model block {kind!r} (anchor {anchor}) not rendered in html"
