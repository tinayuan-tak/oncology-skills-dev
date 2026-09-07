"""report_render — the faceted lens-switcher (PR1/PR2): lens grouping, the persistent advisory banner
with the LLM↔deterministic mismatch flag, anchor-routed synthesis notes, and the embedded sub-skill
signal×confidence scatter + sub-group bands. The lens layer is a presentation grouping — the verdict
spine is untouched; the standalone single-skill path stays un-lensed (flat fallback)."""

import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render._fixtures import make_decision_json, make_nomination
from _skills_common.report_render import build_ir, build_ir_for_skill, render_report, resolve_spec, vocab


def _lens_ids(ir):
    return [lid for lid, _title, _items in ir.lenses()]


# -- lens grouping ------------------------------------------------------------------------------
def test_composed_report_groups_into_lenses_in_canonical_order():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    assert _lens_ids(ir) == list(vocab.LENS_ORDER)  # all five, in order
    by = {lid: items for lid, _t, items in ir.lenses()}
    # sections live in the Signals lens; the per-skill sections + the scatter + strip are all there.
    signals_kinds = [it.kind if k == "block" else "section" for k, it in by[vocab.LENS_SIGNALS]]
    assert "section" in signals_kinds and vocab.SIGNALS_OVERVIEW in signals_kinds
    assert vocab.SIGNALS_SCATTER in signals_kinds
    # modality/risk/biology carry their projection blocks.
    assert vocab.MODALITY_MATRIX in [it.kind for k, it in by[vocab.LENS_MODALITY] if k == "block"]
    assert vocab.RISK_6DIM in [it.kind for k, it in by[vocab.LENS_RISK] if k == "block"]


def test_header_and_about_are_chrome_not_a_lens():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    assert ir.header.lens is None and (ir.about is None or ir.about.lens is None)


def test_standalone_skill_is_unlensed_flat_fallback():
    ir = build_ir_for_skill(
        make_decision_json()["headline"]["skill_report"], resolve_spec("full"), skill_name="on-target-safety-liability"
    )
    assert ir.lenses() == []  # nothing lens-annotated → backends use the flat layout
    assert ir.banner is None
    # renders without a tab bar (the CSS always defines .lens-* rules; assert the tab DOM is absent)
    html = render_report(make_decision_json(), preset="full", backend="html")
    assert "class='lens-radio'" not in html and "class='lens-tabs'" not in html


# -- persistent advisory banner + mismatch ------------------------------------------------------
def test_banner_carries_exec_summary_and_flags_llm_mismatch():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    assert ir.banner is not None and ir.banner.kind == vocab.SYNTHESIS_BANNER
    p = ir.banner.payload
    assert p["executive_summary"] and "[SAF-LOF-01" not in p["executive_summary"]  # citations lifted out
    # target_call is "hold", the LLM said "nominate" → mismatch surfaced (deterministic wins).
    assert p["mismatch"] and p["mismatch"]["deterministic"] == "hold" and p["mismatch"]["llm"] == "nominate"
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "advisory" in h and "mismatch flagged" in h
    # the banner is chrome — above the tabs, not inside a panel.
    assert h.index("class='card narr'") < h.index("class='lens-tabs'")


def test_banner_absent_when_no_synthesis():
    nom = make_nomination()
    nom.pop("llm_synthesis")
    assert build_ir(nom, resolve_spec("full")).banner is None


# -- anchor-routed synthesis notes --------------------------------------------------------------
def test_synthesis_notes_route_to_topical_lens_by_anchor():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    notes = {b.lens: b for b in ir.overview if b.kind == vocab.SYNTHESIS_NOTE}
    # the against-arg cites a safety rule → Risk lens; the for-arg cites a dependency rule → Signals lens.
    assert vocab.LENS_RISK in notes and vocab.LENS_SIGNALS in notes
    assert any(n["stance"] == "against" for n in notes[vocab.LENS_RISK].payload["notes"])
    # nothing routes to Decision (it already carries the consolidated SYNTHESIS block).
    assert vocab.LENS_DECISION not in notes


# -- embedded sub-skill view: scatter + sub-group bands -----------------------------------------
def test_section_carries_subgroup_bands_and_scatter_at_evidence_depth():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    safety = next(s for s in ir.sections if s.short == "safety")
    kinds = [b.kind for b in safety.blocks]
    assert vocab.SUBGROUP_BANDS in kinds and vocab.SIGNALS_SCATTER in kinds
    bands = next(b for b in safety.blocks if b.kind == vocab.SUBGROUP_BANDS)
    assert any(r["conflict"] for r in bands.payload["sub_groups"])  # the corroboration sub-group conflicts


def test_embedded_detail_gated_below_evidence_depth():
    ir = build_ir(make_nomination(), resolve_spec(level="L1"))
    safety = next(s for s in ir.sections if s.short == "safety")
    kinds = [b.kind for b in safety.blocks]
    assert vocab.SUBGROUP_BANDS not in kinds  # embedded detail is L2+ only
    assert vocab.SIGNALS_SCATTER not in kinds  # per-skill scatter is gated with the bands (L2)


def test_section_scatter_absent_without_subgroup_signals():
    nom = make_nomination()
    for rep in nom["target_report"]["skill_reports"].values():
        rep.pop("subgroup_signals", None)
    ir = build_ir(nom, resolve_spec("full"))
    for sec in ir.sections:
        assert vocab.SUBGROUP_BANDS not in [b.kind for b in sec.blocks]  # fail-soft: omitted


# -- json + backends carry the grouping ---------------------------------------------------------
def test_json_exposes_lenses_and_banner():
    obj = json.loads(render_report(make_nomination(), preset="full", backend="json"))
    assert obj.get("banner") and obj["banner"]["kind"] == vocab.SYNTHESIS_BANNER
    lids = [L["id"] for L in obj.get("lenses") or []]
    assert lids == list(vocab.LENS_ORDER)


def test_signals_lens_sections_collapse_deciding_open():
    h = render_report(make_nomination(), preset="full", backend="html")
    assert "skill-collapse" in h
    # the deciding axis (safety, killer) opens by default; a non-deciding gating skill stays collapsed.
    assert "<details class='card pol-killer skill-collapse' open>" in h
    assert "<details class='card pol-supportive skill-collapse'>" in h  # dependency, closed
    # the embedded detail (sub-group bands) is still in the DOM inside the collapsed section.
    assert "Sub-group bands" in h


def test_all_string_backends_render_new_blocks():
    for backend in ("text", "markdown", "html"):
        out = render_report(make_nomination(), preset="full", backend=backend)
        assert "confidence" in out.lower()  # scatter/bands render their axes/columns
        assert out  # no crash on any backend
