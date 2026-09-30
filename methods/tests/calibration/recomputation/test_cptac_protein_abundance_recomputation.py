"""T3 recomputation anchors — tumor-protein-abundance-cptac (#2045, batch C).

Plan foamy-bird, Stage I / tier T3. tumor-protein-abundance-cptac is the per-INDICATION CPTAC protein
tumor-vs-normal card, produced by ``methods.cptac_protein_deg.read.read_target_summary(target,
indication)``. This re-derives the card summary from the IRREPRODUCIBLE raw input committed as lossless
parquet:
  - the target's raw per-cohort df rows (``{target}.cptac_target_rows.parquet``) — the substrate the
    indication->cohort resolution + representative-cohort pick + row->summary consume;
  - the matched cohort's all-gene ``protein_effect_size`` null
    (``{target}_{cohort}.cptac_allgene_effect_null.parquet``) — the WITHIN-cohort percentile denominator.

The offline re-derivation reconstructs the (df, cohort_gene_idx, gene_idx, cohort_effect_null) tuple
``_load_indexed`` returns (mirroring its own indexing exactly) and monkeypatches ONLY that S3-load
seam; the REAL ``read_target_summary`` then runs unmodified (indication->cohort resolution, the
representative-cohort pick on the comparable |Cohen's d| axis, ``_row_to_summary``,
``_standardized_effect``, ``_allgene_effect_percentile``).

Why this is not the green-for-the-wrong-reason trap: the fixtures are the raw INPUT (df rows + all-gene
null), the expected summary is re-derived by the same reader the framework runs, and the mutation tests
below prove the assertions have teeth.

BOUNDARY: validates the READ/AGGREGATION path, NOT the upstream MSstatsTMT DEG run (that provenance
belongs to data-catalog). WITHIN-COHORT SEMANTICS (#1512/#1664): CPTAC TMT effect sizes are pooled-
reference-relative RATIOS; every anchored indication is a LEAF -> a single cohort, so no cross-cohort
aggregation of non-comparable ratios occurs on this verdict-bearing path (that is confined to the
umbrella / indication-free paths, where #1664 F1 ranks on the comparable |Cohen's d| axis). The all-gene
percentile is a within-cohort rank.

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"


import onc_methods.cptac_protein_deg.read as cp

MIN_ANCHORS = 2
MIN_DISTINCT_CLASSES = 2

_CARD_FIELDS = (
    "cohort",
    "protein_expression_class",
    "protein_contrast_estimable",
    "protein_effect_size",
    "allgene_percentile",
    "allgene_percentile_class",
    "allgene_percentile_context",
    "protein_bh_q_value",
    "protein_p_value",
    "protein_median_log2_tumor",
    "protein_median_log2_normal",
    "n_tumor_samples",
    "n_normal_samples",
    "protein_effect_size_se",
    "protein_effect_standardized_t",
    "protein_effect_cohens_d",
    "protein_effect_standardized_class",
    "protein_effect_standardized_method",
    "stat_test_used",
    "method_version",
    "_data_source",
)


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.cptac_protein_abundance.json"))


def _rows_from_fixture(rel: str) -> list[dict]:
    return pq.read_table(HERE / rel).to_pylist()


def _null_from_fixture(rel: str) -> list:
    return pq.read_table(HERE / rel).column("protein_effect_size").to_pylist()


def _rederive_target_summary(
    target_rows: list[dict], matched_cohort: str, null_effects: list, target: str, indication: str
) -> dict:
    """Re-derive read_target_summary(target, indication) OFFLINE by reconstructing the (df,
    cohort_gene_idx, gene_idx, cohort_effect_null) tuple _load_indexed returns — from the frozen target
    rows + matched-cohort all-gene null — and monkeypatching ONLY that S3-load seam. Reconstruction
    mirrors _load_indexed's own indexing exactly (str().strip().upper() keys).

    IDENTICAL to the helper in capture_cptac_protein_abundance_anchor.py — the capture-time fidelity
    guard proves it reproduces the live read; this replays it against the same frozen bytes.
    """
    from unittest import mock

    import pandas as pd

    df = pd.DataFrame(target_rows)
    cohort_gene_idx: dict[tuple, int] = {}
    gene_idx: dict[str, list[int]] = {}
    cohort_col = df["cohort"].values
    gene_col = df["gene_symbol"].values
    for idx in range(len(df)):
        cohort = str(cohort_col[idx]).strip().upper()
        gene = str(gene_col[idx]).strip().upper()
        if not cohort or not gene:
            continue
        cohort_gene_idx[(cohort, gene)] = idx
        gene_idx.setdefault(gene, []).append(idx)
    cohort_effect_null = {matched_cohort.strip().upper(): list(null_effects)}
    with mock.patch.object(cp, "_load_indexed", lambda: (df, cohort_gene_idx, gene_idx, cohort_effect_null)):
        return cp.read_target_summary(target, indication)


pytestmark = pytest.mark.skipif(not _anchor_files(), reason="no cptac_protein_abundance anchors committed")


@pytest.mark.parametrize("anchor_path", _anchor_files(), ids=lambda p: p.stem)
def test_rederives_from_raw_substrate(anchor_path: Path):
    anchor = json.loads(anchor_path.read_text())
    rows = _rows_from_fixture(anchor["target_rows_fixture"])
    null = _null_from_fixture(anchor["allgene_effect_null_fixture"])
    summary = _rederive_target_summary(rows, anchor["matched_cohort"], null, anchor["target"], anchor["indication"])
    for f in _CARD_FIELDS:
        assert summary.get(f) == anchor["expected"][f], f"{anchor_path.stem}: {f} != anchor"


def test_fixture_md5_matches_anchors():
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        for fix_key, md5_key in (
            ("target_rows_fixture", "target_rows_fixture_md5"),
            ("allgene_effect_null_fixture", "allgene_effect_null_fixture_md5"),
        ):
            digest = hashlib.md5((HERE / anchor[fix_key]).read_bytes()).hexdigest()
            assert digest == anchor[md5_key], f"{anchor_path.stem}: {fix_key} md5 drift"


def test_anchor_set_is_not_vacuous():
    files = _anchor_files()
    assert len(files) >= MIN_ANCHORS, f"need >= {MIN_ANCHORS} anchors, found {len(files)}"
    classes = {json.loads(p.read_text())["expected"]["protein_expression_class"] for p in files}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchor set spans only {classes} protein_expression_class(es) — need >= {MIN_DISTINCT_CLASSES}"
    )


def test_teeth_unestimable_effect_collapses_to_data_unavailable():
    """Teeth: forcing the matched-cohort row's protein_effect_size to +Inf (MSstatsTMT's unestimable-
    contrast sentinel) must drive read_target_summary down the _unestimable_reason path — the re-derived
    class collapses to data_unavailable and the effect nulls — proving protein_expression_class /
    protein_effect_size are a live function of the frozen row, not echoed from the anchor."""
    moved = 0
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        if anchor["expected"]["protein_expression_class"] == "data_unavailable":
            continue
        rows = _rows_from_fixture(anchor["target_rows_fixture"])
        null = _null_from_fixture(anchor["allgene_effect_null_fixture"])
        mc = anchor["matched_cohort"].strip().upper()
        for r in rows:
            if str(r["cohort"]).strip().upper() == mc:
                r["protein_effect_size"] = math.inf
        summary = _rederive_target_summary(rows, anchor["matched_cohort"], null, anchor["target"], anchor["indication"])
        assert summary["protein_expression_class"] == "data_unavailable"
        assert summary["protein_expression_class"] != anchor["expected"]["protein_expression_class"]
        assert summary["protein_effect_size"] is None
        moved += 1
    assert moved >= 1, "teeth vacuous: no estimable anchor to perturb"


def test_teeth_shifting_the_allgene_null_moves_the_within_cohort_percentile():
    """Teeth: shifting the matched cohort's all-gene effect null far above the target's effect must move
    the WITHIN-cohort allgene_percentile — proving it is ranked live against the frozen null, not echoed.
    (A revert-verified different-input probe: the un-shifted null reproduces the anchor exactly, per
    test_rederives_from_raw_substrate.)"""
    moved = 0
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        if anchor["expected"]["allgene_percentile"] is None:
            continue
        rows = _rows_from_fixture(anchor["target_rows_fixture"])
        null = [float(v) + 1000.0 for v in _null_from_fixture(anchor["allgene_effect_null_fixture"])]
        summary = _rederive_target_summary(rows, anchor["matched_cohort"], null, anchor["target"], anchor["indication"])
        assert summary["allgene_percentile"] != anchor["expected"]["allgene_percentile"]
        moved += 1
    assert moved >= 1, "teeth vacuous: no anchor with a measured allgene_percentile to perturb"
