"""narrator_engine — the ONE generic capsule-driven single-lens narrator. Deterministic prompt/schema
assertions, no Bedrock. Two-slot / verdict-inert."""

from __future__ import annotations
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import narrator_engine as NE  # noqa: E402
from _skills_common.narrator_lenses import (  # noqa: E402
    FUNCTIONAL_REQUIREMENT,
    GENOMIC_ALTERATION,
    ON_TARGET_SAFETY,
    SURFACE_MODALITY_FIT,
    TRACTABILITY_SM,
    TUMOR_SELECTIVITY,
)


def _decision():
    return {
        "target": "KRAS",
        "indication": "COADREAD",
        "headline": {
            "verdict": "lineage_selective",
            "driving_rule_id": "lineage-selective-supportive",
            "subgroup_signals": {
                "DEP": {
                    "signal": "strong",
                    "confidence": "high",
                    "n_sources": 6,
                    "n_agree": 5,
                    "power": "high",
                    "conflict": False,
                    "sources": [],
                }
            },
        },
        "cards": [
            {
                "card_id": "pan-cancer-crispr-dependency-distribution",
                "summary": {
                    "dependency_class": "strongly_selective",
                    "median_chronos_panel": -0.457,
                    "selectivity_index": 0.85,
                    "n_cell_lines_evaluated": 1538,
                },
            }
        ],
    }


def test_verdict_tool_uses_lens_relevance_enum():
    name, schema = NE._tool(FUNCTIONAL_REQUIREMENT)
    assert name == "emit_functional_requirement_synthesis"
    assert schema["properties"]["relevance"]["enum"] == list(FUNCTIONAL_REQUIREMENT.relevance_enum)
    assert schema["additionalProperties"] is False
    # safety carries its OWN liability enum (polarity-specific)
    _, s2 = NE._tool(ON_TARGET_SAFETY)
    assert "high_liability" in s2["properties"]["relevance"]["enum"]


def test_descriptive_mode_tool_has_no_relevance_verdict():
    from _skills_common.narrator_engine import LensConfig

    lens = LensConfig(name="combination-and-vulnerability", thesis="t", relevance_prompt="p", mode="descriptive")
    name, schema = NE._tool(lens)
    assert name.endswith("_context")
    assert "relevance" not in schema["properties"] and "context_read" in schema["properties"]


def test_system_prompt_threads_polarity_and_scope():
    s = NE._system(ON_TARGET_SAFETY).lower()
    assert "liability" in s and "reassuring" in s  # polarity note threaded
    assert "do not discuss" in s  # scope exclusions threaded
    assert "never change the deterministic" in s  # verdict-inert guardrail


def test_prompt_carries_signal_lead_and_capsules_and_scope():
    p = NE.build_capsule_prompt(_decision(), FUNCTIONAL_REQUIREMENT)
    assert "SUB-GROUP SIGNALS" in p  # signal layer (contract)
    assert "EVIDENCE CAPSULES" in p and "card floor" in p  # data layer (capsules) + completeness
    assert "selectivity_index=0.85" in p  # a bounded raw anchor reached the prompt
    assert "COLLAPSED VERDICT" in p and "lineage_selective" in p
    assert p.index("SUB-GROUP SIGNALS") < p.index("COLLAPSED VERDICT")  # signals lead, verdict trails


def test_selectivity_collapsed_verdict_is_resolved_class_not_rule_id():
    """The tumor-selectivity lens declares verdict_key='selectivity_class', so the COLLAPSED VERDICT
    prompt line injects the RESOLVED (post-veto) class token — not driving_rule_id (a rule-id string
    like 'tvn-...-veto'), which is what the fallback chain landed on before the fix. Mirrors the
    TUMOR_PRESENCE verdict_key contract."""
    assert TUMOR_SELECTIVITY.verdict_key == "selectivity_class"
    decision = {
        "target": "TACSTD2",
        "indication": "COADREAD",
        "headline": {
            "selectivity_class": "selective_but_broadly_normal",
            "driving_rule_id": "tvn-no-therapeutic-window-veto",
            "claim_vector": {"WIN": {"signal": "strong", "corroboration": "high"}},
        },
    }
    p = NE.build_capsule_prompt(decision, TUMOR_SELECTIVITY)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "selective_but_broadly_normal" in collapsed
    assert "tvn-no-therapeutic-window-veto" not in collapsed


