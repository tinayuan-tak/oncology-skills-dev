"""Tests for the role-grouped axis hierarchy (_render_axis_hierarchy) — the consumer-surface
'forest not tree' render. Gating axes (verdict spine) · Context (measured, does not gate) · Inert.
Reads synthesis.skill_report_rollup.by_role (grouped upstream); verdict-inert; byte-stable when absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from scripts.render_markdown import _render_axis_hierarchy  # noqa: E402


def _syn(gating, descriptive, inert):
    return {
        "skill_report_rollup": {
            "by_role": {
                "gating": [{"short": s, "call": c, "polarity": p} for s, c, p in gating],
                "descriptive": [{"short": s, "call": c, "polarity": "not_scored"} for s, c in descriptive],
                "inert": [{"short": s, "call": c, "polarity": "not_scored"} for s, c in inert],
            }
        }
    }


def test_renders_three_role_groups():
    syn = _syn(
        gating=[("selectivity", "selective", "neutral"), ("safety", "concern", "opposing")],
        descriptive=[("expression", "broadly_expressed"), ("immune_context", "intermediate")],
        inert=[("cis_coherence", "uncoupled")],
    )
    md = "\n".join(_render_axis_hierarchy(syn))
    assert "## Evidence Axes by Role" in md
    assert "### Gating (2) — the verdict spine" in md
    assert "### Context (2) — measured, does not gate" in md
    assert "### Inert (1)" in md
    # a gating axis shows its polarity; a context axis is rendered without a polarity column
    assert "| selectivity | selective | neutral |" in md
    assert "| expression | broadly_expressed |" in md


def test_gateless_axis_gets_a_home_in_context():
    # the point of the change: an axis that does not gate is NOT dropped — it renders under Context.
    syn = _syn(gating=[("safety", "ok", "supportive")], descriptive=[("literature_context", "supportive")], inert=[])
    md = "\n".join(_render_axis_hierarchy(syn))
    assert "literature_context" in md
    assert "### Context (1)" in md


def test_byte_stable_when_rollup_absent():
    # an un-migrated package carrying no rollup renders nothing here (no spurious section).
    assert _render_axis_hierarchy({}) == []
    assert _render_axis_hierarchy({"skill_report_rollup": {}}) == []
    assert _render_axis_hierarchy({"skill_report_rollup": {"by_role": {}}}) == []


def test_inert_group_omitted_when_empty():
    syn = _syn(gating=[("safety", "ok", "supportive")], descriptive=[], inert=[])
    md = "\n".join(_render_axis_hierarchy(syn))
    assert "### Inert" not in md
    assert "### Context" not in md
    assert "### Gating (1)" in md


def test_absent_call_renders_dash_not_blank():
    syn = {"skill_report_rollup": {"by_role": {"gating": [{"short": "x", "call": None, "polarity": "neutral"}]}}}
    md = "\n".join(_render_axis_hierarchy(syn))
    assert "| x | — | neutral |" in md
