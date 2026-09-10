"""Dashboard consolidation Phase 4 — LOCK the "embedded == standalone" invariant.

The whole point of the consolidation: ONE renderer (report_render) + ONE design system render the
rich evidence view (fingerprint heatmap, dataset→data→rule→verdict card chains, literature axes) the
SAME way in BOTH surfaces:
  - the standalone per-subskill dashboard (render_skill_report from a decision.json), and
  - the composed target-profile's embedded per-skill drill-down (render_report from a nomination).

Both draw from the same carried headline.evidence_graph through the same ir/backends blocks and the
same _CSS tokens (incl. the Phase-2 omics/literature two-tone --lit ring). This test fails if a future
change re-forks either surface onto a divergent renderer/design (the fragmentation this arc retired:
example-gallery / eg-sandbox / render_review each re-implemented these blocks).
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import render_report, render_skill_report
from _skills_common.report_render._fixtures import make_nomination

# the standalone-decision fixture (headline.skill_report + headline.evidence_graph)
from _skills_common.tests.test_report_render_standalone_from_decision import _decision

# the shared evidence-graph design vocabulary that MUST appear identically in both surfaces
_RICH_CLASSES = ("hmcell", "cardln", "litdot")
_TWO_TONE_RING = "border:2px solid var(--lit)"  # Phase-2 omics/literature two-tone


def _composed_html() -> str:
    return render_report(make_nomination(), preset="full", backend="html")


def _standalone_html() -> str:
    return render_skill_report(_decision(with_graph=True), preset="full", backend="html")


def test_rich_evidence_view_shares_one_design_system():
    """2026-09-10 refine: the composed v6 HTML no longer INLINES the per-subskill dashboards, but it still
    bundles the SAME scoped subskill stylesheet, so the rich evidence-view design classes (fingerprint
    heatmap / card chains / literature dots) resolve identically in both surfaces — proof they render
    through the ONE renderer (report_render) + ONE design system, not divergent per-surface styles. The
    STANDALONE subskill page additionally renders those classes as live DOM."""
    composed, standalone = _composed_html(), _standalone_html()
    for cls in _RICH_CLASSES:
        assert cls in composed, f"composed page dropped the shared design class {cls}"
        assert cls in standalone, f"standalone dashboard missing {cls}"
    # the standalone page renders them as real DOM (not only CSS) — the composed page no longer inlines
    # the subskill sections, so it carries the design tokens without the embedded dashboards.
    body = standalone.split("</style>", 1)[1]
    assert any(c in body for c in _RICH_CLASSES), "standalone must render the rich view as DOM, not only CSS"


def test_shared_design_system_two_tone_in_both():
    """The Phase-2 --lit ring (one design system) is present in both surfaces — proof they render
    through the same _CSS, not divergent per-surface styles."""
    assert _TWO_TONE_RING in _composed_html()
    assert _TWO_TONE_RING in _standalone_html()


def test_both_surfaces_are_self_contained_html_documents():
    for h in (_composed_html(), _standalone_html()):
        assert "<!doctype html>" in h.lower() or "<!DOCTYPE" in h
