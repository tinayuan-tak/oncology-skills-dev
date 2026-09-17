"""Step 2b increment 1 — the EVIDENCE_SIGNALS block surfaces the salient MEASURED fields (evidence, not
a ranked verdict). Relevance is the per-field salience role, so every card's decisive datum shows and
nothing is picked. The block reuses the spine's already-assembled readings + joins the Step-1 descriptor.
"""

from __future__ import annotations

from _skills_common.report_render import build_ir, vocab
from _skills_common.report_render._fixtures import make_nomination
from _skills_common.report_render.backends import render as be_render
from _skills_common.report_render.ir import _evidence_signals_block
from _skills_common.report_render.spec import resolve_spec

_KE = {
    "effect": {"metric": "median_chronos", "value": -1.18, "direction": "lower_is_stronger"},
    "significance": {"stat": "q_value", "value": 3.8e-16},
    "top_strata": [{"label": "COADREAD", "value": -1.4, "q": 1e-9, "n": 42, "role": "indication"}],
}


def _selected(cards):
    return [("dependency", {"evidence_graph": {"cards": cards}}, "gating")]


def _card(**over):
    c = {
        "id": "pan-cancer-crispr-dependency-distribution",
        "measurement_type": "crispr_lof_dependency",
        "role": "primary",
        "key_evidence": _KE,
        "confidence": {"n": 1538},
    }
    c.update(over)
    return c


def test_block_surfaces_the_salient_datum_and_the_descriptor():
    blk = _evidence_signals_block(_selected([_card()]))
    assert blk is not None and blk.kind == vocab.EVIDENCE_SIGNALS
    row = blk.payload["rows"][0]
    assert row["short"] == "dependency"
    assert row["measurement_type"] == "crispr_lof_dependency"
    assert row["measured"] is True
    assert "CHRONOS" in (row["reading"] or "")  # the decisive datum in words
    # Step-1 descriptor is attached for the measurement_type's effect field (machine-side tuple)
    assert row["descriptor"]["role"] == "effect"
    assert row["descriptor"]["units"] == "CHRONOS"
    assert row["descriptor"]["significance_field"] == "q_value"


def test_every_card_shows_no_ranking_no_pick():
    # two salient cards on one skill → BOTH appear (relevance is per-field, not a single per-skill pick)
    blk = _evidence_signals_block(_selected([_card(id="card-a"), _card(id="card-b")]))
    ids = {r["card_id"] for r in blk.payload["rows"]}
    assert ids == {"card-a", "card-b"}


def test_rollup_counts_measured_vs_looked_at_but_unmeasured():
    # one card with a decisive datum + one consulted card that surfaced none → 1 measured, 1 unmeasured.
    # This is the roll-up over EVIDENCE (counts), not a polarity ranking.
    blk = _evidence_signals_block(_selected([_card(id="has-datum"), _card(id="empty", key_evidence=None)]))
    ru = blk.payload["rollup"]
    assert ru["n_measured"] == 1
    assert ru["n_unmeasured"] == 1
    assert ru["n_skills"] == 1
    assert ru["by_skill"]["dependency"] == {"title": "Functional dependency", "measured": 1, "unmeasured": 1}


def test_fail_soft_when_no_evidence():
    assert _evidence_signals_block([("dependency", {}, "gating")]) is None  # no evidence_graph
    assert _evidence_signals_block(_selected([{"id": "x", "key_evidence": None}])) is None  # no datum
    assert _evidence_signals_block([]) is None


def _nomination_with_eg():
    return {
        "target_report": {
            "target_call": {"recommendation": "advance", "deciding_axis": {"deciding_axes": [{"short": "dependency"}]}},
            "skill_reports": {
                "dependency": {
                    "call": "selective_dependency",
                    "polarity": "supports",
                    "role": "gating",
                    "evidence_graph": {"cards": [_card()]},
                }
            },
        }
    }


def test_tier_gated_to_evidence_depth_l2():
    nom = _nomination_with_eg()
    at_l2 = [
        b for b in build_ir(nom, resolve_spec(level="L2", scope="all")).overview if b.kind == vocab.EVIDENCE_SIGNALS
    ]
    at_l1 = [
        b for b in build_ir(nom, resolve_spec(level="L1", scope="all")).overview if b.kind == vocab.EVIDENCE_SIGNALS
    ]
    assert len(at_l2) == 1  # present at evidence depth
    assert len(at_l1) == 0  # not at summary depth (TIER == 2)


def _lead_present(ir, spec) -> bool:
    """The lead-preset guard invariant: a demoted verdict must not leave a preset's headline empty."""
    if spec.lead == "recommendation":
        return bool(ir.header.payload.get("recommendation"))
    if spec.lead == "deciding_axis":
        return bool(ir.header.payload.get("deciding_short"))
    return True


