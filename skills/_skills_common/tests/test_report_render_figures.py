"""report_render — the FIGURE JOIN: nomination.card_figures joined into per-skill sections as FIGURE
blocks with a spine-polarity verdict badge, card→owner routing, level/medium gating, and backend embed.

Fixture shapes mirror the REAL nomination (top-level sub_verdicts.cards_used + card_figures descriptors)
so the join is exercised against real shapes, not fixture-invented ones (the #990 lesson)."""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import build_ir, render_report, resolve_spec, vocab
from _skills_common.report_render._fixtures import make_decision_json, make_nomination


def _section(ir, short):
    return next((s for s in ir.sections if s.short == short), None)


def _figs(ir, short):
    """Card-figure blocks in a section (the join's output — carry a card_id). The legacy
    skill_report.figures hero blocks (no card_id) are excluded so counts test the join only."""
    sec = _section(ir, short)
    return [b for b in (sec.blocks if sec else []) if b.kind == vocab.FIGURE and b.payload.get("card_id")]


# -- the join + owner routing --------------------------------------------------------------------
def test_card_figures_join_into_their_owning_section():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    dep = _figs(ir, "dependency")
    assert [b.payload["card_id"] for b in dep] == [
        "pan-cancer-crispr-dependency-distribution",
        "pan-cancer-crispr-dependency-distribution",
    ]  # L3: 2 svgs
    assert {b.payload["card_id"] for b in _figs(ir, "safety")} == {"gnomad-lof-constraint", "normal-tissue-liability"}


def test_shared_card_routes_to_the_gating_lister_not_the_descriptive_one():
    # normal-tissue-liability is in BOTH safety (gating) and target_intrinsic (descriptive) cards_used.
    ir = build_ir(make_nomination(), resolve_spec("full"))
    safety_cards = {b.payload["card_id"] for b in _figs(ir, "safety")}
    ti_cards = {b.payload["card_id"] for b in _figs(ir, "target_intrinsic")}
    assert "normal-tissue-liability" in safety_cards
    assert "normal-tissue-liability" not in ti_cards  # no duplication across sections
    assert ti_cards == {"functional-gene-state"}  # only its own-lens card


def test_figure_ref_is_prefixed_for_the_run_root():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    for b in _figs(ir, "safety"):
        assert b.payload["ref"].startswith("figures/cards/")


# -- the verdict badge (spine polarity) ----------------------------------------------------------
def test_badge_is_derived_from_the_sections_spine_polarity():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    assert all(b.payload["status"]["label"] == "SUPPORTS" for b in _figs(ir, "dependency"))  # supportive
    assert all(b.payload["status"]["label"] == "KILLER" for b in _figs(ir, "safety"))  # killer
    # a descriptive skill's figure is an honest CONTEXT no-call, never a grey killer.
    assert all(b.payload["status"]["signal"] == "context" for b in _figs(ir, "target_intrinsic"))


# -- level + medium gating -----------------------------------------------------------------------
def test_L2_shows_primary_only_L3_shows_all_svgs():
    l2 = build_ir(make_nomination(), resolve_spec(level="L2", medium="both"))
    l3 = build_ir(make_nomination(), resolve_spec(level="L3", medium="both"))
    # the dependency card has a primary + a secondary SVG (+ a plotly sibling).
    assert len(_figs(l2, "dependency")) == 1
    assert _figs(l2, "dependency")[0].payload["primary"] is True
    assert len(_figs(l3, "dependency")) == 2


def test_no_figures_below_the_figure_tier():
    l1 = build_ir(make_nomination(), resolve_spec(level="L1", medium="both"))
    assert _figs(l1, "dependency") == []


def test_plotly_sibling_is_carried_as_dynamic_ref_not_its_own_block():
    ir = build_ir(make_nomination(), resolve_spec("full"))
    primary = next(b for b in _figs(ir, "dependency") if b.payload["primary"])
    assert primary.payload["dynamic_ref"].endswith("figure_chronos_density.plotly.json")
    # the .plotly.json descriptor is never emitted as its own FIGURE block (no .plotly.json refs).
    assert not any(str(b.payload.get("ref") or "").endswith(".plotly.json") for b in _figs(ir, "dependency"))


def test_medium_text_suppresses_the_image_but_keeps_the_caption():
    ir = build_ir(make_nomination(), resolve_spec(level="L3", medium="text"))
    figs = _figs(ir, "dependency")
    assert figs and all(b.payload["show_image"] is False for b in figs)
    assert all(b.payload["caption"] for b in figs)


# -- backend embed -------------------------------------------------------------------------------
def test_html_embeds_image_and_status_pill():
    # per-subskill sections are no longer inlined in the composed v6 HTML — assert the HTML section-render
    # capability directly (the standalone subskill page uses the same _emit_standalone_section path).
    from _skills_common.report_render.backends.html import HtmlBackend

    ir = build_ir(make_nomination(), resolve_spec("full"))
    be = HtmlBackend()
    html = "".join(be._emit_standalone_section(s) for s in ir.sections if s.short in ("dependency", "safety"))
    assert "<img src='figures/cards/pan-cancer-crispr-dependency-distribution/" in html
    assert "fig-badge sig-supportive" in html and "SUPPORTS" in html
    assert "fig-badge sig-killer" in html and "KILLER" in html


def test_markdown_embeds_image_with_badge_in_caption():
    md = render_report(make_nomination(), preset="full", backend="markdown")
    assert "![" in md and "figures/cards/gnomad-lof-constraint/" in md
    assert "KILLER —" in md  # badge kept in the markdown caption


def test_text_fallback_names_figure_and_badge_without_image():
    txt = render_report(make_nomination(), backend="text", level="L3", medium="text")
    assert "FIGURE:" in txt.upper()
    assert "SUPPORTS —" in txt  # dependency figures badged in the text degrade path


# -- fail-soft / single-skill --------------------------------------------------------------------
def test_single_skill_render_has_no_card_figures_and_does_not_crash():
    # a standalone decision.json carries no top-level card_figures → the join is a graceful no-op.
    txt = render_report(make_decision_json(), backend="text", preset="full")
    assert "Target report" in txt


def test_nomination_without_card_figures_is_a_noop():
    nom = make_nomination()
    nom.pop("card_figures", None)
    ir = build_ir(nom, resolve_spec("full"))
    assert _figs(ir, "dependency") == [] and _figs(ir, "safety") == []
