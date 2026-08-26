"""render_review.py — the 'Why this verdict' narrative panel (d).

Hermetic: builds a tiny run dir (nomination.json with narrative_by_axis + one subskills/<short>/
package.json) and asserts the deterministic narrative panel renders movers / dissenters / flip
conditions (incl. the ⚑ recommendation-flip flag). No live run needed.
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
        "target": "BRAF", "indication": "COADREAD", "llm_synthesis": {},
        "narrative_by_axis": {"safety": {
            "axis": "safety", "gate": "safety", "verdict": "highly_constrained_safety_concern",
            "driving_rule_id": "highly-constrained-safety-warning", "scan_depth": "single_rule",
            "movers": [{"rule_id": "highly-constrained-safety-warning", "card_id": "gnomad-lof-constraint",
                        "role": "driver", "signals": {"small_molecule": "opposing"},
                        "sentence": "Highly LoF-constrained in gnomAD.", "killer_message": None}],
            "dissenters": [
                {"rule_id": "clingen-recessive-only-safety-reassurance", "card_id": "clingen-dosage",
                 "channel": "small_molecule", "signal": "supportive",
                 "sentence": "Recessive-only reassurance.", "killer_message": None},
                {"rule_id": "clingen-recessive-only-safety-reassurance", "card_id": "clingen-dosage",
                 "channel": "degrader", "signal": "supportive",
                 "sentence": "Recessive-only reassurance.", "killer_message": None}],
            "flip_conditions": [{"rule_id": "highly-constrained-safety-warning", "present": True,
                                 "to_verdict": "insufficient", "recommendation_flip": True, "sentence": ""}],
            "gaps": [{"kind": "strengthen", "availability": "insufficient", "missing_cards": []}],
            "rule_sentences": {}}}}
    (tmp_path / "nomination.json").write_text(json.dumps(nom))
    (tmp_path / "evidence_package.json").write_text(
        json.dumps({"context": {"target": "BRAF", "indication": "COADREAD"}}))
    sub = tmp_path / "subskills" / "safety"
    sub.mkdir(parents=True)
    (sub / "package.json").write_text(json.dumps({
        "verdict": "highly_constrained_safety_concern",
        "driving_rule_id": "highly-constrained-safety-warning",
        "fired_rules": [{"rule_id": "highly-constrained-safety-warning", "card_id": "gnomad-lof-constraint",
                         "signals": {"small_molecule": "opposing"}, "is_driving": True}],
        "cards": [{"card_id": "gnomad-lof-constraint", "summary": {"constraint_class": "highly_constrained"}}]}))
    return tmp_path


def test_why_verdict_panel_renders_movers_dissenters_flips(tmp_path):
    html = rr.build_html(_run_dir(tmp_path))
    assert "Why this verdict" in html
    for row in ("set by", "despite", "flips if"):
        assert row in html, f"missing row: {row}"
    assert "highly-constrained-safety-warning" in html          # driver / mover
    assert "clingen-recessive-only-safety-reassurance" in html  # dissenter
    assert "→ <b>insufficient</b>" in html                      # flip target
    assert "⚑ rec" in html                                      # recommendation-flip flag


def test_why_verdict_absent_narrative_shows_muted_note(tmp_path):
    d = _run_dir(tmp_path)
    nom = json.loads((d / "nomination.json").read_text())
    nom["narrative_by_axis"] = {}   # no narrative for safety
    (d / "nomination.json").write_text(json.dumps(nom))
    html = rr.build_html(d)
    assert "No narrative for this axis" in html   # graceful fallback, panel header still present
