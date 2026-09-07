"""cross-evidence-hypothesis — offline guards for the modality×safety seam (Phase 2) and the per-axis
certainty consumption (Phase 3), the integrator's consumption of the spine's new
synthesis.decision_facets layer + the safety_verdict_by_modality stamp on the safety sub_verdict.

No Bedrock: gate_ceiling / parse_certainty_by_axis / weakest_link_certainty are pure; the two run()-level
tests inject a stub synthesize_fn. Package fixtures are edited copies of evidence_package_new_blocks.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from _test_support import load_run_py

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import hypothesis_core as hc  # noqa: E402

R = load_run_py(SCRIPTS.parent, "ce_run_modality_safety")

FIX = Path(__file__).resolve().parent / "fixtures"
PKG = FIX / "evidence_package_new_blocks.json"


def _pkg():
    return json.loads(PKG.read_text())


def _with_safety_hold_and_svbm(pkg, sm_action):
    """Set the safety sub-verdict to a hold-grade WT-loss concern and attach a per-modality safety block
    whose small_molecule channel carries `sm_action` (degrader always holds)."""
    sv = pkg["synthesis"]["sub_verdicts"]
    sv["safety"]["verdict"] = "human_genetics_safety_concern"  # in hc.SAFETY_HOLD
    sv["safety"]["safety_verdict_by_modality"] = {
        "small_molecule": {"action": sm_action, "wt_engagement": "conditional", "driving_rules": []},
        "degrader": {"action": "hold", "wt_engagement": "engages_wt", "driving_rules": ["r"]},
    }
    return pkg


# =============================== Phase 2 — modality×safety in gate_ceiling ==========================


def test_scalar_safety_hold_caps_when_no_modality():
    """Without a --modality, a hold-grade safety verdict caps the ceiling at advanceable_flagged
    (the pre-existing blanket behaviour — the per-modality block cannot refine an unspecified channel)."""
    g = hc.gate_ceiling(_with_safety_hold_and_svbm(_pkg(), "conditional"), modality=None)
    assert g["ceiling"] == "advanceable_flagged"
    assert g["safety_modality_cleared"] is False
    assert g["safety_modality_action"] is None


def test_conditional_channel_clears_the_safety_hold_cap():
    """A modality whose per-channel action is `conditional` (allele-selective escape — the spine's sole
    safe action) clears the blanket hold cap; the ceiling is no longer capped by the scalar safety hold."""
    g = hc.gate_ceiling(_with_safety_hold_and_svbm(_pkg(), "conditional"), modality="small_molecule")
    assert g["safety_modality_action"] == "conditional"
    assert g["safety_modality_cleared"] is True
    # with the clean fixture hard_gates (safety rows latent), clearing the scalar hold restores advanceable
    assert g["ceiling"] == "advanceable"


def test_hold_channel_keeps_the_safety_cap():
    """A modality whose per-channel action is `hold` (engages WT) does NOT clear the cap — a degrader run
    keeps the hold. Fail-closed: only `conditional` clears (mirrors tp_gates._SAFETY_SAFE_ACTIONS)."""
    g = hc.gate_ceiling(_with_safety_hold_and_svbm(_pkg(), "conditional"), modality="degrader")
    # degrader's own action is hold → the (small_molecule=conditional) escape does not apply
    assert g["safety_modality_action"] == "hold"
    assert g["safety_modality_cleared"] is False
    assert g["ceiling"] == "advanceable_flagged"


def test_missing_svbm_block_is_fail_closed():
    """An older package with no safety_verdict_by_modality block: the scalar hold cap still applies
    (never silently cleared)."""
    pkg = _pkg()
    pkg["synthesis"]["sub_verdicts"]["safety"]["verdict"] = "human_genetics_safety_concern"
    g = hc.gate_ceiling(pkg, modality="small_molecule")
    assert g["safety_modality_action"] is None and g["safety_modality_cleared"] is False
    assert g["ceiling"] == "advanceable_flagged"


# =============================== Phase 3 — per-axis certainty ======================================


def test_parse_certainty_by_axis_normalizes_medium_to_moderate():
    pkg = _pkg()
    pkg["synthesis"]["decision_facets"] = {
        "certainty_by_axis": {
            "dependency": {"certainty": {"level": "high"}},
            "selectivity": {"certainty": {"level": "medium"}},
            "genomic_alteration": {"certainty": {"level": "low"}},
            "malformed": {"certainty": "not-a-dict"},
        }
    }
    cba = hc.parse_certainty_by_axis(pkg)
    assert cba == {"dependency": "high", "selectivity": "moderate", "genomic_alteration": "low"}


def test_parse_certainty_by_axis_absent_is_empty():
    assert hc.parse_certainty_by_axis(_pkg()) == {}  # fixture has no decision_facets → {}


def test_weakest_link_prefers_sidecar_and_falls_back():
    conviction = {"dependency": "selective_dependency", "selectivity": "tumor_selective", "mechanism": "some_call"}
    in_scope = ["dependency", "selectivity", "mechanism"]
    # dependency+selectivity opt in (high); mechanism has no sidecar → binary proxy = moderate → limits
    cba = {"dependency": "high", "selectivity": "high"}
    worst, limiting = hc.weakest_link_certainty(conviction, in_scope, cba)
    assert worst == "moderate" and limiting == "mechanism"
    # all in-scope axes high via sidecar → weakest-link CAN now reach high (old proxy never did)
    cba_all = {"dependency": "high", "selectivity": "high", "mechanism": "high"}
    worst2, _ = hc.weakest_link_certainty(conviction, in_scope, cba_all)
    assert worst2 == "high"


def test_weakest_link_gap_axis_still_low():
    conviction = {"dependency": "selective_dependency", "selectivity": "insufficient"}
    worst, limiting = hc.weakest_link_certainty(conviction, ["dependency", "selectivity"], {"dependency": "high"})
    assert worst == "low" and limiting == "selectivity"  # gap axis (absence-discipline) dominates


# =============================== run()-level surfacing =============================================


def _stub(system, user, name, schema, **kw):
    if name == "cross_edges":
        return {"edges": [], "principal_tensions": [], "evidence_paths": []}
    return {
        "causal_rationale": {"statement": "x", "citations": ["dependency"]},
        "therapeutic_hypothesis": {"statement": "x", "modality": "small_molecule", "citations": ["dependency"]},
        "population": {"statement": "x", "citations": ["dependency"]},
        "therapeutic_window": {"statement": "x", "citations": ["safety"]},
        "evidence_grade": {"overall": "moderate", "per_line": []},
        "proposed_verdict": "advanceable",
        "proposed_verdict_reason": "x",
        "go_forth": {"next_evidence": "y"},
    }


def test_run_surfaces_composed_modality_mismatch(tmp_path):
    pkg = _pkg()
    pkg["synthesis"]["decision_facets"] = {"composed_modality": "adc"}  # composed under ADC
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(pkg))
    r = R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_stub)
    assert r["degraded_mode"]["composed_modality"] == "adc"
    assert r["degraded_mode"]["modality_mismatch"] is True
    assert any(t.get("source") == "integrator_modality_mismatch" for t in r["hypothesis"]["tensions"]), (
        "expected a modality-mismatch tension"
    )


def test_run_matching_modality_has_no_mismatch(tmp_path):
    pkg = _pkg()
    pkg["synthesis"]["decision_facets"] = {"composed_modality": "small_molecule"}
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(pkg))
    r = R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_stub)
    assert r["degraded_mode"]["modality_mismatch"] is False
    assert not any(t.get("source") == "integrator_modality_mismatch" for t in r["hypothesis"]["tensions"])


def test_run_confidence_tier_divergence_recorded(tmp_path):
    """When the spine's confidence_tier diverges from the integrator's discounted certainty, the
    divergence is recorded in cap_reasons (informational; never overrides the spine)."""
    pkg = _pkg()
    pkg["synthesis"]["confidence_tier"] = {"tier": "high"}  # spine says high
    p = tmp_path / "ep.json"
    p.write_text(json.dumps(pkg))
    # no dossier/risk → degraded inputs cap the integrator's certainty at low → diverges from 'high'
    r = R.run(str(p), None, "small-molecule drug target", "small_molecule", None, synthesize_fn=_stub)
    assert r["uncertainty"]["overall_certainty"] != "high"
    assert any("diverges from spine confidence_tier 'high'" in reason for reason in r["uncertainty"]["cap_reasons"])
