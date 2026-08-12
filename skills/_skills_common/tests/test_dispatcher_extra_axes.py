"""Sweep-2 S2: run_wired_skill(extra_axes=...) merges the extra axis's fired rules into the emitted
decision['fired_rules'] + run_health.cards_fired, WITHOUT letting them touch the primary verdict."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import _skills_common.dispatcher as D  # noqa: E402


def _run(monkeypatch, tmp_path, extra_axes):
    cards_out = [
        {"card_id": "combo-crispr-screen",
         "summary": {"combination_opportunity_class": "strong"}, "interpretation_call": "strong"},
        {"card_id": "resistance-emergence-signature",
         "summary": {"resistance_emergence_class": "strong_resistance_signal"},
         "interpretation_call": "strong_resistance_signal"},
    ]
    monkeypatch.setattr(D, "resolve_cards", lambda cards, target, indication, **k: cards_out)

    def _rule(rid, cid):
        # full shape make_decision_json serializes (rule_id/card_id/field/value/dominant/rationale)
        return {"rule_id": rid, "card_id": cid, "field": "x_class", "value": "v",
                "dominant": True, "rationale": "r"}

    def fake_fired(card_outputs, axis, card_id_filter=None):
        if axis == "combination_opportunity":
            return [_rule("combination-strong", "combo-crispr-screen")]
        if axis == "resistance_emergence":
            return [_rule("resistance-strong-signal", "resistance-emergence-signature")]
        return []
    monkeypatch.setattr(D, "fired_rules", fake_fired)

    captured = {}

    def fake_write(**kw):
        captured["decision"] = kw["decision"]
        return {"tables": [], "figures": []}   # dispatcher len()s both after writing
    monkeypatch.setattr(D, "write_package", fake_write)

    verdict_seen = {}

    def verdict_fn(fired):
        verdict_seen["fired"] = [f["rule_id"] for f in fired]
        return ("combination_supported", "combination-strong")

    rc = D.run_wired_skill(
        skill_name="combo-and-resistance", skill_version="test",
        cards=["combo-crispr-screen", "resistance-emergence-signature"],
        axis="combination_opportunity", question="Q {target} {indication}",
        verdict_fn=verdict_fn,
        headline_fn=lambda cards, fired, vp: {"verdict": vp[0], "driving_rule_id": vp[1]},
        extra_axes=extra_axes,
        argv=["--target", "KRAS", "--indication", "COADREAD", "--out", str(tmp_path)],
    )
    return rc, captured["decision"], verdict_seen["fired"]


def test_extra_axes_merged_into_audit_spine(monkeypatch, tmp_path):
    rc, decision, verdict_fired = _run(monkeypatch, tmp_path, ["resistance_emergence"])
    fired_ids = {f["rule_id"] for f in decision["fired_rules"]}
    assert "combination-strong" in fired_ids
    assert "resistance-strong-signal" in fired_ids                      # the fix
    assert "resistance-emergence-signature" in decision["run_health"]["cards_fired"]
    assert verdict_fired == ["combination-strong"]                      # verdict saw PRIMARY only


def test_no_extra_axes_is_byte_identical(monkeypatch, tmp_path):
    rc, decision, _ = _run(monkeypatch, tmp_path, None)
    assert {f["rule_id"] for f in decision["fired_rules"]} == {"combination-strong"}
