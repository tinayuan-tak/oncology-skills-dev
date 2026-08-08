"""Two-slot LLM synthesis: byte-stability of the deterministic spine + prompt grounding.

The load-bearing guarantee: running WITH --synthesize produces a decision that is
IDENTICAL to the no-flag decision except for the added `llm_synthesis` sibling key.
The narration can never touch the verdict spine. Bedrock is fully mocked (no network).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import synthesis as SYN  # noqa: E402


# ---------------------------------------------------------------------------
# 1. build_user_prompt grounds the narration in the contextualized fields
# ---------------------------------------------------------------------------
def _decision_fixture():
    return {
        "skill": "tumor-presence", "target": "CEACAM5", "indication": "COADREAD",
        "headline": {"presence_verdict": "broadly_high_expression",
                     "driving_rule_id": "expression-broadly-high-supportive",
                     "purity_confound_class": "tumor_intrinsic"},
        "cards": [
            {"card_id": "tumor-rna-distribution", "summary": {
                "tumor_expression_class": "broadly_high", "median_log2tpm": 10.99,
                "allgene_percentile": 99.9, "allgene_percentile_class": "top_1pct",
                "allgene_percentile_context": "tcga_tumor:COAD,READ (allgene-tumor-rank-v1)",
                "control_position_class": "above_all_positives",
                "control_position": "above 4/4 positive control(s); above 4/5 negative control(s)",
                "control_positives": {"CEACAM5": 99.9, "EPCAM": 99.7},
                "control_negatives": {"ACTB": 99.9, "SFTPC": 18.0},
                "control_negatives_excluded_lineage_conflict": []}},
            {"card_id": "tumor-rna-distribution-by-subtype", "summary": {
                "subtype_axis_available": True,
                "subtype_effect_size_class": "moderate", "subtype_variance_explained": 0.097,
                "which_subtypes_separate": {"highest": "stage_I", "lowest": "MSI_H"},
                "n_subtypes_measured": 4,
                "per_subtype": {"MSI_H": "18.0 (log2tpm 8.1)", "MSS": "22.0 (log2tpm 9.4)"},
                "subtype_stratification_class": "pan_subtype_uniform"}},
            # a verdict-bearing DEG card + protein card that the OLD prompt dropped entirely.
            # Field names MIRROR the real card schemas (verified against live decision.json) so this
            # fixture cannot silently agree with a reader that reads the wrong keys.
            {"card_id": "tumor-rna-vs-adjacent", "summary": {
                "expression_call_class": "strongly_upregulated", "log2_fc": 3.1,
                "q_value": 1e-12, "is_upregulated_provider_call": True}},
            {"card_id": "tumor-elevation-breadth", "summary": {
                "tumor_elevation_breadth_class": "broad", "n_cohorts_elevated": 7,
                "n_cohorts_tested": 12, "most_elevated_cohorts": ["COAD", "STAD"]}},
        ],
        "fired_rules": [],
    }


def test_prompt_grounds_all_three_axes():
    p = SYN.build_user_prompt(_decision_fixture())
    # verdict + all three contextualized axes must be present in the prompt
    assert "broadly_high_expression" in p
    assert "99.9" in p and "top_1pct" in p                 # axis 1
    assert "above_all_positives" in p                       # axis 2
    assert "moderate" in p and "MSI_H" in p                 # axis 3 (subtype axis available)
    # the system prompt forbids inventing/changing the verdict
    assert "never" in SYN._SYSTEM.lower() and "narrate" in SYN._SYSTEM.lower()


def test_prompt_forwards_the_full_gathered_evidence():
    """Regression for the '2 of 10 cards' drop: the verdict-bearing DEG card + the pan-cancer
    breadth frame must reach the prompt (they were previously never referenced)."""
    p = SYN.build_user_prompt(_decision_fixture())
    # DEG card forwarded with its ACTUAL fields (real values, not "no listed fields present")
    assert "tumor-rna-vs-adjacent" in p and "strongly_upregulated" in p
    assert "log2_fc=3.1" in p
    assert "PAN-CANCER FRAME" in p and "broad" in p                       # true pan-cancer grain
    assert "n_cohorts_elevated: 7 / 12" in p


def test_real_decision_fixture_surfaces_present_cards_not_data_unavailable():
    """THE anti-regression for the field-name-mismatch bug (2026-08-05): a captured REAL
    decision.json (CEACAM5/COADREAD) — where tumor-rna-vs-adjacent, tumor-protein-abundance-cptac,
    and cellline-protein-abundance are all _missing=False with real data — must have those cards
    surfaced with their measured values, NOT rendered 'no listed fields present' or DATA_UNAVAILABLE.
    The bug was invisible to hand-authored fixtures because they shared the reader's wrong field
    names; only a real card payload catches it."""
    import json
    fx = Path(__file__).resolve().parent / "fixtures" / "real_decision_ceacam5_coadread.json"
    decision = json.loads(fx.read_text())
    p = SYN.build_user_prompt(decision)
    # locate each present data card by id in the INDICATION-ANCHOR block and assert it has a value
    present = {c["card_id"] for c in decision["cards"] if not c.get("_missing")}
    for cid in ("tumor-rna-vs-adjacent", "tumor-protein-abundance-cptac", "cellline-protein-abundance"):
        assert cid in present, f"fixture precondition: {cid} should be present with data"
        # the line for this card must NOT be the empty/unavailable renderings
        line = next((ln for ln in p.splitlines() if ln.strip().startswith(cid)), "")
        assert line, f"{cid} missing from prompt entirely"
        assert "no listed fields present" not in line, f"{cid} rendered empty despite having data: {line}"
        assert "DATA_UNAVAILABLE" not in line, f"{cid} mislabeled unavailable despite _missing=False: {line}"
        assert "=" in line, f"{cid} surfaced no field=value pairs: {line}"


def test_grain_governance_gates_subtype_axis_when_unavailable():
    """When the subtype axis is not available, the prompt must say so — NOT narrate an effect."""
    d = _decision_fixture()
    for c in d["cards"]:
        if c["card_id"] == "tumor-rna-distribution-by-subtype":
            c["summary"] = {"subtype_axis_available": False}
    p = SYN.build_user_prompt(d)
    assert "subtype axis NOT available" in p
    assert "moderate" not in p.split("AXIS 3")[1]   # no effect narrated after the axis header


def test_queried_subtype_foregrounded_only_when_in_strata():
    # in per_subtype value map → foregrounded with its position
    p_hit = SYN.build_user_prompt(_decision_fixture(), subtype_query="MSI_H")
    assert "QUERIED SUBTYPE MSI_H" in p_hit and "foreground this stratum" in p_hit
    # named in the omnibus extremes only (no per-stratum value) → narrate role, don't fabricate
    d = _decision_fixture()
    for c in d["cards"]:
        if c["card_id"] == "tumor-rna-distribution-by-subtype":
            c["summary"].pop("per_subtype", None)   # only which_subtypes_separate remains
    p_named = SYN.build_user_prompt(d, subtype_query="stage_I")
    assert "appears in the omnibus extremes" in p_named
    # not in any stratum → honest "not among the computed strata", no invented position
    p_miss = SYN.build_user_prompt(_decision_fixture(), subtype_query="POLE_ULTRA")
    assert "QUERIED SUBTYPE POLE_ULTRA: NOT among the computed strata" in p_miss


def test_data_unavailable_card_forwarded_not_flattened():
    """A measured-but-unavailable card must be rendered as DATA_UNAVAILABLE, distinct from
    a never-wired card — the null result reaches the LLM."""
    d = _decision_fixture()
    d["cards"].append({"card_id": "tumor-protein-abundance-cptac", "summary": {},
                       "_missing": True, "_missing_reason": "no_cptac_cohort_for_indication"})
    p = SYN.build_user_prompt(d)
    assert "tumor-protein-abundance-cptac: DATA_UNAVAILABLE" in p


def test_prompt_handles_missing_axes_gracefully():
    d = {"target": "X", "indication": "BRCA", "headline": {"presence_verdict": "insufficient"},
         "cards": []}
    p = SYN.build_user_prompt(d)  # must not raise on absent cards
    assert "insufficient" in p and "n/a" in p


# ---------------------------------------------------------------------------
# 2. Tool schema is well-formed + verdict-neutral (no field that could restate a verdict)
# ---------------------------------------------------------------------------
def test_tool_schema_is_relevance_read_never_a_verdict():
    props = SYN.SYNTHESIS_TOOL_SCHEMA["properties"]
    # the headline is a single-lens RELEVANCE read (not a presence verdict restatement)
    assert "expression_relevance_for_target" in props
    assert props["expression_relevance_for_target"]["enum"] == [
        "strongly_supports", "supports_with_caveats", "neutral_uninformative", "argues_against"]
    # confidence remains a separate CONFIDENCE qualifier
    assert props["confidence_qualifier"]["enum"] == [
        "well_supported", "supported_with_caveats", "weakly_supported", "insufficient_evidence"]
    # the LLM cannot emit or restate the deterministic verdict
    assert "presence_verdict" not in props
    assert SYN.SYNTHESIS_TOOL_SCHEMA["additionalProperties"] is False


def test_schema_and_system_are_modality_free():
    """The single-lens presence synthesis must NOT solicit or discuss therapeutic modality —
    that reasoning belongs to the cross-lens target-profile synthesis."""
    import json
    schema_txt = json.dumps(SYN.SYNTHESIS_TOOL_SCHEMA).lower()
    for tok in ["adc", "t-cell-engager", "tce", "bite", "car ", "small_molecule", "degrader", "antibody"]:
        assert tok not in schema_txt, f"schema should not mention modality token {tok!r}"
    # the system prompt explicitly scopes modality OUT
    assert "do not discuss therapeutic modality" in SYN._SYSTEM.lower()
    assert "relevan" in SYN._SYSTEM.lower()   # relevance is the stated purpose


# ---------------------------------------------------------------------------
# 3. synthesize_presence stamps provenance (mocked Bedrock)
# ---------------------------------------------------------------------------
def test_synthesize_presence_returns_stamped_block():
    fake = {"headline_narrative": {"value": "CEACAM5 is broadly high...",
                                   "_source": "llm_synthesized", "_model_id": "opus",
                                   "_prompt_hash": "abc"},
            "confidence_qualifier": "well_supported"}
    with patch("_skills_common.llm.synthesize_structured", return_value=fake) as m:
        out = SYN.synthesize_presence(_decision_fixture())
    assert m.called
    assert out["headline_narrative"]["_source"] == "llm_synthesized"


# ---------------------------------------------------------------------------
# 4. TWO-SLOT byte-stability: --synthesize adds ONLY llm_synthesis (dispatcher e2e, mocked)
# ---------------------------------------------------------------------------
def _run(tmp_path, synthesize: bool, synth_return=None, synth_raises=False):
    """Run run_wired_skill with resolve_cards + synthesize_structured mocked, return the
    decision.json dict written to disk."""
    import json
    from _skills_common import dispatcher as D

    card_outputs = [
        {"card_id": "tumor-rna-distribution", "summary": {
            "tumor_expression_class": "broadly_high", "allgene_percentile": 99.9,
            "allgene_percentile_class": "top_1pct", "control_position_class": "above_all_positives"},
         "_missing": False},
    ]

    def _headline(cards, fired, vp):
        return {"presence_verdict": "broadly_high_expression", "driving_rule_id": None}

    # tumor-presence is a VERDICT-bearing skill (it passes a verdict_fn); model that so the presence
    # fallback path is exercised (not the 2026-08-08 descriptive-skill synthesis-skip guard, which is
    # only for verdict_fn=None skills like target-intrinsic).
    def _verdict(fired):
        return ("broadly_high_expression", None)

    argv = ["--target", "CEACAM5", "--indication", "COADREAD", "--out", str(tmp_path)]
    if synthesize:
        argv.append("--synthesize")

    patches = [
        patch.object(D, "resolve_cards", return_value=card_outputs),
        patch.object(D, "fired_rules", return_value=[]),
    ]
    # patch synthesize_structured at its SOURCE (_skills_common.llm) — synthesis.py imports
    # it lazily inside synthesize_presence, so it is not an attribute of the synthesis module.
    if synth_raises:
        patches.append(patch("_skills_common.llm.synthesize_structured",
                             side_effect=RuntimeError("bedrock down")))
    else:
        patches.append(patch("_skills_common.llm.synthesize_structured",
                             return_value=(synth_return or {"headline_narrative": {
                                 "value": "narr", "_source": "llm_synthesized",
                                 "_model_id": "m", "_prompt_hash": "h"}})))
    for p in patches:
        p.start()
    try:
        D.run_wired_skill(skill_name="tumor-presence", skill_version="9.9.9",
                          cards=["tumor-rna-distribution"], axis="intracellular_intrinsic",
                          question="Is {target} present in {indication}?",
                          verdict_fn=_verdict, headline_fn=_headline, argv=argv)
    finally:
        for p in patches:
            p.stop()
    return json.loads((tmp_path / "decision.json").read_text())


def test_synthesize_adds_only_llm_synthesis_key(tmp_path):
    base = _run(tmp_path / "a", synthesize=False)
    synth = _run(tmp_path / "b", synthesize=True)
    # the deterministic spine (everything except llm_synthesis + volatile fields) is identical.
    # run_health is VOLATILE (per-run timings + monotonic clock) — excluded from the spine
    # comparison exactly like generated_at. It is added by the dispatcher unconditionally, NOT
    # by synthesis, so it must be present in BOTH runs.
    for d in (base, synth):
        d.pop("generated_at", None)
        d.pop("run_health", None)
    assert "run_health" not in base and "run_health" not in synth  # popped from both
    assert "llm_synthesis" not in base
    assert "llm_synthesis" in synth
    synth_wo = {k: v for k, v in synth.items() if k != "llm_synthesis"}
    assert synth_wo == base, "synthesis must NOT change any deterministic field"
    assert synth["headline"]["presence_verdict"] == base["headline"]["presence_verdict"]


def test_dispatcher_emits_run_health(tmp_path):
    """Every wired subskill writes a per-run run_health block (observability; sibling key,
    never touches the spine). Guards the read/compute timing + liveness record."""
    d = _run(tmp_path / "rh", synthesize=False)
    assert "run_health" in d, "dispatcher must emit run_health into decision.json"
    rh = d["run_health"]
    # shape + liveness
    assert rh["skill_name"] and rh["skill_version"]
    assert rh["status"] == "ok"                      # the 1 mocked card resolves, none missing/skipped
    assert rh["n_cards_resolved"] == 1
    assert rh["cards_missing"] == [] and rh["cards_skipped_a4"] == []
    # timings are present, non-negative, and total ≥ read (monotonic clock)
    for k in ("read_secs", "compute_secs", "total_secs"):
        assert isinstance(rh[k], (int, float)) and rh[k] >= 0, f"{k} bad"
    assert rh["total_secs"] >= rh["read_secs"]


def test_run_health_status_degraded_on_missing_card(tmp_path):
    """A consumed card that resolves _missing → status 'degraded' (run completed, but not
    all evidence was available). Distinguishes an honest partial run from a clean one."""
    from _skills_common import dispatcher as D
    import json
    card_outputs = [
        {"card_id": "present-card", "summary": {}, "_missing": False},
        {"card_id": "absent-card", "summary": {}, "_missing": True},
    ]
    argv = ["--target", "KRAS", "--indication", "COADREAD", "--out", str(tmp_path / "deg")]
    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(skill_name="t", skill_version="9.9.9", cards=["present-card", "absent-card"],
                          axis="intracellular_intrinsic", question="q {target} {indication}",
                          headline_fn=lambda c, f, v: {"verdict": "x"}, argv=argv)
    rh = json.loads((tmp_path / "deg" / "decision.json").read_text())["run_health"]
    assert rh["status"] == "degraded"
    assert rh["cards_missing"] == ["absent-card"]
    assert rh["n_cards_resolved"] == 1


def test_synthesis_failure_degrades_to_note(tmp_path):
    d = _run(tmp_path / "c", synthesize=True, synth_raises=True)
    assert "_synthesis_error" in d["llm_synthesis"]
    # the verdict spine is untouched despite the synthesis failure
    assert d["headline"]["presence_verdict"] == "broadly_high_expression"


# ---------------------------------------------------------------------------
# 5. LIVE Bedrock smoke (opt-in only — skipped in CI / offline). Set RUN_LIVE_BEDROCK=1
#    with an invoke-entitled profile (BEDROCK_AWS_PROFILE=cmp-dev, AWS_REGION=us-east-1)
#    to exercise the real synthesize_structured path end-to-end.
# ---------------------------------------------------------------------------
@pytest.mark.skipif(os.environ.get("RUN_LIVE_BEDROCK") != "1",
                    reason="live Bedrock opt-in; set RUN_LIVE_BEDROCK=1 with an entitled profile")
def test_live_relevance_read_is_scoped_and_categorical():
    block = SYN.synthesize_presence(_decision_fixture())
    # returns the reshaped relevance schema, provenance-stamped
    rel = block["expression_relevance_for_target"]
    val = rel["value"] if isinstance(rel, dict) else rel
    assert val in ("strongly_supports", "supports_with_caveats",
                   "neutral_uninformative", "argues_against")
    # narration must not have drifted into modality talk (single-lens scope)
    joined = " ".join(v.get("value", "") if isinstance(v, dict) else str(v)
                      for v in block.values()).lower()
    for tok in [" adc", "t-cell engager", "t-cell-engager", "small molecule", "degrader"]:
        assert tok not in joined, f"live narration leaked modality token {tok!r}"
