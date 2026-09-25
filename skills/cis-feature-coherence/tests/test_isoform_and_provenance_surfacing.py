"""cis-feature-coherence — #1598 data-package-utilization tests (VERDICT-INERT).

Pins the fixes for the under-utilized data package:
  * the previously-STRANDED cellline-isoform-expression card (dispatched but consumed by nothing) now
    reaches a surface — the molecular_form_caveat AND the synthesis facet.
  * the protein-leg NUMERIC provenance (cn_prot_spearman_r / delta_log2abundance_amplified_vs_neutral /
    n_paired_models_cn_protein / protein_dependency_pearson_r) is restored to the synthesis facet.
  * the patient (TCGA) raw cross-grain classes + case count reach the facet, not only the derived booleans.

None of these read the resolver — the verdict spine (cis_coherence_verdict + driving_rule_id + resolver
golden) is untouched (byte-stable verdict-inert). Hermetic (no S3/network).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

_run = load_run_py(Path(__file__).resolve().parent.parent, "cis_run_1598")
_molecular_form_caveat = _run._molecular_form_caveat
_synthesis_facet = _run._synthesis_facet
_SYNTHESIS_FACET_KEYS = _run._SYNTHESIS_FACET_KEYS


def _card(card_id: str, summary: dict) -> dict:
    return {"card_id": card_id, "summary": summary}


# ── molecular_form_caveat (the stranded isoform card, now surfaced) ─────────────────────────────
def test_molecular_form_caveat_none_when_isoform_unmeasured():
    for cls in (None, "data_unavailable"):
        assert _molecular_form_caveat({"isoform_expression_class": cls}) is None


def test_molecular_form_caveat_single_isoform_dominant():
    hl = {
        "isoform_expression_class": "single_isoform_dominant",
        "dominant_isoform_fraction": 0.91,
        "n_expressed_isoforms": 2,
        "dominant_isoform": "ENST00000269305",
    }
    c = _molecular_form_caveat(hl)
    assert c is not None
    assert c["isoform_expression_class"] == "single_isoform_dominant"
    assert c["single_isoform_target"] is True
    assert c["dominant_isoform_fraction"] == 0.91
    assert c["dominant_isoform"] == "ENST00000269305"


def test_molecular_form_caveat_isoform_diverse_is_not_a_single_isoform_target():
    c = _molecular_form_caveat({"isoform_expression_class": "isoform_diverse", "dominant_isoform_fraction": 0.32})
    assert c is not None and c["single_isoform_target"] is False


# ── the isoform card + numeric provenance reach the composed synthesis facet ────────────────────
def _facet_for(iso_class):
    cards = [
        _card("cis-feature-expression-coherence", {"cis_dosage_class": "cn_dosage_coupled_strong"}),
        _card(
            "cis-feature-protein-coherence",
            {
                "cis_protein_dosage_class": "prot_dosage_coupled_moderate",
                "cn_prot_spearman_r": 0.61,
                "delta_log2abundance_amplified_vs_neutral": 1.2,
                "n_paired_models_cn_protein": 44,
            },
        ),
        _card("abundance-dependency", {"protein_dependency_pearson_r": -0.35}),
        _card(
            "patient-cis-coherence",
            {
                "patient_cis_dosage_class": "cn_dosage_coupled_moderate",
                "patient_methylation_silencing_class": "no_silencing_signal",
                "n_cases_expression": 312,
            },
        ),
        _card("cellline-isoform-expression", {"isoform_expression_class": iso_class, "dominant_isoform_fraction": 0.9}),
    ]
    return _synthesis_facet(cards, fired=[], verdict_pair=("coherent_cis_driver", "some_rule"))


def test_facet_carries_the_isoform_card_that_was_previously_stranded():
    facet = _facet_for("single_isoform_dominant")
    # the raw isoform fields are now in the facet (previously the card reached NO surface)
    assert facet["isoform_expression_class"] == "single_isoform_dominant"
    assert facet["dominant_isoform_fraction"] == 0.9
    assert "n_expressed_isoforms" in facet
    assert "dominant_isoform" in facet
    # and the molecular_form_caveat fired
    assert facet["molecular_form_caveat"] is not None
    assert facet["molecular_form_caveat"]["isoform_expression_class"] == "single_isoform_dominant"


def test_facet_restores_protein_numeric_provenance():
    facet = _facet_for("single_isoform_dominant")
    assert facet["cn_prot_spearman_r"] == 0.61
    assert facet["delta_log2abundance_amplified_vs_neutral"] == 1.2
    assert facet["n_paired_models_cn_protein"] == 44
    assert facet["protein_dependency_pearson_r"] == -0.35


def test_facet_carries_patient_raw_classes_and_case_count():
    facet = _facet_for("single_isoform_dominant")
    assert facet["patient_cis_dosage_class"] == "cn_dosage_coupled_moderate"
    assert facet["patient_methylation_silencing_class"] == "no_silencing_signal"
    assert facet["patient_n_cases_expression"] == 312


def test_all_new_provenance_keys_are_declared_in_facet_key_tuple():
    for k in (
        "cn_prot_spearman_r",
        "delta_log2abundance_amplified_vs_neutral",
        "n_paired_models_cn_protein",
        "protein_dependency_pearson_r",
        "patient_cis_dosage_class",
        "patient_methylation_silencing_class",
        "patient_n_cases_expression",
        "isoform_expression_class",
        "dominant_isoform_fraction",
        "n_expressed_isoforms",
        "dominant_isoform",
        "molecular_form_caveat",
    ):
        assert k in _SYNTHESIS_FACET_KEYS