def test_functional_requirement_collapsed_verdict_is_resolved_token_not_rule_id():
    """The functional-requirement lens declares verdict_key='dependency_verdict', so the COLLAPSED
    VERDICT prompt line injects the RESOLVED dependency verdict token — not driving_rule_id (a rule-id
    string like 'pan-essential-killer'), which is what the fallback chain landed on before the fix (the
    FR headline key is dependency_verdict, never 'verdict'). Mirrors the presence/selectivity contract.
    The pan_essential case matters most: leaking the rule-id would rob the narrator of the resolved
    'this is a liability' token."""
    assert FUNCTIONAL_REQUIREMENT.verdict_key == "dependency_verdict"
    decision = {
        "target": "PLK1",
        "indication": "COADREAD",
        "headline": {
            "dependency_verdict": "pan_essential_killer",
            "driving_rule_id": "pan-essential-killer",
            "claim_vector": {"DEP": {"signal": "strong", "corroboration": "high"}},
        },
    }
    p = NE.build_capsule_prompt(decision, FUNCTIONAL_REQUIREMENT)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "pan_essential_killer" in collapsed
    # the bare rule-id must not be what the model is handed as the one-word verdict
    assert collapsed.count("pan-essential-killer") == 0


def test_on_target_safety_collapsed_verdict_is_resolved_token_not_rule_id():
    """The on-target-safety lens declares verdict_key='safety_verdict', so the COLLAPSED VERDICT prompt
    line injects the RESOLVED safety verdict token — not driving_rule_id (a rule-id string like
    'highly-constrained-safety-warning'), which is what the fallback chain landed on before the fix (the
    safety headline key is safety_verdict, never 'verdict'). Mirrors the presence/selectivity/FR contract;
    safety was left behind when those three were fixed."""
    assert ON_TARGET_SAFETY.verdict_key == "safety_verdict"
    decision = {
        "target": "KRAS",
        "indication": "COADREAD",
        "headline": {
            "safety_verdict": "highly_constrained_safety_concern",
            "driving_rule_id": "highly-constrained-safety-warning",
            "claim_vector": {"CONSTRAINT": {"signal": "strong", "corroboration": "high"}},
        },
    }
    p = NE.build_capsule_prompt(decision, ON_TARGET_SAFETY)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "highly_constrained_safety_concern" in collapsed
    # the bare rule-id must not be what the model is handed as the one-word verdict
    assert "highly-constrained-safety-warning" not in collapsed


def test_surface_modality_collapsed_verdict_is_resolved_token_not_rule_id():
    """The surface-modality-fit lens declares verdict_key='surface_modality_verdict', so the COLLAPSED
    VERDICT prompt line injects the RESOLVED surface-modality verdict token — not driving_rule_id (a
    rule-id string like 'pmhc-iedb-tcell-validated-tce-supportive'). Before the fix the fallback chain
    MISSED the real key (the <name>_verdict guess is 'surface_modality_fit_verdict' — note the extra
    'fit' — while the headline key is 'surface_modality_verdict') and landed on driving_rule_id. The
    pmhc_tce_supported case matters most: leaking the rule-id let the narrator narrate a NEGATIVE
    (surface fit_class=neither_viable) against a POSITIVE resolved verdict. Mirrors the
    presence/selectivity/FR/safety contract; surface-modality-fit was left behind."""
    assert SURFACE_MODALITY_FIT.verdict_key == "surface_modality_verdict"
    decision = {
        "target": "KRAS",
        "indication": "COADREAD",
        "headline": {
            "surface_modality_verdict": "pmhc_tce_supported",
            "driving_rule_id": "pmhc-iedb-tcell-validated-tce-supportive",
            "fit_class": "neither_viable",
            "claim_vector": {"FIT": {"signal": "strong", "corroboration": "high"}},
        },
    }
    p = NE.build_capsule_prompt(decision, SURFACE_MODALITY_FIT)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "pmhc_tce_supported" in collapsed
    # the bare rule-id must not be what the model is handed as the one-word verdict
    assert "pmhc-iedb-tcell-validated-tce-supportive" not in collapsed


