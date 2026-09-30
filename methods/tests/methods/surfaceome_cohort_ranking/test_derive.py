"""Synthetic-data tests for surfaceome_cohort_ranking.derive (no S3)."""

import numpy as np
import pandas as pd

from onc_methods.surfaceome_cohort_ranking.derive import (
    CPTAC_COHORT_MAP,
    INDICATION_NORMAL_CAVEAT,
    OUTPUT_COLUMNS,
    _cell_pairs,
    _cohort_rank_class,
    rank_indication,
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


def _sens_ac():
    # 2-cell indication (A/C; cell B removed in analysis-methods#727). SURF1 strong-up robust;
    # SURF2 up but only 1/2 supporting; SURF3 down; NOTSURF up robust (filtered — not surface).
    return pd.DataFrame(
        [
            {
                "gene_symbol": "SURF1",
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "up",
                "log2fc_A": 3.0,
                "padj_A": 1e-10,
                "log2fc_C": 2.8,
                "padj_C": 1e-9,
                "max_abs_log2fc": 3.0,
            },
            {
                "gene_symbol": "SURF2",
                "cells_ran": 2,
                "cells_supporting": 1,
                "dominant_direction": "up",
                "log2fc_A": 1.0,
                "padj_A": 1e-3,
                "log2fc_C": 0.2,
                "padj_C": 0.7,
                "max_abs_log2fc": 1.0,
            },
            {
                "gene_symbol": "SURF3",
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "down",
                "log2fc_A": -2.0,
                "padj_A": 1e-6,
                "log2fc_C": -1.9,
                "padj_C": 1e-5,
                "max_abs_log2fc": 2.0,
            },
            {
                "gene_symbol": "NOTSURF",
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "up",
                "log2fc_A": 5.0,
                "padj_A": 1e-20,
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
    out = rank_indication("COADREAD", _sens_ac(), _surface_df(), min_cells_supporting=2)
    genes = set(out.gene_symbol)
    assert "NOTSURF" not in genes  # non-surface excluded
    assert "SURF3" not in genes  # tumor-DOWN excluded
    assert "SURF2" not in genes  # only 1/2 supporting < min(2,2)
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
                "log2fc_C": 3.0,
                "padj_C": 1e-10,
                "max_abs_log2fc": 3.0,
            },
            {
                "gene_symbol": "SURF2",
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "up",
                "log2fc_A": 1.0,
                "padj_A": 1e-3,
                "log2fc_C": 1.0,
                "padj_C": 1e-3,
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
                "log2fc_C": 2.0,
                "padj_C": 1e-8,
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
                "log2fc_C": 2.0,
                "padj_C": 1e-8,
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
                "log2fc_C": 2.0,
                "padj_C": 1e-8,
                "max_abs_log2fc": 2.0,
            },
        ]
    )
    out = rank_indication("HNSC", sens, _surface_df(), min_cells_supporting=2)
    assert out.empty
    assert list(out.columns) == OUTPUT_COLUMNS


def _sens_laml():
    # LAML-style single-cell-C product (tumor vs GTEx whole blood; no adjacent normal => cell A empty).
    return pd.DataFrame(
        [
            {
                "gene_symbol": "SURF1",
                "cells_ran": 1,
                "cells_supporting": 1,
                "dominant_direction": "up",
                "log2fc_C": 2.5,
                "padj_C": 1e-7,
                "max_abs_log2fc": 2.5,
            },
        ]
    )


def test_laml_caveat_propagated_to_every_row():
    out = rank_indication("LAML", _sens_laml(), _surface_df(), cptac_df=None, min_cells_supporting=2)
    assert set(out.gene_symbol) == {"SURF1"}  # single-cell-C survives, as OV does
    caveat = out["normal_contrast_caveat"]
    assert (caveat == INDICATION_NORMAL_CAVEAT["LAML"]).all()
    assert "whole blood" in caveat.iloc[0] and "maturation-state confound" in caveat.iloc[0]


def test_normal_indication_has_empty_caveat():
    # A tissue-matched indication carries no normal-contrast caveat (guards against a vacuous map that
    # stamps the confound everywhere).
    out = rank_indication("COADREAD", _sens_ac(), _surface_df(), min_cells_supporting=2)
    assert not out.empty
    assert (out["normal_contrast_caveat"] == "").all()


def test_caveat_is_rank_inert():
    # The caveat is a per-indication annotation, not a ranking input: the same fixture ranked as a
    # caveated (LAML) vs non-caveated (OV) indication must produce identical ranking columns.
    laml = rank_indication("LAML", _sens_laml(), _surface_df(), cptac_df=None, min_cells_supporting=2)
    ov = rank_indication("OV", _sens_laml(), _surface_df(), cptac_df=None, min_cells_supporting=2)
    rank_cols = ["gene_symbol", "ranking_score", "tissue_rank", "tissue_percentile_rna", "cohort_rank_class"]
    pd.testing.assert_frame_equal(laml[rank_cols].reset_index(drop=True), ov[rank_cols].reset_index(drop=True))
    assert laml["normal_contrast_caveat"].iloc[0] != ""
    assert ov["normal_contrast_caveat"].iloc[0] == ""


def test_caveat_map_scope():
    # Only LAML is currently caveated; keep the map from silently growing/emptying.
    assert set(INDICATION_NORMAL_CAVEAT) == {"LAML"}
    assert INDICATION_NORMAL_CAVEAT["LAML"]


def _sens_single_arm_conflation():
    """A 2-arm (A+C) product with three surface genes exercising the NA-conflation bug
    (analysis-methods#864). The SHIPPED cells_ran/cells_supporting columns are set to the
    conflated values a real product ships (cells_ran = per-gene non-NaN padj count); the
    fixed consumer must IGNORE them and re-derive from padj_A/padj_C directly.
      (i)   SURF1 — sig in BOTH arms.
      (ii)  SURF2 — sig in C only because A NA-filtered it (padj_A = NaN). The shipped
            cells_ran conflates this to 1, which used to earn robustness 1/1 = 1.0.
      (iii) SURF3 — sig in C only; A ran and tested NON-significant (padj_A present, > q).
    """
    return pd.DataFrame(
        [
            {
                "gene_symbol": "SURF1",
                # shipped (deliberately trusted-nothing): both arms non-NaN
                "cells_ran": 2,
                "cells_supporting": 2,
                "dominant_direction": "up",
                "log2fc_A": 3.0,
                "padj_A": 1e-10,
                "log2fc_C": 3.0,
                "padj_C": 1e-10,
                "max_abs_log2fc": 3.0,
            },
            {
                "gene_symbol": "SURF2",
                # shipped conflation: A NA-filtered -> non-NaN padj count == 1
                "cells_ran": 1,
                "cells_supporting": 1,
                "dominant_direction": "up",
                "log2fc_A": np.nan,
                "padj_A": np.nan,
                "log2fc_C": 2.5,
                "padj_C": 1e-9,
                "max_abs_log2fc": 2.5,
            },
            {
                "gene_symbol": "SURF3",
                # A ran and was non-significant -> shipped cells_ran == 2, supporting == 1
                "cells_ran": 2,
                "cells_supporting": 1,
                "dominant_direction": "up",
                "log2fc_A": 0.3,
                "padj_A": 0.6,
                "log2fc_C": 2.5,
                "padj_C": 1e-9,
                "max_abs_log2fc": 2.5,
            },
        ]
    )


def test_single_arm_support_does_not_outrank_two_arm():
    # min_cells_supporting=1 keeps all three so the ORDER is observable. The fix must:
    #   - re-derive cells_ran = product arm count (2) for the A-filtered gene, NOT the
    #     conflated 1 -> robustness 0.5, not an inflated 1.0;
    #   - order sig-in-both (i) strictly above sig-in-C-only (ii);
    #   - give the A-filtered (ii) and A-tested-nonsig (iii) genes the SAME robustness
    #     (both 1/2), so neither out-ranks a two-arm-measured gene via an inflated ratio.
    out = rank_indication("COADREAD", _sens_single_arm_conflation(), _surface_df(), min_cells_supporting=1).set_index(
        "gene_symbol"
    )
    assert set(out.index) == {"SURF1", "SURF2", "SURF3"}

    # cells_ran re-derived to the product arm count for every gene (the A-filtered gene's
    # shipped 1 is discarded).
    assert out.loc["SURF1", "cells_ran"] == 2
    assert out.loc["SURF2", "cells_ran"] == 2  # was conflated to 1 by the shipped column
    assert out.loc["SURF3", "cells_ran"] == 2
    assert out.loc["SURF1", "cells_supporting"] == 2
    assert out.loc["SURF2", "cells_supporting"] == 1
    assert out.loc["SURF3", "cells_supporting"] == 1

    # (i) > (ii): sig-in-both ranks first; sig-in-one-arm does not tie it.
    assert out.loc["SURF1", "tissue_rank"] == 1
    assert out.loc["SURF1", "ranking_score"] > out.loc["SURF2", "ranking_score"]
    assert out.loc["SURF1", "ranking_score"] > out.loc["SURF3", "ranking_score"]

    # (ii) and (iii) carry the same (0.5) robustness weight; the A-filtered gene gets no
    # inflated credit over the A-tested-nonsig gene (same C evidence, same weighting).
    assert out.loc["SURF2", "ranking_score"] == out.loc["SURF3", "ranking_score"]


def test_single_arm_support_dropped_at_default_threshold():
    # At the default min_cells_supporting=2 the crux fix is symmetry: in a 2-arm product a
    # gene supported in ONE arm is dropped whether the other arm NA-filtered it (SURF2) or
    # tested it non-significant (SURF3) — the conflated gene no longer sneaks past the
    # filter that a genuinely two-arm-measured single-supported gene is denied.
    out = rank_indication("COADREAD", _sens_single_arm_conflation(), _surface_df(), min_cells_supporting=2)
    assert set(out.gene_symbol) == {"SURF1"}


def test_carried_but_unrun_arm_not_counted_in_denominator():
    # SCLC-style: the product CARRIES log2fc_A/padj_A columns but that arm ran for no gene
    # (padj_A entirely NaN) — only cell C ran. cells_ran must read 1 (arms that RAN), not 2
    # (columns present), so a cell-C-significant gene survives the default threshold exactly
    # as a genuine 1-arm product does. Counting the carried-but-unrun column would demand
    # 2-arm support and wipe every gene (the SCLC 1558->0 regression).
    sens = pd.DataFrame(
        [
            {
                "gene_symbol": "SURF1",
                "cells_ran": 1,  # shipped (per-gene non-NaN) — must be ignored
                "cells_supporting": 1,
                "dominant_direction": "up",
                "log2fc_A": np.nan,
                "padj_A": np.nan,  # arm A carried but all-NaN across the frame
                "log2fc_C": 2.5,
                "padj_C": 1e-7,
                "max_abs_log2fc": 2.5,
            },
            {
                "gene_symbol": "SURF2",
                "cells_ran": 1,
                "cells_supporting": 1,
                "dominant_direction": "up",
                "log2fc_A": np.nan,
                "padj_A": np.nan,
                "log2fc_C": 2.0,
                "padj_C": 1e-6,
                "max_abs_log2fc": 2.0,
            },
        ]
    )
    out = rank_indication("SCLC", sens, _surface_df(), min_cells_supporting=2).set_index("gene_symbol")
    assert set(out.index) == {"SURF1", "SURF2"}  # survive: arms_ran=1 -> eff_min=1
    assert (out["cells_ran"] == 1).all()
    assert (out["cells_supporting"] == 1).all()
