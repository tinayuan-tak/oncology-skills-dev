"""cis-feature-coherence — #1787 facet-parity (VERDICT-INERT).

Every NUMERIC provenance value emitted into the headline `hl` dict must either reach the synthesis facet
(`_SYNTHESIS_FACET_KEYS`) or be listed in `_FACET_EXCLUDED_HL_NUMERICS` with an inline rationale. This
closes the F4 gap where several primary leg effect sizes (the mRNA spearman / CN→mRNA slope / amplified-
vs-neutral delta, the leg-2 mRNA pearson, the conjoint ΔCHRONOS) were written into `hl` but dropped from
the facet, so a synthesis-facet-only consumer saw the classes without the numerics that back them.

The facet is a verdict-INERT projection — nothing here reads or moves the resolver verdict, so the
verdict spine (cis_coherence_verdict + driving_rule_id + resolver golden) is byte-stable. Hermetic.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

_run = load_run_py(Path(__file__).resolve().parent.parent, "cis_run_1787")
_headline = _run._headline
_SYNTHESIS_FACET_KEYS = set(_run._SYNTHESIS_FACET_KEYS)
_FACET_EXCLUDED_HL_NUMERICS = set(_run._FACET_EXCLUDED_HL_NUMERICS)


def _card(card_id: str, summary: dict) -> dict:
    return {"card_id": card_id, "summary": summary}


def _fully_numeric_cards() -> list:
    """Every numeric leg field populated, so `_headline` emits the full numeric key set (no None gaps)."""
    return [
        _card(
            "cis-feature-expression-coherence",
            {
                "cis_dosage_class": "cn_dosage_coupled_strong",
                "cis_dosage_driver": "pan_panel_correlation",
                "cis_dosage_direction": "amplification",
                "cis_dosage_direction_basis": "amplified_vs_deleted_contrast",
                "evidence_scope": "pan_lineage_evidence_only",
                "cn_expr_spearman_r": 0.55,
                "cn_expr_spearman_p": 1e-9,
                "cn_expr_slope_log2tpm_per_cn": 0.8,
                "relative_cn_iqr": 0.4,
                "delta_log2tpm_amplified_vs_neutral": 1.3,
                "subset_delta_log2tpm_amplified_vs_neutral": 1.1,
                "n_amplified": 40,
                "subset_within_lineage_delta_log2tpm": 0.9,
                "subset_n_lineages_compared": 5,
                "amplified_dominant_lineage_fraction": 0.3,
                "n_deleted": 12,
                "deleted_subset_delta_log2tpm": -0.7,
                "deleted_within_lineage_delta_log2tpm": -0.4,
                "deleted_subset_mannwhitney_p": 0.02,
                "n_cell_lines_evaluated": 700,
            },
        ),
        _card(
            "cis-feature-protein-coherence",
            {
                "cis_protein_dosage_class": "prot_dosage_coupled_moderate",
                "cn_prot_spearman_r": 0.61,
                "cn_prot_slope_log2abundance_per_cn": 0.5,
                "delta_log2abundance_amplified_vs_neutral": 1.2,
                "n_paired_models_cn_protein": 44,
            },
        ),
        _card(
            "cellline-methylation-expression-coherence",
            {
                "methylation_silencing_class": "silencing_coupled_strong",
                "silencing_driver": "subset_hypermethylation",
                "subset_median_delta_log2tpm": -2.1,
                "n_hypermethylated": 30,
                "subset_within_lineage_delta_log2tpm": -1.8,
                "subset_n_lineages_compared": 4,
                "hypermethylated_dominant_lineage_fraction": 0.25,
                "lineage_collapse_ratio": 0.85,
                "broad_quartile_delta_log2tpm": -1.2,
                "broad_quartile_within_lineage_delta_log2tpm": -1.0,
            },
        ),
        _card("expression-dependency-correlation", {"correlation_class": "expr_dep_coupled", "pearson_r": -0.42}),
        _card(
            "abundance-dependency",
            {"abundance_dependency_class": "abd_dep_coupled", "protein_dependency_pearson_r": -0.35},
        ),
        _card(
            "amp-expr-stratified-dependency",
            {"amp_expr_stratification_class": "conjoint_coupled", "delta_chronos_amp_expr_vs_rest": -0.6},
        ),
        _card(
            "patient-cis-coherence",
            {
                "patient_cis_dosage_class": "cn_dosage_coupled_moderate",
                "patient_methylation_silencing_class": "epigenetic_silencing",
                "n_cases_expression": 312,
            },
        ),
        _card(
            "cellline-isoform-expression",
            {
                "isoform_expression_class": "single_isoform_dominant",
                "dominant_isoform_fraction": 0.9,
                "n_expressed_isoforms": 3,
                "dominant_isoform": "ENST00000269305",
            },
        ),
    ]


def _numeric_hl_keys() -> set:
    hl = _headline(_fully_numeric_cards(), fired=[], verdict_pair=("coherent_cis_driver", "some_rule"))
    return {k for k, v in hl.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


def test_every_numeric_hl_key_is_in_facet_or_documented_excluded():
    numeric = _numeric_hl_keys()
    # sanity: the fixture actually exercised a broad numeric surface, not an empty/degenerate hl
    assert len(numeric) >= 20
    unaccounted = numeric - _SYNTHESIS_FACET_KEYS - _FACET_EXCLUDED_HL_NUMERICS
    assert not unaccounted, f"numeric hl keys neither in the facet nor documented-excluded: {sorted(unaccounted)}"


def test_excluded_set_is_disjoint_from_facet():
    # a key is EITHER surfaced in the facet OR deliberately excluded — never both
    assert not (_FACET_EXCLUDED_HL_NUMERICS & _SYNTHESIS_FACET_KEYS)


def test_facet_parity_primary_effect_sizes_now_reach_the_facet():
    # the #1787 additions: the primary leg effect sizes previously dropped from the facet
    for k in (
        "cn_expr_spearman_r",
        "cn_expr_slope_log2tpm_per_cn",
        "delta_log2tpm_amplified_vs_neutral",
        "expression_dependency_pearson_r",
        "amp_expr_delta_chronos",
    ):
        assert k in _SYNTHESIS_FACET_KEYS
