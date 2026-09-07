"""Heterogeneity facet — verdict-inert cross-context dispersion (2026-08-12).

Hermetic: synthetic sub_results (cards keyed by id). Covers the four-cell comparator dispersion (+
discordant = maximal), CRISPR-vs-RNAi modality dispersion, the --subtypes-only per-stratum spread,
worst-case aggregation, and the empty case.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

run = load_run_py(Path(__file__).resolve().parents[1], "tp_run_het")


def _sr(cards_by_short: dict) -> dict:
    """short -> [(card_id, summary_dict), ...]  =>  sub_results shape."""
    return {
        short: {"cards": [{"card_id": cid, "summary": s} for cid, s in cards]}
        for short, cards in cards_by_short.items()
    }


def _panorama_sr(rows):
    return {
        run.SUBTYPE_SHORT: {
            "cards": [{"card_id": "subgroup-stratified-dependency", "summary": {"per_subgroup_metrics": rows}}]
        }
    }


def test_four_cell_comparator_dispersion():
    sr = _sr(
        {
            "selectivity": [
                (
                    "tumor-vs-normal-selectivity",
                    {
                        "cells_ran": 4,
                        "cells_supporting": 2,
                        "discordant": False,
                        "log2fc_cell_a": 2.0,
                        "log2fc_cell_b": 0.1,
                        "log2fc_cell_c": 1.0,
                    },
                )
            ]
        }
    )
    f = run._heterogeneity_facet(sr)
    s = f["sources"]["selectivity_comparators"]
    assert s["unsupported_fraction"] == 0.5 and s["dispersion"] == 0.5
    assert s["log2fc_cv"] is not None  # spread across cells computed
    assert f["heterogeneity_index"] == 0.5


def test_discordant_is_maximal_dispersion():
    sr = _sr(
        {"selectivity": [("tumor-vs-normal-selectivity", {"cells_ran": 4, "cells_supporting": 3, "discordant": True})]}
    )
    f = run._heterogeneity_facet(sr)
    assert f["sources"]["selectivity_comparators"]["dispersion"] == 1.0
    assert f["heterogeneity_index"] == 1.0


def test_modality_crispr_rnai_dispersion():
    sr = _sr({"dependency": [("crispr-rnai-dependency-concordance", {"fraction_agree": 0.7})]})
    f = run._heterogeneity_facet(sr)
    assert f["sources"]["modality_crispr_rnai"]["dispersion"] == 0.3
    assert f["heterogeneity_index"] == 0.3


def test_subtype_strata_only_under_subtypes():
    rows = [
        {
            "stratum": "MSI_H",
            "evidence_state": "measured",
            "subgroup_n_floor_met": True,
            "median_chronos": -0.9,
            "dependency_class": "dependent",
        },
        {
            "stratum": "MSS",
            "evidence_state": "measured",
            "subgroup_n_floor_met": True,
            "median_chronos": -0.05,
            "dependency_class": "non_dependent",
        },
    ]
    sr = _panorama_sr(rows)
    # without --subtypes: panorama ignored
    assert "subtype_strata" not in run._heterogeneity_facet(sr, subtypes=None)["sources"]
    # with --subtypes: two measured strata w/ different classes -> entropy > 0
    f = run._heterogeneity_facet(sr, subtypes=["MSI_H", "MSS"])
    st = f["sources"]["subtype_strata"]
    assert st["n_measured_strata"] == 2 and st["class_entropy"] == 1.0  # 2 distinct classes, 50/50
    assert st["metric_cv"] is not None
    assert f["heterogeneity_index"] == 1.0


def test_worst_case_over_sources_and_empty():
    sr = _sr(
        {
            "selectivity": [
                ("tumor-vs-normal-selectivity", {"cells_ran": 4, "cells_supporting": 3, "discordant": False})
            ],  # dispersion 0.25
            "dependency": [("crispr-rnai-dependency-concordance", {"fraction_agree": 0.4})],
        }
    )  # 0.6
    f = run._heterogeneity_facet(sr)
    assert f["heterogeneity_index"] == 0.6  # worst-case
    # empty: no source cards -> index None, sources {}
    empty = run._heterogeneity_facet(_sr({"x": [("some-other-card", {"foo": 1})]}))
    assert empty["heterogeneity_index"] is None and empty["sources"] == {}
