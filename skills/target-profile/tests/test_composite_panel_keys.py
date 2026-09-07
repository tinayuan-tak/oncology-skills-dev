"""Guard: the composite 'at a glance' panel's PHASE_META sub_keys must be short names the
target-profile composer actually emits.

The bug this catches (2026-08-10 review, M5 + sibling): PHASE_META["F"]["sub_key"] was
"tractability" and ["H"]["sub_key"] was "population", but the composer's SUB_SKILLS emit
"tractability_sm" (renamed in the 2026-07-14 SM/biologics split) and have NO "population" short
name (patient-population-and-access was deleted 2026-07-14, folded into "genomic_alteration").
render_composite_panel does `sub_results.get(short)`, so a stale key silently rendered the badge
as "no rule verdict" on EVERY target — a blank badge no verdict-golden could catch (figure code
is outside the byte-stable snapshot).

Bedrock-free / render-free: parses the SUB_SKILLS literal via ast and reads PHASE_META directly.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _test_support import load_module

SKILLS = Path(__file__).resolve().parents[2]  # .../skills
# SUB_SKILLS moved from run.py to tp_fanout.py in the 2026-08-16 god-module split.
COMPOSER = SKILLS / "target-profile" / "scripts" / "tp_fanout.py"
PANEL = SKILLS / "_skills_common" / "composite_panel.py"

# sub_keys that are panel-synthetic, not composer short names (rendered from llm_output / empty).
_SYNTHETIC_SUB_KEYS = {"_overall"}


def _sub_skill_short_names() -> set[str]:
    """The short names in target-profile's SUB_SKILLS = [(skill_dir, short), ...] literal."""
    tree = ast.parse(COMPOSER.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "SUB_SKILLS" for t in node.targets):
            return {e.elts[1].value for e in node.value.elts}
    raise AssertionError("SUB_SKILLS literal not found in target-profile/scripts/run.py")


def _phase_meta() -> dict:
    """Import composite_panel.PHASE_META without importing the whole skills package."""
    return load_module(PANEL, "_composite_panel_under_test").PHASE_META


def test_phase_meta_sub_keys_are_reachable():
    """Every non-synthetic PHASE_META sub_key must be a short name the composer emits — else the
    badge silently renders 'no rule verdict' for every target."""
    shorts = _sub_skill_short_names()
    unreachable = {
        phase: meta["sub_key"]
        for phase, meta in _phase_meta().items()
        if meta["sub_key"] not in _SYNTHETIC_SUB_KEYS and meta["sub_key"] not in shorts
    }
    assert not unreachable, (
        f"PHASE_META sub_keys not present in SUB_SKILLS short names {sorted(shorts)}: {unreachable}. "
        "A stale key renders that badge blank on every target. Update PHASE_META (and the matching "
        "branch in _metric_lines_for) to the composer's current short name."
    )
