"""Dispatcher synthesize_fn routing + backward-compat.

The bug this fixes: run_wired_skill used to HARDCODE `from .synthesis import synthesize_presence`,
so a --synthesize tumor-selectivity run was narrated by the PRESENCE narrator (wrong lens). The
dispatcher now takes an optional synthesize_fn; when omitted it falls back to synthesize_presence
(so tumor-presence is unchanged). These tests pin BOTH paths + the two-slot byte-stability.
Bedrock fully mocked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import dispatcher as D  # noqa: E402


def _run(tmp_path, *, synthesize, synthesize_fn=None, verdict_fn="default"):
    card_outputs = [
        {"card_id": "tumor-vs-normal-selectivity", "summary": {
            "selectivity_class": "strong_tumor_selective"}, "_missing": False},
    ]

    def _headline(cards, fired, vp):
        return {"selectivity_class": "strong_tumor_selective", "driving_rule_id": None}

    # A VERDICT-bearing skill supplies a verdict_fn (tumor-presence/-selectivity do). The presence
    # fallback + custom-narrator paths are only reachable for verdict-bearing skills; pass a default
    # verdict_fn so the harness models that. `verdict_fn=None` explicitly models a DESCRIPTIVE skill
    # (target-intrinsic) — where --synthesize must SKIP, not mis-lens (2026-08-08 synthesis review).
    _vf = (lambda fired: ("strong_tumor_selective", None)) if verdict_fn == "default" else verdict_fn

    argv = ["--target", "MSLN", "--indication", "PAAD", "--out", str(tmp_path)]
    if synthesize:
        argv.append("--synthesize")

    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(
            skill_name="tumor-selectivity", skill_version="9.9.9",
            cards=["tumor-vs-normal-selectivity"], axis="intracellular_intrinsic",
            question="How selective is {target} in {indication}?",
            headline_fn=_headline, verdict_fn=_vf, synthesize_fn=synthesize_fn, argv=argv)
    return json.loads((tmp_path / "decision.json").read_text())


def test_synthesize_fn_is_invoked_not_presence(tmp_path):
    """When a skill passes synthesize_fn, THAT narrator runs — not the presence fallback."""
    calls = {"n": 0}

    def _fake_selectivity(decision, model_id=None, subtype_query=None):
        calls["n"] += 1
        return {"selectivity_relevance_for_target": {
            "value": "strongly_supports", "_source": "llm_synthesized",
            "_model_id": "m", "_prompt_hash": "h"}}

    # If the dispatcher wrongly fell back to presence, this patch would make it explode.
    with patch("_skills_common.synthesis.synthesize_presence",
               side_effect=AssertionError("presence narrator must NOT be used when synthesize_fn is set")):
        d = _run(tmp_path / "sel", synthesize=True, synthesize_fn=_fake_selectivity)
    assert calls["n"] == 1
    assert "selectivity_relevance_for_target" in d["llm_synthesis"]


def test_no_synthesize_fn_falls_back_to_presence(tmp_path):
    """Backward-compat: a VERDICT-bearing skill that passes no synthesize_fn (tumor-presence today)
    still narrates via the presence fallback."""
    with patch("_skills_common.synthesis.synthesize_presence",
               return_value={"expression_relevance_for_target": {
                   "value": "supports_with_caveats", "_source": "llm_synthesized"}}) as m:
        d = _run(tmp_path / "pres", synthesize=True, synthesize_fn=None)  # verdict_fn defaults present
    assert m.called
    assert "expression_relevance_for_target" in d["llm_synthesis"]


def test_descriptive_skill_skips_synthesis_not_mislens(tmp_path):
    """2026-08-08 synthesis-review F2: a DESCRIPTIVE skill (verdict_fn=None AND no synthesize_fn —
    e.g. target-intrinsic) must NOT fall back to the presence narrator (wrong lens → garbage on an
    indication-independent dossier). --synthesize is a no-op skip with an honest note; the presence
    narrator must never be invoked."""
    with patch("_skills_common.synthesis.synthesize_presence",
               side_effect=AssertionError("presence narrator must NOT run for a descriptive skill")):
        d = _run(tmp_path / "desc", synthesize=True, synthesize_fn=None, verdict_fn=None)
    s = d["llm_synthesis"]
    assert s.get("_synthesis_skipped") == "descriptive_skill_no_narrator"
    # no mis-lensed presence fields leaked in
    assert "expression_relevance_for_target" not in s
    assert "selectivity_relevance_for_target" not in s


def test_descriptive_skill_without_synthesize_flag_is_clean(tmp_path):
    """A descriptive skill WITHOUT --synthesize emits no llm_synthesis key at all (unchanged)."""
    d = _run(tmp_path / "desc2", synthesize=False, synthesize_fn=None, verdict_fn=None)
    assert "llm_synthesis" not in d


def test_two_slot_byte_stability_with_custom_synthesizer(tmp_path):
    """--synthesize with a custom synthesize_fn adds ONLY llm_synthesis; the spine is identical."""
    def _fake(decision, model_id=None, subtype_query=None):
        return {"selectivity_relevance_for_target": {"value": "strongly_supports",
                "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}}

    base = _run(tmp_path / "a", synthesize=False)
    synth = _run(tmp_path / "b", synthesize=True, synthesize_fn=_fake)
    base.pop("generated_at", None); synth.pop("generated_at", None)
    assert "llm_synthesis" not in base
    assert "llm_synthesis" in synth
    assert {k: v for k, v in synth.items() if k != "llm_synthesis"} == base


def test_synthesize_fn_failure_degrades_to_note(tmp_path):
    def _boom(decision, model_id=None, subtype_query=None):
        raise RuntimeError("bedrock down")
    d = _run(tmp_path / "c", synthesize=True, synthesize_fn=_boom)
    assert "_synthesis_error" in d["llm_synthesis"]
    assert d["headline"]["selectivity_class"] == "strong_tumor_selective"


# --- subtype panorama hook (2026-08-06): --subtypes-gated, verdict-inert ---

def _run_sub(tmp_path, *, subtypes=None, panorama_fn=None):
    card_outputs = [{"card_id": "pan-cancer-crispr-dependency-distribution",
                     "summary": {"dependency_class": "strongly_selective"}, "_missing": False}]

    def _headline(cards, fired, vp):
        return {"dependency_verdict": "lineage_selective", "driving_rule_id": "r"}

    argv = ["--target", "KRAS", "--indication", "COADREAD", "--out", str(tmp_path)]
    if subtypes:
        argv += ["--subtypes", subtypes]
    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(
            skill_name="functional-requirement", skill_version="9.9.9",
            cards=["pan-cancer-crispr-dependency-distribution"], axis="intracellular_intrinsic",
            question="Is {target} a dependency in {indication}?",
            headline_fn=_headline, subtype_panorama_fn=panorama_fn, argv=argv)
    return json.loads((tmp_path / "decision.json").read_text())


def test_subtypes_noop_when_no_panorama_fn(tmp_path):
    """--subtypes with NO panorama_fn (every existing caller) is a complete no-op: no subtype keys."""
    d = _run_sub(tmp_path / "a", subtypes="MSI_H,MSS", panorama_fn=None)
    assert "subtype_scope" not in d["headline"]
    assert "subtype_dependency_panorama" not in d["headline"]


def test_panorama_fn_not_invoked_without_subtypes_flag(tmp_path):
    """A skill can supply a panorama_fn, but it must NOT fire unless --subtypes is passed."""
    calls = {"n": 0}

    def _pano(target, indication, strata):
        calls["n"] += 1
        return {"cards": [], "scope_subtypes": strata, "subtype_dependency_panorama": {}}

    d = _run_sub(tmp_path / "b", subtypes=None, panorama_fn=_pano)
    assert calls["n"] == 0
    assert "subtype_scope" not in d["headline"]


def test_panorama_appended_and_verdict_byte_stable(tmp_path):
    """--subtypes + panorama_fn: the panorama block merges into the headline + its cards append to
    the package, but the verdict spine is byte-identical to the no-subtypes run."""
    def _pano(target, indication, strata):
        return {"cards": [{"card_id": "subgroup-stratified-dependency",
                           "summary": {"per_subgroup_metrics": []}, "_missing": False}],
                "scope_subtypes": strata,
                "subtype_dependency_panorama": {"subtype_dependency_pattern": "uniform_across_subgroups"}}

    base = _run_sub(tmp_path / "base", subtypes=None, panorama_fn=_pano)
    sub = _run_sub(tmp_path / "sub", subtypes="MSI_H,MSS", panorama_fn=_pano)
    # panorama present only in the --subtypes run
    assert "subtype_dependency_panorama" not in base["headline"]
    assert sub["headline"]["subtype_scope"] == ["MSI_H", "MSS"]
    assert sub["headline"]["subtype_dependency_panorama"]["subtype_dependency_pattern"] == "uniform_across_subgroups"
    # verdict spine identical
    assert base["headline"]["dependency_verdict"] == sub["headline"]["dependency_verdict"]
    assert base["headline"]["driving_rule_id"] == sub["headline"]["driving_rule_id"]


def test_panorama_fn_failure_degrades_not_breaks(tmp_path):
    """A panorama-resolution failure must NOT break the deterministic run (degrades to an error note)."""
    def _boom(target, indication, strata):
        raise RuntimeError("shard unreachable")
    d = _run_sub(tmp_path / "c", subtypes="MSI_H,MSS", panorama_fn=_boom)
    assert d["headline"]["dependency_verdict"] == "lineage_selective"   # spine intact
    assert "_subtype_panorama_error" in d["headline"]
