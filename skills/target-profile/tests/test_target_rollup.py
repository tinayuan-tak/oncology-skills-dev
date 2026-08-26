"""PR-4 — target_rollup.v1 + target_coherence.v1 (verdict-inert distillation). Pins the 7-axis roll-up,
the NEGATIVE cross-axis block (ignores recommendation_gate.fired), the thesis/coherence lens, and the
PROMINENT subtype block — over the 4 archetype shapes (KRAS driver / ERBB2 amp-antigen / DLL3 surface
antigen / intracellular non-dependent). Pure functions of sub_results + facets; no S3/render."""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_roll", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_load()
import tp_facets as tf  # noqa: E402


def _sr(**verdicts):
    """verdicts: short -> (verdict, driving_rule_id)."""
    return {s: {"verdict": v} for s, v in verdicts.items()}


def _mfc(**fits):
    return {c: {"fit": f} for c, f in fits.items()}


def test_kras_driver_favorable_not_blocked():
    sr = _sr(dependency=("lineage_selective", "lineage-selective-supportive"),
             surface_modality=("pmhc_tce_supported", "r"),
             safety=("highly_constrained_safety_concern", "r"),
             cis_coherence=("coherent_cis_driver", "r"))
    r = tf.build_target_rollup(sr, _mfc(small_molecule="conditional", degrader="unfavorable",
                                        adc="not_applicable_by_axis"))
    assert r["axes"]["biological_necessity"]["band"] == "favorable"
    assert r["biology_axis"] == "intracellular_intrinsic"
    assert r["block"]["blocked"] is False                      # escapable via mutant-selective SM
    c = tf.build_target_coherence(sr, r)
    assert c["thesis"]["primary"] == "oncogene_addiction_driver"


def test_erbb2_amp_antigen_not_blocked():
    sr = _sr(dependency=("non_dependent_paralog_buffered", "r"),
             genomic_alteration=("biomarker_stratified_dependency", "cn-amplified-strongly-dependent-supportive"),
             surface_modality=("adc_preferred_tce_unsafe", "r"),
             safety=("human_genetics_safety_concern", "r"))
    r = tf.build_target_rollup(sr, _mfc(small_molecule="unfavorable", adc="favorable", antibody="favorable",
                                        bite_tce="unfavorable"))
    assert r["axes"]["biological_necessity"]["call"] == "amplification_driven"
    assert r["axes"]["deliverability"]["viable_channels"] == ["adc", "antibody"]
    assert r["block"]["blocked"] is False
    assert tf.build_target_coherence(sr, r)["thesis"]["primary"] == "amplification_overexpression_antigen"


def test_dll3_surface_antigen_reclassified_not_blocked():
    sr = _sr(dependency=("non_dependent", "non-dependent-killer"),
             genomic_alteration=("confirmed_driver", "mut-missense-dominant-supportive"),
             surface_modality=("adc_preferred_tce_unsafe", "r"),
             cis_coherence=("cis_uncoupled_no_dependency", "r"))
    r = tf.build_target_rollup(sr, _mfc(adc="favorable", antibody="favorable", bite_tce="unfavorable"))
    A = r["axes"]["biological_necessity"]
    assert A["call"] == "antigen_no_survival_necessity" and A["band"] == "insufficient"
    assert r["block"]["blocked"] is False                      # antigen non_dependent does NOT block
    c = tf.build_target_coherence(sr, r)
    assert c["thesis"]["primary"] == "surface_antigen_no_dependency"
    assert c["thesis"]["reclassified_note"]                    # mut-spectrum driver flagged
    assert any("data_artifact" in a for a in c["coherence"]["artifact_flags"])


def test_intracellular_no_necessity_blocks():
    sr = _sr(dependency=("non_dependent", "non-dependent-killer"),
             surface_modality=("neither_viable", "r"))          # intracellular
    r = tf.build_target_rollup(sr, _mfc(small_molecule="unfavorable"))
    assert r["axes"]["biological_necessity"]["call"] == "no_necessity"
    assert r["block"]["blocked"] is True
    assert any(b["kind"] == "no_biological_necessity" for b in r["block"]["blocking_axes"])


def test_subtype_block_is_prominent():
    sr = _sr(dependency=("lineage_selective", "r"), surface_modality=("pmhc_tce_supported", "r"))
    # convergent
    r = tf.build_target_rollup(sr, _mfc(small_molecule="conditional"),
                               subtype_facet={"convergent_subtypes": ["MSI-H", "KRAS_G12C"],
                                              "axes_available": ["expression", "dependency"],
                                              "n_subtypes_evaluated": 5})
    assert r["subtype"]["prominence"] == "convergent" and "MSI-H" in r["subtype"]["headline"]
    # whole-cohort (no facet)
    r2 = tf.build_target_rollup(sr, _mfc(small_molecule="conditional"), subtype_facet=None)
    assert r2["subtype"]["prominence"] == "whole_cohort" and "Whole-cohort" in r2["subtype"]["headline"]


def test_subtype_banner_prominent_in_html_header():
    import tp_render_html as tph
    sr = {"expression": {"skill_dir": "tumor-presence", "cards": [{"card_id": "rna", "summary": {}}],
                         "verdict": ("tumor_broadly_expressed", "r"), "fired": []}}
    llm = {"executive_summary": {"value": "e"}, "overall_recommendation": {"value": "hold"},
           "confidence": {"value": "high"}, "tension_analysis": {"value": "t"}}
    tr = tf.build_target_rollup(sr, {"adc": {"fit": "favorable"}},
                                subtype_facet={"convergent_subtypes": ["MSI-H"],
                                               "axes_available": ["expression"], "n_subtypes_evaluated": 3})
    h = tph._render_target_profile_html("KRAS", "COADREAD", sr, llm, {}, target_rollup=tr)
    assert "subtype-banner subtype-hit" in h and "MSI-H" in h    # prominent, in the header
    # whole-cohort → muted banner, still present (never silently dropped)
    tr2 = tf.build_target_rollup(sr, {"adc": {"fit": "favorable"}}, subtype_facet=None)
    h2 = tph._render_target_profile_html("KRAS", "COADREAD", sr, llm, {}, target_rollup=tr2)
    assert "subtype-banner subtype-muted" in h2 and "Whole-cohort" in h2


def test_assemblers_do_not_mutate_sub_results():
    sr = _sr(dependency=("lineage_selective", "r"), surface_modality=("pmhc_tce_supported", "r"))
    import copy
    snap = copy.deepcopy(sr)
    tf.build_target_rollup(sr, _mfc(small_molecule="conditional"))
    tf.build_target_coherence(sr, None)
    assert sr == snap        # verdict-inert: pure read, no mutation of the spine input
