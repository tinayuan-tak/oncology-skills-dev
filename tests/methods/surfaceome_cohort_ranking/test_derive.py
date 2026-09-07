"""Synthetic-data tests for surfaceome_cohort_ranking.derive (no S3)."""

import numpy as np
import pandas as pd

from methods.surfaceome_cohort_ranking.derive import (
    CPTAC_COHORT_MAP,
    OUTPUT_COLUMNS,
    rank_indication,
    _cell_pairs,
    _cohort_rank_class,
)


def _surface_df():
    # SURF1/SURF2/SURF3 are surface; NOTSURF is not; EMPTYSYM has no symbol.
    return pd.DataFrame(
        [
            {
                "uniprot_ac": "P1",
                "gene_symbol": "SURF1",
                "surface_protein_family": "GPCR",
                "is_surface_protein": True,
                "surfaceome_confidence_score": 0.9,
            },
            {
                "uniprot_ac": "P2",
                "gene_symbol": "SURF2",
                "surface_protein_family": "Adhesion",
                "is_surface_protein": True,
                "surfaceome_confidence_score": 0.8,
            },
            {
                "uniprot_ac": "P3",
                "gene_symbol": "SURF3",
                "surface_protein_family": "CD_molecule",
                "is_surface_protein": True,
                "surfaceome_confidence_score": 0.7,
            },
            {
                "uniprot_ac": "P4",
                "gene_symbol": "NOTSURF",
                "surface_protein_family": "Not_surface",
                "is_surface_protein": False,
                "surfaceome_confidence_score": 0.1,
            },
            {
                "uniprot_ac": "P5",
                "gene_symbol": "",
                "surface_protein_family": "GPCR",
                "is_surface_protein": True,
                "surfaceome_confidence_score": 0.5,
            },
        ]
    )


def _sens_3cell():
    # 3-cell indication. SURF1 strong-up robust; SURF2 up but only 1/3 supporting; SURF3 down;
    # NOTSURF up robust (must be filtered out — not surface).
    return pd.DataFrame(
        [
            {
                "gene_symbol": "SURF1",
                "cells_ran": 3,
                "cells_supporting": 3,
                "dominant_direction": "up",
                "log2fc_A": 3.0,
                "padj_A": 1e-10,
                "log2fc_B": 2.5,
                "padj_B": 1e-8,
                "log2fc_C": 2.8,
                "padj_C": 1e-9,
                "max_abs_log2fc": 3.0,
            },
            {
                "gene_symbol": "SURF2",
                "cells_ran": 3,
                "cells_supporting": 1,
                "dominant_direction": "up",
                "log2fc_A": 1.0,
                "padj_A": 1e-3,
                "log2fc_B": 0.1,
                "padj_B": 0.6,
                "log2fc_C": 0.2,
                "padj_C": 0.7,
                "max_abs_log2fc": 1.0,
            },
            {
                "gene_symbol": "SURF3",
                "cells_ran": 3,
                "cells_supporting": 3,
                "dominant_direction": "down",
                "log2fc_A": -2.0,
                "padj_A": 1e-6,
                "log2fc_B": -2.1,
                "padj_B": 1e-6,
                "log2fc_C": -1.9,
                "padj_C": 1e-5,
                "max_abs_log2fc": 2.1,
            },
            {
                "gene_symbol": "NOTSURF",
                "cells_ran": 3,
                "cells_supporting": 3,
                "dominant_direction": "up",
                "log2fc_A": 5.0,
                "padj_A": 1e-20,
                "log2fc_B": 4.0,
                "padj_B": 1e-15,
                "log2fc_C": 4.5,
                "padj_C": 1e-18,
                "max_abs_log2fc": 5.0,
            },
        ]
    )


def test_cell_pairs_discovery():
    assert _cell_pairs(["gene_symbol", "log2fc_A", "padj_A", "log2fc_C", "padj_C"]) == [
        ("log2fc_A", "padj_A"),
        ("log2fc_C", "padj_C"),
    ]


def test_surface_only_and_direction_filter():
    out = rank_indication("COADREAD", _sens_3cell(), _surface_df(), min_cells_supporting=2)
    genes = set(out.gene_symbol)
    assert "NOTSURF" not in genes  # non-surface excluded
    assert "SURF3" not in genes  # tumor-DOWN excluded
    assert "SURF2" not in genes  # only 1/3 supporting < min(2,3)
    assert genes == {"SURF1"}
    assert list(out.columns) == OUTPUT_COLUMNS


def test_single_cell_indication_not_dropped():
    # OV-style: only cell C present, cells_ran=1. Must survive with min(2,1)=1.
    sens = pd.DataFrame(
        [
            {
                "gene_symbol": "SURF1",
                "cells_ran": 1,
                "cells_supporting": 1,
                "dominant_direction": "up",
                "log2fc_C": 2.0,
                "padj_C": 1e-5,
                "max_abs_log2fc": 2.0,
            },
        ]
    )
    out = rank_indication("OV", sens, _surface_df(), cptac_df=None, min_cells_supporting=2)
    assert set(out.gene_symbol) == {"SURF1"}
    assert out.iloc[0].tissue_rank == 1
    assert out.iloc[0].tissue_percentile_rna == 100.0


