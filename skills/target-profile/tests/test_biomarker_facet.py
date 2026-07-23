"""Q12 biomarker-convergence facet — deterministic assembly (master-sequencing Part 3c).

Verifies the facet pulls corroboration + stratification + preferred_assay from synthetic sub_results,
and the golden cases the plan names: KRAS-like → strong_selection_biomarker (mutant-stratified);
housekeeping-like → none. No S3/LLM (pure dict fixtures)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run  # noqa: E402


def _sr(**cards_by_short):
    """Build a sub_results dict: short -> {cards:[{card_id, summary}]} from {short: {card_id: summary}}."""
    out = {}
    for short, card_map in cards_by_short.items():
        out[short] = {"cards": [{"card_id": cid, "summary": s} for cid, s in card_map.items()]}
    return out


def test_kras_like_strong_selection_biomarker_genomic():
    # the plan's golden: mutant-stratified dependency → strong_selection_biomarker, preferred genomic
    sr = _sr(
        genomic_alteration={"mutation-stratified-dependency": {"mutation_stratification_class": "mutant_strongly_dependent"},
                            "alteration-role": {"alteration_role": "direct_driver_gof"}},
        expression={"rna-protein-concordance": {"rna_as_biomarker": "partial_proxy"}},
    )
    f = run._biomarker_facet(sr)
    assert f["verdict"] == "strong_selection_biomarker"
    assert f["preferred_assay"] == "genomic"
    assert f["stratification_role"]["mutation_stratification_class"] == "mutant_strongly_dependent"


def test_predictive_biomarker_alteration_role_is_genomic_stratifier():
    sr = _sr(genomic_alteration={"alteration-role": {"alteration_role": "predictive_biomarker"}})
    f = run._biomarker_facet(sr)
    assert f["verdict"] == "strong_selection_biomarker"
    assert f["preferred_assay"] == "genomic"


def test_rna_adequate_proxy_prefers_rna():
    # no genomic stratifier; RNA is an adequate proxy → preferred RNA, corroborating_only
    sr = _sr(
        expression={"rna-protein-concordance": {"rna_as_biomarker": "adequate_proxy"},
                    "phospho-pathway-activity": {"phospho_activity_class": "phospho_active"}},
    )
    f = run._biomarker_facet(sr)
    assert f["preferred_assay"] == "RNA"
    assert f["verdict"] == "corroborating_only"


def test_poor_proxy_prefers_protein():
    sr = _sr(expression={"rna-protein-concordance": {"rna_as_biomarker": "poor_proxy"},
                         "phospho-pathway-activity": {"phospho_activity_class": "phospho_present"}})
    f = run._biomarker_facet(sr)
    assert f["preferred_assay"] == "protein"
    # corroboration present (phospho_present) → corroborating_only (not inadequate)
    assert f["verdict"] == "corroborating_only"


def test_poor_proxy_no_corroboration_is_inadequate():
    sr = _sr(expression={"rna-protein-concordance": {"rna_as_biomarker": "poor_proxy"}})
    f = run._biomarker_facet(sr)
    assert f["preferred_assay"] == "protein"
    assert f["verdict"] == "inadequate"


def test_housekeeping_like_none():
    # the plan's other golden: nothing biomarker-relevant → none. All corroboration signals must be
    # in the excluded set (None / data_unavailable / not_informative) and no stratifier present.
    sr = _sr(
        expression={"rna-protein-concordance": {"rna_as_biomarker": "data_unavailable"},
                    "phospho-pathway-activity": {"phospho_activity_class": "data_unavailable"},
                    "expression-purity-confound": {"purity_confound_class": "data_unavailable"}},
        genomic_alteration={"alteration-role": {"alteration_role": "data_unavailable"},
                            "mutation-stratified-dependency": {"mutation_stratification_class": "data_unavailable"}},
    )
    f = run._biomarker_facet(sr)
    assert f["verdict"] == "none"
    assert f["preferred_assay"] == "neither"


def test_missing_subskills_null_not_fabricated():
    # sub-skills absent → fields recorded null (honest coverage), verdict none, no crash
    f = run._biomarker_facet({})
    assert f["verdict"] == "none"
    assert f["corroboration_role"] == {} and f["stratification_role"] == {}


def test_facet_is_verdict_inert_shape():
    # the facet must NOT carry an overall_recommendation / nominate field (it's not a gate)
    f = run._biomarker_facet(_sr(genomic_alteration={"alteration-role": {"alteration_role": "predictive_biomarker"}}))
    assert "overall_recommendation" not in f and "nominate" not in f
    assert "_disclaimer" in f  # states the facet-not-gate contract