def test_genomic_alteration_collapsed_verdict_is_resolved_token_not_rule_id():
    """The genomic-alteration lens declares verdict_key='genomic_alteration_profile', so the COLLAPSED
    VERDICT prompt line injects the RESOLVED multi-class verdict token — not driving_rule_id (a rule-id
    string like 'mutant-strongly-dependent-supportive'). Before the fix the fallback chain MISSED the
    real key (the <name>_verdict guess is 'genomic_alteration_profile_verdict' — note the extra
    '_verdict' — while the headline key is 'genomic_alteration_profile') and landed on driving_rule_id.
    genomic-alteration was the LAST verdict-skill left behind; mirrors the
    presence/selectivity/FR/safety/surface-modality-fit contract."""
    assert GENOMIC_ALTERATION.verdict_key == "genomic_alteration_profile"
    decision = {
        "target": "KRAS",
        "indication": "COADREAD",
        "headline": {
            "genomic_alteration_profile": "biomarker_stratified_dependency",
            "driving_rule_id": "mutant-strongly-dependent-supportive",
            "claim_vector": {"DEP": {"signal": "strong", "corroboration": "high"}},
        },
    }
    p = NE.build_capsule_prompt(decision, GENOMIC_ALTERATION)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "biomarker_stratified_dependency" in collapsed
    # the bare rule-id must not be what the model is handed as the one-word verdict
    assert "mutant-strongly-dependent-supportive" not in collapsed


def test_tractability_sm_collapsed_verdict_is_resolved_token_not_rule_id():
    """The tractability-small-molecule lens declares verdict_key='druggability_snapshot', so the COLLAPSED
    VERDICT prompt line injects the RESOLVED snapshot token — not driving_rule_id (a rule-id string like
    'known-drug-approved-antineoplastic-sm-supportive'). Before the fix the fallback chain MISSED the real
    key (the <name>_verdict guess is 'tractability_small_molecule_verdict' while the headline key is
    'druggability_snapshot') and landed on driving_rule_id. tractability-small-molecule was the LAST
    verdict-skill left behind; mirrors the presence/selectivity/FR/safety/surface/genomic contract."""
    assert TRACTABILITY_SM.verdict_key == "druggability_snapshot"
    decision = {
        "target": "EGFR",
        "indication": "LUAD",
        "headline": {
            "druggability_snapshot": "well_covered",
            "driving_rule_id": "e7-triangulated-target-engaged-supportive",
            "claim_vector": {"ACTIVITY": {"signal": "strong", "corroboration": "high"}},
        },
    }
    p = NE.build_capsule_prompt(decision, TRACTABILITY_SM)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "well_covered" in collapsed
    # the bare rule-id must not be what the model is handed as the one-word verdict
    assert "e7-triangulated-target-engaged-supportive" not in collapsed


def test_immune_context_collapsed_verdict_is_resolved_token_not_rule_id():
    """The immune-context lens declares verdict_key='immune_context_verdict', so the COLLAPSED VERDICT
    prompt line injects the RESOLVED effector-context token (immune_hot/…) — not driving_rule_id (a
    rule-id string like 'immune-context-hot-tce-supportive'). UNLIKE surface/genomic/tractability, the
    legacy <name>_verdict guess here ('immune-context' → 'immune_context_verdict') COINCIDES with the real
    headline key, so the collapsed line was already correct; declaring verdict_key removes that
    naming-coincidence dependency (a future rename can't silently regress it) and brings this lens into
    line with the presence/selectivity/FR/safety/surface/genomic/tractability contract."""
    from _skills_common.narrator_lenses import IMMUNE_CONTEXT

    assert IMMUNE_CONTEXT.verdict_key == "immune_context_verdict"
    decision = {
        "target": "MSLN",
        "indication": "PRAD",
        "headline": {
            "immune_context_verdict": "immune_hot",
            "driving_rule_id": "immune-context-hot-tce-supportive",
            "claim_vector": {"IMMUNE": {"signal": "strong", "corroboration": "moderate"}},
        },
    }
    p = NE.build_capsule_prompt(decision, IMMUNE_CONTEXT)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "immune_hot" in collapsed
    # the bare rule-id must not be what the model is handed as the one-word verdict
    assert "immune-context-hot-tce-supportive" not in collapsed


