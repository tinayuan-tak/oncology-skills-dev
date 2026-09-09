"""Phase 1 (dashboard consolidation): the shared dispatcher emits a best-effort per-subskill
`dashboard.html` on every run via report_render (the ONE renderer), default-on, `--no-dashboard`
opt-out. The dashboard is DISPLAY-ONLY — it reads only the in-memory decision and writes a SEPARATE
file, so `decision.json` is byte-identical whether or not it renders.

These tests cover the render path + the invariants without a full live subskill run (which needs S3):
the end-to-end wire-up is exercised by a real run in the phase's verification step.
"""

import copy
import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import render_skill_report

# reuse the standalone-decision fixture (headline.skill_report + optional headline.evidence_graph)
from _skills_common.tests.test_report_render_standalone_from_decision import _decision


def test_no_dashboard_flag_present_and_defaults_off():
    """The dispatcher parser exposes --no-dashboard (store_true, default False = dashboard on)."""
    from _skills_common.dispatcher import _build_run_parser

    ns = _build_run_parser().parse_args(["--target", "KRAS", "--indication", "COADREAD", "--out", "/tmp/x"])
    assert hasattr(ns, "no_dashboard")
    assert ns.no_dashboard is False  # default-on dashboard
    ns2 = _build_run_parser().parse_args(
        ["--target", "KRAS", "--indication", "COADREAD", "--out", "/tmp/x", "--no-dashboard"]
    )
    assert ns2.no_dashboard is True


def test_render_skill_report_from_decision_produces_html():
    """The exact call the dispatcher makes renders a self-contained rich dashboard string."""
    dec = _decision(with_graph=True)
    html = render_skill_report(dec, backend="html", preset="full", target="KRAS", indication="COADREAD")
    assert "<!doctype html>" in html.lower() or "<!DOCTYPE" in html
    # rich per-question evidence view is present when the graph carries questions
    assert any(cls in html for cls in ("hmcell", "cardln", "cfp-chip", "question"))


def test_dashboard_render_does_not_mutate_decision():
    """DISPLAY-ONLY invariant: rendering the dashboard must not mutate the decision (the guarantee
    that emitting dashboard.html leaves decision.json byte-identical)."""
    dec = _decision(with_graph=True)
    before = json.dumps(dec, sort_keys=True, default=str)
    snapshot = copy.deepcopy(dec)
    _ = render_skill_report(dec, backend="html", preset="full", target="KRAS", indication="COADREAD")
    after = json.dumps(dec, sort_keys=True, default=str)
    assert after == before, "render_skill_report mutated the decision"
    assert dec == snapshot


def test_asset_root_param_accepted():
    """render_skill_report accepts asset_root (threaded to the html backend for inline SVGs),
    mirroring render_report — the dispatcher passes it only when --figures ran."""
    dec = _decision(with_graph=True)
    html_none = render_skill_report(dec, backend="html", preset="full", asset_root=None)
    html_set = render_skill_report(dec, backend="html", preset="full", asset_root="/tmp")
    assert html_none and html_set  # both render without error
