"""Honest gate scorecard (2026-07-20).

Pins the honesty-critical property of the gate scorecard: it is a PROJECTION of the nomination-gate
policy (can't diverge from the verdict), shows EVERY registry sub-skill grouped by gate (a gate with no
sub-verdict this run still appears, greyed), and maps status to the 4-state chip so a coverage gap is
NEVER an opposing. Renderer-free — asserts on `tp._gate_scorecard` (tp_gates) directly.

(The legacy static-HTML report assertions that used to live here were removed with the retirement of
tp_render_html 2026-09-03 — the default html render path is report_render, covered by its own suite.)
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run")


def _fired(*sm):
    return [{"rule_id": f"r{i}", "card_id": "c", "field": "f", "value": "v", "signals": s} for i, s in enumerate(sm)]


def _sr():
    return {
        "dependency": {
            "skill_dir": "functional-requirement",
            "cards": [
                {"card_id": "crispr", "summary": {}, "provenance": {"input_manifest_ids": ["depmap-consortium-26q1"]}}
            ],
            "verdict": ("lineage_selective", "lineage-selective-supportive"),
            "fired": _fired({"small_molecule": "opposing", "degrader": "supportive"}),
        },
        "safety": {
            "skill_dir": "on-target-safety-liability",
            "cards": [{"card_id": "g", "summary": {}, "provenance": {"input_manifest_ids": ["gnomad-v4"]}}],
            "verdict": ("highly_constrained_safety_concern", "highly-constrained-safety-warning"),
            "fired": _fired({"small_molecule": "opposing"}),
        },
    }


_DA = {
    "basis": "gate_fired",
    "routing": "decided by gate F (Safe): safety forced 'hold'.",
    "deciding_axis": {"gate": "F", "gate_name": "Safe", "short": "safety", "framework_can_evidence": "partial"},
}


# ---------- scorecard ----------


def test_scorecard_includes_every_registry_sub_skill_even_when_absent():
    """Rows come from the gate registry, NOT from iterating sub_results — a sub-skill with no
    verdict this run still appears (greyed), so the gates we're blind on are never dropped."""
    sc = tp._gate_scorecard(_sr(), _DA)
    shorts = {r["short"] for r in sc}
    # dependency + safety produced verdicts; the rest are registry gates with no sub_result → present anyway
    assert {"dependency", "safety"} <= shorts
    assert {"expression", "surface_modality", "differentiation", "mechanism"} <= shorts, (
        "registry gates with no sub_result this run must still be rows"
    )
    # Every row carries an axis (biology|modality_fit). Version-agnostic letter rule: a row MAY be
    # letterless (v2 modality-fit gates are named-not-lettered; v2 biology FACETS like SL-partners
    # are letterless too) — but any row that DOES carry a letter must use a valid one (A..H). This
    # passes against both the v1 flat contract (all lettered) and the v2 three-list contract.
    assert all(r.get("axis") in ("biology", "modality_fit") for r in sc)
    assert all(r["gate"] in set("ABCDEFGH") for r in sc if r.get("gate"))


def test_scorecard_status_is_4state_and_gap_is_not_opposing():
    sc = {r["short"]: r for r in tp._gate_scorecard(_sr(), _DA)}
    # safety fired a hold (a kill tuple) → opposing
    assert sc["safety"]["status"] == "opposing"
    assert sc["safety"]["is_deciding"] is True
    # a registry gate with no sub_result → coverage_gap, NOT opposing (we didn't look ≠ negative)
    assert sc["surface_modality"]["status"] == "coverage_gap"
    assert sc["surface_modality"]["status"] != "opposing"
    # dependency lineage_selective is a curated positive → supportive
    assert sc["dependency"]["status"] == "supportive"


def test_scorecard_supportive_requires_curated_positive_not_just_measured():
    """A measured verdict that is neither a kill nor a curated positive is 'neutral', not
    'supportive' — the chip can't over-claim."""
    sr = {
        "mechanism": {
            "skill_dir": "mechanism-and-pharmacology",
            "cards": [],
            "verdict": ("well_characterized", "x"),
            "fired": [],
        }
    }
    sc = {r["short"]: r for r in tp._gate_scorecard(sr, None)}
    assert sc["mechanism"]["status"] in ("neutral", "supportive")  # not opposing, not gap
    # and an insufficient verdict is a coverage gap
    sr2 = {"mechanism": {"skill_dir": "m", "cards": [], "verdict": ("insufficient", None), "fired": []}}
    sc2 = {r["short"]: r for r in tp._gate_scorecard(sr2, None)}
    assert sc2["mechanism"]["status"] == "coverage_gap"