def test_mechanism_collapsed_verdict_is_resolved_token_not_rule_id():
    """The mechanism-and-pharmacology lens declares verdict_key='mechanism_verdict', so the COLLAPSED VERDICT
    prompt line injects the RESOLVED characterization token (well_characterized / partial / …) — NOT
    driving_rule_id (a rule-id string like 'mechanism-well-characterized-supportive'). This lens is
    mode='descriptive', but descriptive mode STILL builds the collapsed line, and — unlike the other three
    descriptive lenses, which carry no token — this skill emits a real `mechanism_verdict` (top-level
    decision['verdict'] is None here). Without the declared key the legacy <name>_verdict guess
    ('mechanism-and-pharmacology' → 'mechanism_and_pharmacology_verdict') MISSES the real headline key and
    the line fell through to the rule-id, which the LLM was observed to echo verbatim into user prose. Mirrors
    the surface/genomic/tractability guess-misses fix; mechanism was the last verdict-carrying skill left
    behind."""
    from _skills_common.narrator_lenses import MECHANISM_PHARMACOLOGY

    assert MECHANISM_PHARMACOLOGY.verdict_key == "mechanism_verdict"
    decision = {
        "target": "EGFR",
        "indication": "COADREAD",
        "headline": {
            "mechanism_verdict": "well_characterized",
            "driving_rule_id": "mechanism-well-characterized-supportive",
            "claim_vector": {"NETWORK": {"signal": "moderate", "corroboration": "moderate"}},
        },
    }
    p = NE.build_capsule_prompt(decision, MECHANISM_PHARMACOLOGY)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "well_characterized" in collapsed
    assert "mechanism-well-characterized-supportive" not in collapsed


def test_differentiation_landscape_collapsed_verdict_is_resolved_token_not_rule_id():
    """The differentiation-landscape lens declares verdict_key='differentiation_verdict', so the COLLAPSED
    VERDICT prompt line injects the RESOLVED co-mutation token (both_patterns_present / strong_cooccurring /
    strong_mutually_exclusive / …) — NOT driving_rule_id (a rule-id string like
    'cooccurrence-both-patterns-supportive'). This lens is mode='verdict' and emits a real
    `differentiation_verdict` (top-level decision['verdict'] is None — the descriptive fan-out gate). Without
    the declared key the legacy <name>_verdict guess ('differentiation-landscape' →
    'differentiation_landscape_verdict') MISSED the real headline key `differentiation_verdict` and the line
    fell through to the rule-id, which the LLM could echo verbatim into user prose. Mirrors the
    surface/genomic/tractability/mechanism guess-misses fix; differentiation was the last verdict-carrying
    lens left behind."""
    from _skills_common.narrator_lenses import DIFFERENTIATION_LANDSCAPE

    assert DIFFERENTIATION_LANDSCAPE.verdict_key == "differentiation_verdict"
    decision = {
        "target": "PCLO",
        "indication": "COADREAD",
        "headline": {
            "differentiation_verdict": "strong_cooccurring",
            "driving_rule_id": "cooccurrence-strong-supportive",
            "claim_vector": {"COMUT": {"signal": "strong", "corroboration": "moderate"}},
        },
    }
    p = NE.build_capsule_prompt(decision, DIFFERENTIATION_LANDSCAPE)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "strong_cooccurring" in collapsed
    assert "cooccurrence-strong-supportive" not in collapsed


