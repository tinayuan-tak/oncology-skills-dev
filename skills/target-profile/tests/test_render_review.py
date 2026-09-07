"""render_review.py — build_html smoke test.

Hermetic: builds a tiny run dir (nomination.json + evidence_package.json + one
subskills/<short>/package.json) and asserts build_html renders the top-level
sections as plain <section> blocks. The former per-axis "Why this verdict"
narrative panel (d) was removed — its trace is superseded by the cross-evidence
synthesis (section 1) and the deterministic-vs-literature risk comparison
(section 2); this test guards that it stays gone. No live run needed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_review as rr  # noqa: E402


def _run_dir(tmp_path: Path) -> Path:
    nom = {
        "target": "BRAF",
        "indication": "COADREAD",
        "llm_synthesis": {},
        "narrative_by_axis": {
            "safety": {
                "axis": "safety",
                "gate": "safety",
                "verdict": "highly_constrained_safety_concern",
                "driving_rule_id": "highly-constrained-safety-warning",
                "scan_depth": "single_rule",
                "movers": [
                    {
                        "rule_id": "highly-constrained-safety-warning",
                        "card_id": "gnomad-lof-constraint",
                        "role": "driver",
                        "signals": {"small_molecule": "opposing"},
                        "sentence": "Highly LoF-constrained in gnomAD.",
                        "killer_message": None,
                    }
                ],
                "dissenters": [],
                "flip_conditions": [],
                "gaps": [],
                "rule_sentences": {},
            }
        },
    }
    (tmp_path / "nomination.json").write_text(json.dumps(nom))
    (tmp_path / "evidence_package.json").write_text(
        json.dumps({"context": {"target": "BRAF", "indication": "COADREAD"}})
    )
    sub = tmp_path / "subskills" / "safety"
    sub.mkdir(parents=True)
    (sub / "package.json").write_text(
        json.dumps(
            {
                "verdict": "highly_constrained_safety_concern",
                "driving_rule_id": "highly-constrained-safety-warning",
                "fired_rules": [
                    {
                        "rule_id": "highly-constrained-safety-warning",
                        "card_id": "gnomad-lof-constraint",
                        "signals": {"small_molecule": "opposing"},
                        "is_driving": True,
                    }
                ],
                "cards": [{"card_id": "gnomad-lof-constraint", "summary": {"constraint_class": "highly_constrained"}}],
            }
        )
    )
    return tmp_path


def test_build_html_renders_top_level_sections(tmp_path):
    html = rr.build_html(_run_dir(tmp_path))
    # sections render as plain <section><h2> blocks (no longer collapsible <details class=sec>)
    for heading in ("1 · Cross-evidence synthesis", "2 · 6-dimension risk assessment", "4 · Per-sub-skill"):
        assert heading in html, f"missing section: {heading}"
    assert "<section" in html
    assert "details class=sec" not in html


def test_why_verdict_panel_removed(tmp_path):
    """The per-axis 'Why this verdict' narrative panel (d) is gone — guard the removal."""
    html = rr.build_html(_run_dir(tmp_path))
    assert "Why this verdict" not in html
    assert "No narrative for this axis" not in html


def test_reads_decision_spine_from_nested_target_call(tmp_path):
    """Full-nest (2026-09-03): the decision spine lives under target_call, NOT top-level. render_review
    must read the recommendation from target_call.gate when the top-level keys are absent (the new shape)."""
    nom = {
        "target": "BRAF",
        "indication": "COADREAD",
        "llm_synthesis": {},
        # NEW shape: no top-level recommendation_gate/confidence_tier — nested under target_call only.
        "target_call": {
            "schema": "target_call.v1",
            "recommendation": "hold",
            "gate": {"fired": True},
            "confidence": {"tier": "high"},
        },
    }
    (tmp_path / "nomination.json").write_text(json.dumps(nom))
    (tmp_path / "evidence_package.json").write_text(
        json.dumps({"context": {"target": "BRAF", "indication": "COADREAD"}})
    )
    sub = tmp_path / "subskills" / "safety"
    sub.mkdir(parents=True)
    (sub / "package.json").write_text(json.dumps({"verdict": "x", "fired_rules": [], "cards": []}))
    html = rr.build_html(tmp_path)
    # gate.fired True (read from the NESTED location) → the "hold / block" recommendation renders
    assert "hold / block" in html
