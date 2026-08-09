"""synthesis_surface_modality — the opt-in surface-modality (biologics) lens narrator (prompt build +
tool schema + two-slot dispatch). Bedrock fully mocked (no network).

Pins: (1) the tool schema is CONFIDENCE-only (no fit_class / surface_modality_verdict field the LLM
could emit); (2) build_user_prompt reads the FULL surface evidence set and renders a measured-but-
unavailable card as DATA_UNAVAILABLE (the H1 drops-nulls guard); (3) the accessibility-first + ADC-vs-TCE
discrimination steer is present; (4) two-slot byte-stability through the dispatcher with
synthesize_surface_modality; (5) failure degrades to a note; (6) the publication register + deterministic
metric legend.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import synthesis_surface_modality as SM  # noqa: E402
from _skills_common import dispatcher as D  # noqa: E402


def _decision(shed_missing: bool = True):
    """A realistic surface-modality-fit decision spine (mirrors run.py::_headline + card summaries)."""
    return {
        "target": "ERBB2", "indication": "BRCA",
        "headline": {
            "surface_modality_verdict": "adc_preferred",
            "driving_rule_id": "adc-preferred-supportive",
            "fit_class": "adc_preferred",
            "topology_class": "single_pass_large_ecd",
            "family_class": "receptor_tyrosine_kinase",
            "hotspot_pocket_adjacency_call": "n/a",
            "surface_confirmation_class": "protein_confirmed",
            "surface_confirmation_n_celllines": 34,
            "surface_density_class": "high_density_grade_b",
            "normal_tissue_breadth_class": "restricted",
            "essential_tissue_flag": False,
            "normal_tissue_safety_flags": [],
            "shed_liability_class": "low_shed",
            "shed_serum_marker": None,
            "tce_homogeneity_class": "homogeneous",
            "malignant_detection_fraction": 0.91,
            "window_class": "wide_window",
            "window_ratio_full_normal": 8.2,
            "window_ratio_essential": 21.0,
            "window_max_essential_organ": "heart",
        },
        "cards": [
            {"card_id": "adc-tce-modality-fit", "_missing": False, "summary": {}},
            {"card_id": "surface-topology-and-ptm", "_missing": False, "summary": {}},
            {"card_id": "surfaceome-family-classification", "_missing": False, "summary": {}},
            {"card_id": "protein-surface-evidence", "_missing": False, "summary": {}},
            {"card_id": "surface-abundance-density", "_missing": False, "summary": {}},
            {"card_id": "normal-tissue-liability", "_missing": False, "summary": {}},
            {"card_id": "shed-ectodomain-liability", "_missing": shed_missing, "summary": {}},
            {"card_id": "tumor-scrna-celltype-expression", "_missing": False, "summary": {}},
        ],
    }


# ---- schema is confidence-only ----
def test_tool_schema_has_no_verdict_field():
    """The LLM must NOT be able to emit a fit_class / surface_modality_verdict — it narrates a FIXED spine."""
    props = set(SM.SYNTHESIS_TOOL_SCHEMA["properties"])
    assert "fit_class" not in props and "surface_modality_verdict" not in props
    assert props == {"surface_modality_relevance_for_target", "surface_modality_rationale",
                     "adc_vs_tce_read", "confidence_qualifier", "key_caveat"}
    assert SM.SYNTHESIS_TOOL_SCHEMA["additionalProperties"] is False


# ---- prompt reads the full evidence set and never drops a null ----
def test_prompt_grounds_full_evidence():
    p = SM.build_user_prompt(_decision())
    assert "surface_modality_verdict: adc_preferred" in p
    assert "fit_class (composed): adc_preferred" in p
    for token in ("ACCESSIBILITY", "topology_class", "PROTEIN-LEVEL SURFACE CONFIRMATION",
                  "ADC AXIS", "NORMAL-TISSUE LIABILITY", "SHED-ECTODOMAIN LIABILITY",
                  "WITHIN-TUMOUR HOMOGENEITY", "THERAPEUTIC-WINDOW ARC"):
        assert token in p, f"missing evidence block: {token}"


def test_prompt_renders_unavailable_card_as_data_unavailable():
    """The H1 drops-nulls guard: a measured-but-missing card is shown as DATA_UNAVAILABLE."""
    p = SM.build_user_prompt(_decision(shed_missing=True))
    assert "shed-ectodomain-liability: DATA_UNAVAILABLE" in p


def test_prompt_carries_accessibility_and_adc_vs_tce_steer():
    p = SM.build_user_prompt(_decision())
    # accessibility-first steer (2026-08-09: the no-ECD case now argues against a SURFACE-BINDING
    # biologic, not "all biologics" — the peptide-centric pMHC axis can still reach intracellular targets)
    assert "ACCESSIBILITY" in p and "argues AGAINST a surface-binding biologic" in p
    # ADC-vs-TCE discrimination steer + the TCE-killer axes
    assert "DISCRIMINATE ADC vs TCE" in p
    assert "KILLER axis" in p
    # the 6 previously-invisible enrichment cards now reach the prompt (2026-08-09 wiring)
    assert "pmhc_presentation_class" in p and "PEPTIDE-CENTRIC" in p
    assert "cd_antigen_backbone_class" in p
    assert "sc_normal_expression_class" in p
    assert "mutant_stratified_surface_class" in p and "pathway_stratified_surface_class" in p
    assert "exon_window_class" in p


# ---- two-slot byte-stability through the dispatcher ----
def _run_dispatch(tmp_path, *, synthesize):
    card_outputs = [{"card_id": "adc-tce-modality-fit", "summary": {}, "_missing": False}]

    def _headline(cards, fired, vp):
        return {"surface_modality_verdict": "adc_preferred", "fit_class": "adc_preferred",
                "driving_rule_id": "adc-preferred-supportive"}

    argv = ["--target", "ERBB2", "--indication", "BRCA", "--out", str(tmp_path)]
    if synthesize:
        argv.append("--synthesize")

    def _fake(decision, model_id=None, subtype_query=None):
        return {"surface_modality_relevance_for_target": {"value": "strongly_supports",
                "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}}

    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(
            skill_name="surface-modality-fit", skill_version="9.9.9",
            cards=["adc-tce-modality-fit"], axis="surface_intrinsic",
            question="Is {target} biologics-approachable in {indication}?",
            headline_fn=_headline, synthesize_fn=_fake, argv=argv)
    return json.loads((tmp_path / "decision.json").read_text())


def test_two_slot_byte_stability(tmp_path):
    base = _run_dispatch(tmp_path / "a", synthesize=False)
    synth = _run_dispatch(tmp_path / "b", synthesize=True)
    base.pop("generated_at", None); synth.pop("generated_at", None)
    assert "llm_synthesis" not in base
    assert "llm_synthesis" in synth
    assert {k: v for k, v in synth.items() if k != "llm_synthesis"} == base


def test_synthesis_failure_degrades_to_note(tmp_path):
    """A narration failure must never break the deterministic run."""
    card_outputs = [{"card_id": "adc-tce-modality-fit", "summary": {}, "_missing": False}]

    def _headline(cards, fired, vp):
        return {"surface_modality_verdict": "adc_preferred", "fit_class": "adc_preferred",
                "driving_rule_id": "adc-preferred-supportive"}

    def _boom(decision, model_id=None, subtype_query=None):
        raise RuntimeError("bedrock down")

    out = tmp_path / "c"
    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(
            skill_name="surface-modality-fit", skill_version="9.9.9",
            cards=["adc-tce-modality-fit"], axis="surface_intrinsic",
            question="Is {target} biologics-approachable in {indication}?",
            headline_fn=_headline, synthesize_fn=_boom,
            argv=["--target", "ERBB2", "--indication", "BRCA", "--out", str(out), "--synthesize"])
    d = json.loads((out / "decision.json").read_text())
    assert "_synthesis_error" in d["llm_synthesis"]
    assert d["headline"]["fit_class"] == "adc_preferred"


# --- publication-register + deterministic metric legend ---

def test_metric_legend_is_deterministic_and_covers_cited_metrics():
    keys = set(SM.METRIC_LEGEND)
    assert {"fit_class", "topology_class", "surface_density_class", "normal_tissue_breadth_class",
            "shed_liability_class", "tce_homogeneity_class", "surface_confirmation_class"} <= keys
    for k, v in SM.METRIC_LEGEND.items():
        assert isinstance(v, str) and len(v) > 40, f"{k} legend too short"
    # the homogeneity legend must explain the TCE-escape mechanism (readable by a non-specialist)
    assert "escape" in SM.METRIC_LEGEND["tce_homogeneity_class"].lower() or \
           "antigen-negative" in SM.METRIC_LEGEND["tce_homogeneity_class"].lower()


def test_legend_attached_on_success_not_on_failure():
    ok = {"surface_modality_relevance_for_target": {"value": "supports_with_caveats",
          "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}}
    with patch("_skills_common.llm.synthesize_structured", return_value=dict(ok)):
        res = SM.synthesize_surface_modality(_decision())
    assert res["metric_legend"] == SM.METRIC_LEGEND

    degraded = {"_synthesis_error": "RuntimeError: bedrock down", "_note": "..."}
    with patch("_skills_common.llm.synthesize_structured", return_value=dict(degraded)):
        res2 = SM.synthesize_surface_modality(_decision())
    assert "metric_legend" not in res2 and "_synthesis_error" in res2


def test_system_prompt_enforces_publication_register_and_glosses():
    sysp = SM._SYSTEM.lower()
    assert "publication" in sysp
    assert "promotional" in sysp or "editorialis" in sysp
    assert "promising" in sysp
    assert "gloss" in sysp
    desc = SM.SYNTHESIS_TOOL_SCHEMA["properties"]["surface_modality_rationale"]["description"].lower()
    assert "publication register" in desc and "plain language" in desc
