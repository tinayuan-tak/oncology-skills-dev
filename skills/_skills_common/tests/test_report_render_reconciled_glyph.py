"""report_render — COMPOSED cross-axis reconciliation of the per-axis glyph.

A measured-negative CONTRADICTION the composed gate RETIRED (target_call.gate.hard_gates status ==
'reconciled' — e.g. the selectivity no-window KILL reconciled by an ADC/TCE surface fit) must render
NEUTRAL (glyph •, raw polarity retained) across the per-axis header glyph, the figure badge, the
diverging strip, the scatter, and the composed fingerprint — so the human report agrees with the gate,
scorecard, and LLM. COMPOSED-ONLY: the standalone single-skill path carries no gate, so it keeps the
honest ⛔. Sibling to the thesis de-escalation (_negative_expected_under_thesis)."""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import build_ir, build_ir_for_skill, render_report, resolve_spec
from _skills_common.report_render import ir as I


def test_reconciled_note_de_escalates_negative_only():
    rs = frozenset({"selectivity"})
    assert I._reconciled_note("selectivity", "killer", rs)
    assert I._reconciled_note("selectivity", "opposing", rs)
    assert I._reconciled_note("selectivity", "supportive", rs) is None  # never invents a positive
    assert I._reconciled_note("selectivity", "killer", frozenset()) is None  # not reconciled -> stands
    assert I._reconciled_note("dependency", "killer", rs) is None  # a different axis is untouched


def test_build_section_neutralizes_reconciled_header_glyph():
    rep = {"role": "gating", "call": "selective_but_broadly_normal", "polarity": "killer", "honest_phrase": "x"}
    spec = resolve_spec("full")
    hdr = I._build_section("selectivity", rep, spec, is_deciding=False, reconciled_shorts=frozenset({"selectivity"}))
    p = hdr.blocks[0].payload
    assert p["polarity"] == "neutral" and p["raw_polarity"] == "killer" and p["reconciled_note"]
    p2 = I._build_section("selectivity", rep, spec, is_deciding=False).blocks[0].payload
    assert p2["polarity"] == "killer" and p2["raw_polarity"] is None


def _nom_with_reconciled() -> dict:
    return {
        "target": "ERBB3",
        "indication": "LUAD",
        "target_report": {
            "skill_reports": {
                "selectivity": {
                    "role": "gating",
                    "call": "selective_but_broadly_normal",
                    "polarity": "killer",
                    "confidence": "moderate",
                },
                "dependency": {"role": "gating", "call": "non_dependent", "polarity": "killer", "confidence": "high"},
            },
            "target_call": {
                "recommendation": "veto",
                "gate": {
                    "hard_gates": [
                        {
                            "short": "selectivity",
                            "verdict": "selective_but_broadly_normal",
                            "disposition": "contradiction",
                            "status": "reconciled",
                        },
                        {"short": "dependency", "verdict": "non_dependent", "disposition": "gated", "status": "fired"},
                    ]
                },
            },
        },
    }


def test_build_ir_reconciles_only_the_gate_reconciled_axis():
    spec = resolve_spec("full")
    ir = build_ir(_nom_with_reconciled(), spec)
    hdr = {s.short: s.blocks[0].payload for s in ir.sections}
    assert hdr["selectivity"]["polarity"] == "neutral" and hdr["selectivity"]["raw_polarity"] == "killer"
    assert hdr["dependency"]["polarity"] == "killer"


def test_standalone_single_skill_keeps_honest_killer():
    """The standalone path carries no target_call.gate, so reconciliation is structurally dormant."""
    spec = resolve_spec("full")
    rep = {"role": "gating", "call": "selective_but_broadly_normal", "polarity": "killer", "confidence": "moderate"}
    ir = build_ir_for_skill(rep, spec, short="selectivity")
    assert ir.sections[0].blocks[0].payload["polarity"] == "killer"


def test_rendered_markdown_has_no_killer_glyph_for_reconciled_axis():
    md = render_report(_nom_with_reconciled(), preset="full", backend="markdown")
    sel_lines = [l for l in md.splitlines() if "Tumor selectivity" in l]
    assert sel_lines and all("⛔" not in l for l in sel_lines)