def test_cis_feature_coherence_collapsed_verdict_is_resolved_token_not_rule_id():
    """The cis-feature-coherence lens declares verdict_key='cis_coherence_verdict', so the COLLAPSED VERDICT
    prompt line injects the RESOLVED coherence token (coherent_cis_driver / coherent_epigenetic_silencing /
    dependency_without_cis_dosage / …) — NOT driving_rule_id (a rule-id string like
    'cis-dosage-coupled-supportive'). This lens is mode='descriptive', but descriptive mode STILL builds the
    collapsed line, and — unlike combination-and-vulnerability / target-intrinsic (truly tokenless) — this
    skill supplies verdict_fn=_verdict and emits a real `cis_coherence_verdict` (top-level decision['verdict']
    is None; verdict-inert at nomination). Without the declared key the legacy <name>_verdict guess
    ('cis-feature-coherence' → 'cis_feature_coherence_verdict') MISSED the real headline key
    `cis_coherence_verdict` and the line fell through to the rule-id (confirmed live). Mirrors the
    surface/genomic/tractability/mechanism/differentiation guess-misses fix; cis-feature-coherence was the last
    verdict-carrying lens left behind."""
    from _skills_common.narrator_lenses import CIS_FEATURE_COHERENCE

    assert CIS_FEATURE_COHERENCE.verdict_key == "cis_coherence_verdict"
    decision = {
        "target": "ERBB2",
        "indication": "BRCA",
        "headline": {
            "cis_coherence_verdict": "coherent_cis_driver",
            "driving_rule_id": "cis-dosage-coupled-supportive",
            "claim_vector": {"CIS_DOSAGE": {"signal": "moderate", "corroboration": "moderate"}},
        },
    }
    p = NE.build_capsule_prompt(decision, CIS_FEATURE_COHERENCE)
    collapsed = p.split("COLLAPSED VERDICT", 1)[1].splitlines()[0]
    assert "coherent_cis_driver" in collapsed
    assert "cis-dosage-coupled-supportive" not in collapsed


def test_make_synthesize_fn_signature(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        NE, "narrate", lambda dec, lens, model_id=None: seen.update(lens=lens.name, m=model_id) or {"ok": 1}
    )
    fn = NE.make_synthesize_fn(FUNCTIONAL_REQUIREMENT)
    out = fn(_decision(), "modelX", "MSI_H")  # (decision, model_id, subtype_query)
    assert out == {"ok": 1} and seen["lens"] == "functional-requirement" and seen["m"] == "modelX"


# ── _render_literature: provenance-wrap defense (the "0 literature lines" bug) ─────────────────────
def _wrapped_lit():
    """A literature_synthesis block as a --literature-only decision.json can carry it: `axes` and
    `blind_spots` still provenance-WRAPPED as {value:[...], _source:'llm_synthesized', ...}."""
    stamp = {"_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}
    axes = [
        {
            "axis_key": "A",
            "literature_read": "strongly_supports",
            "agreement_vs_omics": "agree",
            "confidence": "high",
            "assertion": "EpCAM abundant in CRC.",
            "citations": [{"label": "Went 2006", "pmid": "16404434", "verified": True}],
        }
    ]
    blind = [{"signal": "localization", "why_omics_blind": "MS/RNA cannot resolve", "citations": []}]
    return {
        "literature_synthesis": {
            "axes": {"value": axes, **stamp},
            "blind_spots": {"value": blind, **stamp},
            "overall_consistency": "concordant",
        }
    }


def test_render_literature_unwraps_provenance_wrapped_axes():
    """Regression: a re-wrapped `axes` dict must still render axis lines, not iterate wrapper keys."""
    out = NE._render_literature(_wrapped_lit())
    assert "axis A" in out  # the axis line survives the unwrap
    assert "strongly_supports" in out
    assert "PMID:16404434" in out
    assert "OMICS-BLIND" in out  # blind_spots also unwrapped
    # sanity: an unwrapped (plain-list) block renders identically for axes
    plain = {
        "literature_synthesis": {
            "axes": _wrapped_lit()["literature_synthesis"]["axes"]["value"],
            "blind_spots": [],
            "overall_consistency": "concordant",
        }
    }
    assert "axis A" in NE._render_literature(plain)


def test_render_literature_still_empty_when_absent_or_errored():
    assert NE._render_literature({}) == ""
    assert NE._render_literature({"literature_synthesis": {"_literature_error": "boom"}}) == ""
    assert NE._render_literature({"literature_synthesis": {"axes": [], "blind_spots": []}}) == ""
