"""T3 recomputation anchors — tumor-elevation-breadth (#2044, batch B).

Plan foamy-bird, Stage I / tier T3. tumor-elevation-breadth is a TWO-LAYER card; this re-derives
BOTH layers' roll-ups from the IRREPRODUCIBLE raw input, each committed as a lossless parquet:
  - PROTEIN (primary): the target's per-cohort CPTAC rows -> the REAL
    ``methods.cptac_protein_deg.read.read_tumor_elevation_breadth`` (monkeypatching ``read_all_cohorts``
    to the frozen rows).
  - RNA: the target's stacked pancan rows -> the REAL
    ``methods.dge_deseq2.derive_pancan_stack.read_rna_tumor_elevation_breadth`` (patching the S3 read
    to the frozen rows).

Why this is not the green-for-the-wrong-reason trap: the fixtures are the raw per-cohort / per-
indication INPUT rows, the expected roll-ups are re-derived by the same readers the framework runs,
and the mutation tests below prove the assertions have teeth.

BOUNDARY: validates the READ/AGGREGATION path (elevated-cohort counting + read-time pan-cohort BH/FDR
on the protein layer; composite-indication dedupe + K-of-N roll-up on the RNA layer), NOT the upstream
DEG/DESeq2 runs. #1663: no n-field is fabricated — only fields the readers emit are asserted.

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"


import onc_methods.cptac_protein_deg.read as cp
import onc_methods.dge_deseq2.derive_pancan_stack as ps

MIN_ANCHORS = 2
MIN_DISTINCT_CLASSES = 2

_PROTEIN_FIELDS = (
    "tumor_elevation_breadth_class",
    "n_cohorts_tested",
    "n_cohorts_elevated",
    "n_cohorts_sig_up_effect_negligible",
    "n_cohorts_sig_up_pan_cohort_fdr_fail",
    "fraction_elevated",
    "median_effect_across_elevated",
    "median_standardized_effect_across_elevated",
    "most_elevated_cohorts",
    "cohorts_tested",
    "cohorts_unestimable",
)
_RNA_FIELDS = (
    "rna_tumor_elevation_breadth_class",
    "n_indications_tested",
    "n_indications_elevated",
    "fraction_elevated",
    "median_max_log2fc_across_elevated",
    "most_elevated_indications",
    "indications_tested",
)


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.tumor_elevation_breadth.json"))


def _rows_from_fixture(rel: str) -> list[dict]:
    return pq.read_table(HERE / rel).to_pylist()


def _rederive_protein(cohort_rows: list[dict]) -> dict:
    with mock.patch.object(cp, "read_all_cohorts", lambda t: [dict(r) for r in cohort_rows]):
        return cp.read_tumor_elevation_breadth("FROZEN")


def _rederive_rna(rna_rows: list[dict]) -> dict:
    import pyarrow.fs as pafs

    frozen = pa.Table.from_pylist(rna_rows)

    def _fake_read_table(*_a, **_k):
        return frozen

    ps.read_rna_tumor_elevation_breadth.cache_clear()
    with (
        mock.patch.object(pafs, "S3FileSystem", lambda *a, **k: None),
        mock.patch("pyarrow.parquet.read_table", _fake_read_table),
    ):
        try:
            return ps.read_rna_tumor_elevation_breadth("FROZEN")
        finally:
            ps.read_rna_tumor_elevation_breadth.cache_clear()


pytestmark = pytest.mark.skipif(not _anchor_files(), reason="no tumor_elevation_breadth anchors committed")


@pytest.mark.parametrize("anchor_path", _anchor_files(), ids=lambda p: p.stem)
def test_protein_layer_rederives_from_raw_cohort_rows(anchor_path: Path):
    anchor = json.loads(anchor_path.read_text())
    cohort_rows = _rows_from_fixture(anchor["cptac_cohort_rows_fixture"])
    summary = _rederive_protein(cohort_rows)
    for f in _PROTEIN_FIELDS:
        assert summary[f] == anchor["expected_protein"][f], f"{anchor_path.stem}: protein {f} != anchor"


@pytest.mark.parametrize("anchor_path", _anchor_files(), ids=lambda p: p.stem)
def test_rna_layer_rederives_from_raw_stack_rows(anchor_path: Path):
    anchor = json.loads(anchor_path.read_text())
    rna_rows = _rows_from_fixture(anchor["rna_stack_rows_fixture"])
    summary = _rederive_rna(rna_rows)
    for f in _RNA_FIELDS:
        assert summary[f] == anchor["expected_rna"][f], f"{anchor_path.stem}: rna {f} != anchor"


def test_fixture_md5_matches_anchors():
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        for fix_key, md5_key in (
            ("cptac_cohort_rows_fixture", "cptac_cohort_rows_fixture_md5"),
            ("rna_stack_rows_fixture", "rna_stack_rows_fixture_md5"),
        ):
            digest = hashlib.md5((HERE / anchor[fix_key]).read_bytes()).hexdigest()
            assert digest == anchor[md5_key], f"{anchor_path.stem}: {fix_key} md5 drift"


def test_anchor_set_is_not_vacuous():
    files = _anchor_files()
    assert len(files) >= MIN_ANCHORS, f"need >= {MIN_ANCHORS} anchors, found {len(files)}"
    classes = {json.loads(p.read_text())["expected_protein"]["tumor_elevation_breadth_class"] for p in files}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchor set spans only {classes} protein breadth class(es) — need >= {MIN_DISTINCT_CLASSES}"
    )


def test_teeth_stripping_elevated_cohorts_collapses_protein_breadth():
    """Teeth (protein): demote every cohort's class to a non-elevated label and the re-derived
    breadth must collapse to not_tumor_elevated (n_cohorts_elevated -> 0)."""
    moved = 0
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        if anchor["expected_protein"]["n_cohorts_elevated"] == 0:
            continue
        cohort_rows = _rows_from_fixture(anchor["cptac_cohort_rows_fixture"])
        for r in cohort_rows:
            r["protein_expression_class"] = "unchanged"  # not in _ELEVATED_CLASSES
        summary = _rederive_protein(cohort_rows)
        assert summary["n_cohorts_elevated"] == 0
        assert summary["tumor_elevation_breadth_class"] == "not_tumor_elevated"
        moved += 1
    assert moved >= 1, "teeth vacuous: no anchor with an elevated cohort to perturb"


def test_teeth_flipping_rna_direction_collapses_rna_breadth():
    """Teeth (RNA): flip dominant_direction away from 'up' on every stacked row and the re-derived
    RNA breadth must collapse to not_tumor_elevated (n_indications_elevated -> 0)."""
    moved = 0
    for anchor_path in _anchor_files():
        anchor = json.loads(anchor_path.read_text())
        if anchor["expected_rna"]["n_indications_elevated"] == 0:
            continue
        rna_rows = _rows_from_fixture(anchor["rna_stack_rows_fixture"])
        for r in rna_rows:
            r["dominant_direction"] = "down"
        summary = _rederive_rna(rna_rows)
        assert summary["n_indications_elevated"] == 0
        assert summary["rna_tumor_elevation_breadth_class"] == "not_tumor_elevated"
        moved += 1
    assert moved >= 1, "teeth vacuous: no anchor with an elevated indication to perturb"
