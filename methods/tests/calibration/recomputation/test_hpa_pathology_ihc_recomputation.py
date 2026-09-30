"""T3 recomputation anchors — hpa-pathology-cancer-ihc card (#2046, batch D).

Plan foamy-bird, Stage I / tier T3. Re-derives the HPA IHC presence summary from the IRREPRODUCIBLE
raw input (the per-cancer-type product rows for the gene, committed as lossless parquet) through the
REAL methods.hpa_pathology_cancer_ihc.read.read_target_summary. See
capture_hpa_pathology_ihc_anchor.py.

BOUNDARY (honest): read_target_summary is a LOOKUP, not an aggregation — the n_*/fraction/
protein_presence_class aggregation is precomputed upstream in data-catalog's
hpa-pathology-cancer-ihc-per-gene-v1 build (no aggregation arithmetic exists in analysis-methods).
So these anchors validate the read path this reader owns: OncoTree->HPA cancer-type resolution
(INDICATION_TO_HPA_CANCER), the gene predicate, the cancer_type row selection, the field projection,
and the absence-safety — NOT the upstream patient-count aggregation.

Teeth prove the selection + resolution are live functions of the substrate: dropping the resolved
cancer-type row collapses to data_unavailable, and an unmapped indication resolves to
data_unavailable.

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"


import onc_methods.hpa_pathology_cancer_ihc.read as hp

MIN_ANCHORS = 2

ANCHOR_FILES = sorted(ANCHOR_DIR.glob("*.hpa_pathology_cancer_ihc.json"))
ANCHOR_PARAMS = [pytest.param(p, id=p.name.replace(".hpa_pathology_cancer_ihc.json", "")) for p in ANCHOR_FILES]

_FIELDS = (
    "protein_presence_class",
    "fraction_detected",
    "fraction_moderate_strong",
    "staining_score",
    "n_high",
    "n_medium",
    "n_low",
    "n_not_detected",
    "n_patients_total",
    "prognostic_type",
    "prognostic_is_significant",
    "prognostic_p_value",
    "hpa_cancer_type",
)


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 — fixture drift guard, not security


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _base_table(anchor: dict) -> pa.Table:
    return pq.read_table(HERE / anchor["rows_fixture"])


def _replay_from_table(tbl: pa.Table):
    """A read_table replacement that serves an in-memory table through the reader's own
    gene predicate + column projection (mirrors the S3 pushdown)."""

    def _f(_uri, filesystem=None, columns=None, filters=None):  # noqa: ARG001
        t = tbl
        for col, _op, val in filters or []:
            t = t.filter(pc.equal(t[col], val))
        if columns:
            t = t.select([c for c in columns if c in t.column_names])
        return t

    return _f


def _rederive(anchor: dict, tbl: pa.Table) -> dict:
    with (
        mock.patch.object(hp, "_get_s3fs", lambda: None),
        mock.patch("pyarrow.parquet.read_table", _replay_from_table(tbl)),
    ):
        return hp.read_target_summary(anchor["target"], anchor["indication"])


def test_anchor_set_is_not_vacuous():
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, f"expected >= {MIN_ANCHORS} HPA IHC anchors, found {len(ANCHOR_FILES)}"
    assert any("epcam" in p.name for p in ANCHOR_FILES), "the EPCAM flagship HPA IHC anchor is required and missing"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_fixture_md5_matches_anchor(anchor_path: Path):
    anchor = _load(anchor_path)
    assert _md5(HERE / anchor["rows_fixture"]) == anchor["rows_md5"], "HPA rows drifted from the pinned md5"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_rederives_from_raw_rows(anchor_path: Path):
    anchor = _load(anchor_path)
    summary = _rederive(anchor, _base_table(anchor))
    for k, v in anchor["expected"].items():
        assert summary.get(k) == v, (
            f"{anchor['target']}/{anchor['indication']}: re-derived {k}={summary.get(k)!r} != pinned {v!r}"
        )


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_dropping_the_matched_cancer_type_row_yields_data_unavailable(anchor_path: Path):
    """Teeth: dropping the resolved HPA cancer-type row from the product rows collapses the read to
    data_unavailable — proving the cancer_type selection is a live function of the substrate."""
    anchor = _load(anchor_path)
    tbl = _base_table(anchor)
    matched = anchor["hpa_cancer_type"]
    kept = tbl.filter(pc.not_equal(tbl["cancer_type"], matched))
    summary = _rederive(anchor, kept)
    assert summary["protein_presence_class"] == "data_unavailable"
    assert summary["protein_presence_class"] != anchor["expected"]["protein_presence_class"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_unmapped_indication_yields_data_unavailable(anchor_path: Path):
    """Teeth: an indication with no HPA cancer-type mapping resolves to data_unavailable before any
    row is read — proving the OncoTree->HPA resolution is live, not echoed."""
    anchor = _load(anchor_path)
    with (
        mock.patch.object(hp, "_get_s3fs", lambda: None),
        mock.patch("pyarrow.parquet.read_table", _replay_from_table(_base_table(anchor))),
    ):
        summary = hp.read_target_summary(anchor["target"], "NOT_A_REAL_INDICATION")
    assert summary["protein_presence_class"] == "data_unavailable"
