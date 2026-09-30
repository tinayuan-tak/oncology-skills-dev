"""build_tumor_rank._rank / build_depmap_rank._rank — the `is_floor_tie` artifact flag (#2328).

`rank(pct=True)` (default `method="average"`) assigns every gene tied at a cohort's floor median the
SAME percentile — a tie-CONSTANT, not a rank (the #2297 artifact). `is_floor_tie` must mark exactly
those rows: at the group's minimum median AND sharing it with >= 1 other gene. A gene that is merely
the UNIQUE lowest carries its own honest rank/percentile and must NOT be flagged.

Hermetic: `_rank()` is pure/in-memory (no S3, no parquet fixture) — the I/O split from `build()` is
itself part of this change, made specifically to give the tie logic a direct unit-test seam.
"""

from __future__ import annotations

import pandas as pd

from onc_methods.allgene_percentile_precompute import build_depmap_rank, build_tumor_rank

# ---- build_tumor_rank._rank ------------------------------------------------------------------


def _tumor_df(rows):
    # rows: list of (gene_symbol, ensembl_gene_id, source, group, median)
    return pd.DataFrame(rows, columns=["gene_symbol", "ensembl_gene_id", "source", "group", "median"])


def test_tumor_rank_flags_genuine_multi_gene_floor_tie():
    # Two genes tied at median=0.0 in the same (source, group) cohort -> both flagged.
    # MUTANT: `group_min_count > 1` -> `>= 1` reds this by ALSO flagging the unique-min case below.
    df = _tumor_df(
        [
            ("A", "ENSG_A", "tcga_tumor", "COAD", 0.0),
            ("B", "ENSG_B", "tcga_tumor", "COAD", 0.0),
            ("C", "ENSG_C", "tcga_tumor", "COAD", 5.0),
        ]
    )
    out = build_tumor_rank._rank(df)
    tied = out[out["gene_symbol"].isin(["A", "B"])]
    assert tied["is_floor_tie"].all()
    untied = out[out["gene_symbol"] == "C"]
    assert not untied["is_floor_tie"].any()
    # The tie constant: both tied genes get the SAME allgene_percentile (the artifact itself).
    assert tied["allgene_percentile"].nunique() == 1


def test_tumor_rank_does_not_flag_a_unique_lowest_value():
    # MUTANT: `is_group_min & (group_min_count > 1)` -> `is_group_min` alone reds this — a unique
    # lowest gene carries its own honest (non-tied) rank and must not be flagged.
    df = _tumor_df(
        [
            ("A", "ENSG_A", "tcga_tumor", "COAD", 0.0),
            ("B", "ENSG_B", "tcga_tumor", "COAD", 3.0),
            ("C", "ENSG_C", "tcga_tumor", "COAD", 5.0),
        ]
    )
    out = build_tumor_rank._rank(df)
    row_a = out[out["gene_symbol"] == "A"]
    assert not row_a["is_floor_tie"].any()


def test_tumor_rank_floor_tie_is_scoped_per_source_group_cohort():
    # A gene tied in one (source, group) cohort must NOT bleed the flag into a different cohort where
    # it is the unique minimum. MUTANT: computing the min/count over the whole frame (dropping the
    # groupby) reds this — COAD's B(0.0) would spuriously flag READ's B(0.0) as untied, or vice versa.
    df = _tumor_df(
        [
            ("A", "ENSG_A", "tcga_tumor", "COAD", 0.0),
            ("B", "ENSG_B", "tcga_tumor", "COAD", 0.0),
            ("A", "ENSG_A", "tcga_tumor", "READ", 0.0),
            ("C", "ENSG_C", "tcga_tumor", "READ", 9.0),
        ]
    )
    out = build_tumor_rank._rank(df)
    coad_a = out[(out["gene_symbol"] == "A") & (out["group"] == "COAD")]
    read_a = out[(out["gene_symbol"] == "A") & (out["group"] == "READ")]
    assert coad_a["is_floor_tie"].iloc[0] is True or bool(coad_a["is_floor_tie"].iloc[0])
    assert not bool(read_a["is_floor_tie"].iloc[0])  # unique minimum in READ, not tied


def test_tumor_rank_is_floor_tie_column_is_bool_dtype():
    df = _tumor_df([("A", "ENSG_A", "tcga_tumor", "COAD", 0.0), ("B", "ENSG_B", "tcga_tumor", "COAD", 0.0)])
    out = build_tumor_rank._rank(df)
    assert out["is_floor_tie"].dtype == bool


# ---- build_depmap_rank._rank -----------------------------------------------------------------


def _depmap_df(medians):
    return pd.DataFrame(
        {
            "gene_symbol": [f"G{i}" for i in range(len(medians))],
            "entrez_gene_id": [str(1000 + i) for i in range(len(medians))],
            "panel_median_log2tpm": medians,
        }
    )


def test_depmap_rank_flags_genuine_multi_gene_floor_tie():
    # MUTANT: `is_panel_min & (int(is_panel_min.sum()) > 1)` -> `is_panel_min` alone reds this — a
    # unique lowest gene would be wrongly flagged.
    out = build_depmap_rank._rank(_depmap_df([0.0, 0.0, 5.0, 9.0]))
    tied = out[out["panel_median_log2tpm"] == 0.0]
    assert tied["is_floor_tie"].all()
    untied = out[out["panel_median_log2tpm"] != 0.0]
    assert not untied["is_floor_tie"].any()
    assert tied["allgene_percentile"].nunique() == 1


def test_depmap_rank_does_not_flag_a_unique_lowest_value():
    out = build_depmap_rank._rank(_depmap_df([0.0, 3.0, 5.0, 9.0]))
    row = out[out["panel_median_log2tpm"] == 0.0]
    assert not row["is_floor_tie"].any()


def test_depmap_rank_is_floor_tie_column_is_bool_dtype():
    out = build_depmap_rank._rank(_depmap_df([0.0, 0.0, 5.0]))
    assert out["is_floor_tie"].dtype == bool