def test_lead_preset_guard_headline_never_silently_empty():
    """After the ★/○ inversion the verdict is optional — but a preset that LEADS with the recommendation
    or the deciding axis must still render it. Guards the demotion: exec-brief/deck lead with the
    recommendation, reviewer-dossier/full with the deciding axis."""
    nom = make_nomination()
    for preset in ("exec-brief", "deck", "reviewer-dossier", "full"):
        spec = resolve_spec(preset=preset)
        assert _lead_present(build_ir(nom, spec), spec), f"{preset}: lead field ({spec.lead}) missing"


def test_lead_guard_can_fail_when_the_lead_is_stripped():
    """The guard is not vacuous: strip the recommendation and a recommendation-led preset fails it."""
    import copy

    nom = copy.deepcopy(make_nomination())
    nom["target_report"]["target_call"].pop("recommendation", None)
    nom["target_report"]["target_call"].pop("nomination_verdict", None)
    spec = resolve_spec(preset="exec-brief")  # leads with recommendation
    assert not _lead_present(build_ir(nom, spec), spec)


def test_composed_html_surfaces_the_evidence_view_as_a_fourth_tab():
    from _skills_common.report_render import render_report

    h = render_report(_nomination_with_eg(), preset="full", backend="html")
    assert "data-v='evidence'" in h and "id='v-evidence'" in h and "Measured evidence" in h
    # fail-soft: a nomination with no evidence graph adds no evidence tab (no empty view)
    assert "data-v='evidence'" not in render_report(make_nomination(), preset="full", backend="html")


def test_reaches_the_machine_and_linearized_views():
    """Increment 1 surfaces the block in the views that emit every block: json (the programmatic
    consumer — kind + structured descriptor) and the linearized text/markdown reports. The COMPOSED html
    view is a curated 'v6 spine + convergence' surface, so wiring the evidence block into it is increment
    2's presentation work, when the block becomes load-bearing. (The STANDALONE subskill path is now
    wired — see test_standalone_skill_run_surfaces_the_evidence_view below.)"""
    ir = build_ir(_nomination_with_eg(), resolve_spec(level="L2", scope="all"))
    js = be_render(ir, "json")
    assert "evidence_signals" in js and "median_chronos" in js  # machine view carries kind + descriptor field
    for backend in ("text", "markdown"):
        assert "Measured evidence" in be_render(ir, backend)
    # html must still render without error (the block is simply not surfaced in the curated composed view yet)
    assert be_render(ir, "html").startswith("<!doctype html>")


def _standalone_decision_with_eg():
    """A standalone decision.json shape: headline.skill_report + a SIBLING headline.evidence_graph
    (as the dispatcher emits). _extract_skill merges the graph onto the skill_report, so the single-skill
    render path can draw the salient-measured-fields view."""
    return {
        "skill": "tumor-presence",
        "headline": {
            "skill_report": {"call": "present", "polarity": "supports", "role": "descriptive", "claim_chips": []},
            "evidence_graph": {"cards": [_card()]},
        },
    }


def test_standalone_skill_run_surfaces_the_evidence_view():
    """Increment-2 (#1410): a STANDALONE subskill run (e.g. tumor-presence, no full target_report) now
    surfaces EVIDENCE_SIGNALS in its own dashboard, scoped to that one skill (rollup n_skills=1). The
    data was always present in decision.headline.evidence_graph; this wires build_ir_for_skill to add
    the block, TIER-gated exactly as the composed path."""
    from _skills_common.report_render import build_ir_auto, render_skill_report

    src = _standalone_decision_with_eg()
    ir = build_ir_auto(src, resolve_spec(preset="full"))
    es = [b for b in ir.overview if b.kind == vocab.EVIDENCE_SIGNALS]
    assert len(es) == 1
    assert es[0].payload["rollup"]["n_skills"] == 1
    assert es[0].lens is None  # standalone convention: un-lensed → renders INLINE, not as composed tab chrome
    # the block renders INLINE in the standalone layout (header/card-view preserved, not flipped to composed)
    html = render_skill_report(src, backend="html", preset="full")
    assert "Measured evidence" in html
    assert 'class="titlerow"' in html  # standalone single-skill layout survives (not composed lens-tab chrome)
    assert "data-v='evidence'" not in html  # not the composed view-switch tab
    assert "Measured evidence" in render_skill_report(src, backend="text", preset="full")


def test_standalone_evidence_view_is_tier_gated_and_fail_soft():
    """TIER-gated exactly as the composed path (absent at summary depth L1), and absent when the
    standalone decision carries no evidence_graph (fail-soft — no empty view)."""
    from _skills_common.report_render import build_ir_auto

    src = _standalone_decision_with_eg()
    at_l1 = build_ir_auto(src, resolve_spec(level="L1", scope="all")).overview
    assert [b for b in at_l1 if b.kind == vocab.EVIDENCE_SIGNALS] == []  # TIER == 2, not summary depth
    bare = {"skill": "tumor-presence", "headline": {"skill_report": {"role": "descriptive", "claim_chips": []}}}
    at_full = build_ir_auto(bare, resolve_spec(preset="full")).overview
    assert [b for b in at_full if b.kind == vocab.EVIDENCE_SIGNALS] == []  # no evidence_graph → no block
