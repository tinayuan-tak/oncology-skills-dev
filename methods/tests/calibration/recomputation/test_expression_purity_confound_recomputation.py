"""T3 recomputation anchors — expression-purity-confound card (#2046, batch D).

Plan foamy-bird, Stage I / tier T3. Re-derives purity_confound_class + the Pearson/Spearman stats
from the IRREPRODUCIBLE raw input (the per-sample [case, log2_tpm] tumor-expression rows + the
per-case ABSOLUTE purity, committed as lossless parquet) through the REAL
methods.expression_purity_confound.read.read_expression_purity_confound. See
capture_expression_purity_confound_anchor.py.

BOUNDARY: validates the read/join/correlation path (case-collapse -> purity join -> dropna ->
Pearson r(log2TPM, ABSOLUTE purity)/Spearman -> classify -> IQR power gate), NOT the upstream
recount3 / ABSOLUTE snapshot generation.

Why not the green-for-the-wrong-reason trap: the fixture is the raw INPUT; the expected numbers are
re-derived by the same reader the pipeline runs; the mutation tests prove teeth.

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

_AM_ROOT = HERE.parents[2]
if str(_AM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AM_ROOT))

import methods.expression_purity_confound.read as epc  # noqa: E402
import methods.tcga_gtex_expression_distribution.read as exprmod  # noqa: E402

MIN_ANCHORS = 2

ANCHOR_FILES = sorted(ANCHOR_DIR.glob("*.expression_purity_confound.json"))
ANCHOR_PARAMS = [pytest.param(p, id=p.name.replace(".expression_purity_confound.json", "")) for p in ANCHOR_FILES]


def _md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()  # noqa: S324 — fixture drift guard, not security


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _inputs(anchor: dict) -> tuple[pd.DataFrame, dict]:
    expr = pd.read_parquet(HERE / anchor["expr_fixture"])
    purity_tbl = pd.read_parquet(HERE / anchor["purity_fixture"])
    purity_by_case = dict(zip(purity_tbl["case"].tolist(), purity_tbl["purity"].tolist()))
    return expr, purity_by_case


def _rederive(anchor: dict, expr: pd.DataFrame, purity_by_case: dict) -> dict:
    with (
        mock.patch.object(epc, "ensure_aws_profile", lambda: None),
        mock.patch.object(exprmod, "read_tumor_samples_with_case", lambda t, i: expr),
        mock.patch.object(epc, "_load_purity_by_case", lambda: purity_by_case),
    ):
        return epc.read_expression_purity_confound(anchor["target"], anchor["indication"])


def test_anchor_set_is_not_vacuous():
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, f"expected >= {MIN_ANCHORS} purity anchors, found {len(ANCHOR_FILES)}"
    assert any("epcam" in p.name for p in ANCHOR_FILES), "the EPCAM flagship purity anchor is required and missing"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_fixture_md5_matches_anchor(anchor_path: Path):
    anchor = _load(anchor_path)
    assert _md5(HERE / anchor["expr_fixture"]) == anchor["expr_md5"], "expression rows drifted from pinned md5"
    assert _md5(HERE / anchor["purity_fixture"]) == anchor["purity_md5"], "purity rows drifted from pinned md5"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_rederives_from_raw_vectors(anchor_path: Path):
    anchor = _load(anchor_path)
    expr, purity_by_case = _inputs(anchor)
    summary = _rederive(anchor, expr, purity_by_case)
    for k, v in anchor["expected"].items():
        assert summary[k] == v, (
            f"{anchor['target']}/{anchor['indication']}: re-derived {k}={summary[k]!r} != pinned {v!r}"
        )


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_permuting_purity_breaks_the_correlation(anchor_path: Path):
    """Teeth: permuting the purity values across cases breaks the expression↔purity pairing, so the
    re-derived Pearson r must move off the pin — n_paired_samples unchanged (same cases, permuted
    purity)."""
    anchor = _load(anchor_path)
    expr, purity_by_case = _inputs(anchor)
    cases = list(purity_by_case)
    permuted = dict(zip(cases, list(purity_by_case.values())[::-1]))
    summary = _rederive(anchor, expr, permuted)
    assert summary["n_paired_samples"] == anchor["expected"]["n_paired_samples"]
    assert summary["expression_purity_pearson_r"] != anchor["expected"]["expression_purity_pearson_r"], (
        "permuting purity left the correlation unchanged (no teeth)"
    )


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_purity_tracking_expression_flips_to_tumor_intrinsic(anchor_path: Path):
    """Teeth: forcing purity to track expression exactly (a strong positive r) must flip the class to
    tumor_intrinsic — proving the classifier is a live function of the join, and the classifier's
    positive branch is reachable (both committed anchors read purity_independent)."""
    anchor = _load(anchor_path)
    expr, _ = _inputs(anchor)
    per_case = expr.groupby("case", as_index=False)["log2_tpm"].mean()
    # map each case's purity to a clipped monotone transform of its mean expression (rank-preserving,
    # strong positive correlation), clipped to a plausible purity band.
    lo, hi = per_case["log2_tpm"].min(), per_case["log2_tpm"].max()
    span = (hi - lo) or 1.0
    forced = {r.case: 0.2 + 0.6 * (r.log2_tpm - lo) / span for r in per_case.itertuples()}
    summary = _rederive(anchor, expr, forced)
    assert summary["purity_confound_class"] == "tumor_intrinsic"
    assert summary["purity_confound_class"] != anchor["expected"]["purity_confound_class"]