def test_ranking_order_and_percentile():
    # two robust surface genes; SURF1 stronger than SURF2 (make SURF2 robust here).
    sens = pd.DataFrame(
        [
            {
                "gene_symbol": "SURF1",
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "up",
                "log2fc_A": 3.0,
                "padj_A": 1e-10,
                "log2fc_B": 3.0,
                "padj_B": 1e-10,
                "max_abs_log2fc": 3.0,
            },
            {
                "gene_symbol": "SURF2",
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "up",
                "log2fc_A": 1.0,
                "padj_A": 1e-3,
                "log2fc_B": 1.0,
                "padj_B": 1e-3,
                "max_abs_log2fc": 1.0,
            },
        ]
    )
    out = rank_indication("HNSC", sens, _surface_df(), min_cells_supporting=2).set_index("gene_symbol")
    assert out.loc["SURF1", "tissue_rank"] == 1
    assert out.loc["SURF2", "tissue_rank"] == 2
    assert out.loc["SURF1", "tissue_percentile_rna"] == 100.0
    assert out.loc["SURF2", "tissue_percentile_rna"] == 0.0
    assert out.loc["SURF1", "ranking_score"] > out.loc["SURF2", "ranking_score"]


def test_cptac_concordance():
    cptac = pd.DataFrame(
        [
            {
                "cohort": "COAD",
                "gene_symbol": "SURF1",
                "protein_effect_size": 2.0,
                "protein_expression_class": "strong_up",
            },
            {
                "cohort": "COAD",
                "gene_symbol": "SURF2",
                "protein_effect_size": -1.5,
                "protein_expression_class": "modest_down",
            },
            {"cohort": "COAD", "gene_symbol": "SURF3", "protein_effect_size": 0.1, "protein_expression_class": "ns"},
        ]
    )
    # all three surface + robust up
    sens = pd.DataFrame(
        [
            {
                "gene_symbol": g,
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "up",
                "log2fc_A": 2.0,
                "padj_A": 1e-8,
                "log2fc_B": 2.0,
                "padj_B": 1e-8,
                "max_abs_log2fc": 2.0,
            }
            for g in ("SURF1", "SURF2", "SURF3")
        ]
    )
    out = rank_indication("COADREAD", sens, _surface_df(), cptac_df=cptac, min_cells_supporting=2).set_index(
        "gene_symbol"
    )
    assert out.loc["SURF1", "rna_protein_concordance"] == "agreement"
    assert out.loc["SURF2", "rna_protein_concordance"] == "disagreement"
    assert out.loc["SURF3", "rna_protein_concordance"] == "rna_only"
    # protein percentile defined for covered genes
    assert not np.isnan(out.loc["SURF1", "tissue_percentile_protein"])
    assert out.loc["SURF1", "tissue_percentile_protein"] == 100.0  # highest effect size


def test_no_cptac_cohort_is_no_protein():
    # STAD has no CPTAC cohort in the map.
    assert "STAD" not in CPTAC_COHORT_MAP
    sens = pd.DataFrame(
        [
            {
                "gene_symbol": "SURF1",
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "up",
                "log2fc_A": 2.0,
                "padj_A": 1e-8,
                "log2fc_B": 2.0,
                "padj_B": 1e-8,
                "max_abs_log2fc": 2.0,
            },
        ]
    )
    cptac = pd.DataFrame(
        [
            {
                "cohort": "BRCA",
                "gene_symbol": "SURF1",
                "protein_effect_size": 2.0,
                "protein_expression_class": "strong_up",
            }
        ]
    )
    out = rank_indication("STAD", sens, _surface_df(), cptac_df=cptac, min_cells_supporting=2)
    assert out.iloc[0].rna_protein_concordance == "no_protein"
    assert np.isnan(out.iloc[0].tissue_percentile_protein)


def test_cohort_rank_class_thresholds():
    assert _cohort_rank_class(99.5) == "top_1_percent"
    assert _cohort_rank_class(96.0) == "top_5"
    assert _cohort_rank_class(80.0) == "top_25"
    assert _cohort_rank_class(10.0) == "below_25_percent"


def test_empty_when_no_surface_hits():
    sens = pd.DataFrame(
        [
            {
                "gene_symbol": "NOTSURF",
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "up",
                "log2fc_A": 2.0,
                "padj_A": 1e-8,
                "log2fc_B": 2.0,
                "padj_B": 1e-8,
                "max_abs_log2fc": 2.0,
            },
        ]
    )
    out = rank_indication("HNSC", sens, _surface_df(), min_cells_supporting=2)
    assert out.empty
    assert list(out.columns) == OUTPUT_COLUMNS
