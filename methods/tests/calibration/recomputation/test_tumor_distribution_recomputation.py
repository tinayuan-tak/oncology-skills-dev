"""T3 recomputation anchors — tumor-rna-distribution `tumor_expression_class` (#2043).

Plan foamy-bird, Stage I / tier T3. Re-derives the tumor-rna-distribution card's per-sample
distribution fields — tumor_expression_class, median/p95/p99/min/max_log2tpm, coefficient_of_variation,
distribution_pattern, detectable/moderate/high_fraction — from the IRREPRODUCIBLE raw input (the
per-sample tumor log2(TPM+1) vector) through the REAL
methods.tcga_gtex_expression_distribution.read.read_tumor_expression_distribution pipeline. See
capture_tumor_distribution_anchor.py for how an anchor is made — it REUSES the already-committed
percentile_crossing vectors_fixture (the same irreproducible tumor slice the tumor-vs-normal
selectivity anchors freeze) rather than minting a second copy, because the two cards' assemblers
both read through read_tumor_samples over the identical per-sample product.

Why this is not the green-for-the-wrong-reason trap: the fixture is the raw per-SAMPLE log2(TPM+1)
tumor vector; every distribution field is re-computed live from it and re-classified through the real
_classify_tumor_expression. The teeth below prove the assertions bite: pushing the whole vector above
the high cutoff must force broadly_high; silencing every sample must force broadly_low; emptying the
vector must collapse the class to data_unavailable.

OFFLINE — reads only committed fixtures, monkeypatches read_tumor_samples, no creds. Runs in CI.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"


import onc_methods.tcga_gtex_expression_distribution.read as rd

MIN_ANCHORS = 2  # anti-vacuity floor (EPCAM/COADREAD flagship + >=1 other panel target)
MIN_DISTINCT_CLASSES = 2
MIN_TUMOR_SAMPLES = 50


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.tumor_rna_distribution.json"))


def _load_anchor(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_tumor_vector(anchor: dict) -> list[float]:
    """The frozen tumor cohort rows of the (shared, already-committed) vectors_fixture — the exact
    slice read_tumor_samples would have returned for this (target, indication)."""
    table = pq.read_table(HERE / anchor["vectors_fixture"]).to_pydict()
    target, indication, cohort = anchor["target"], anchor["indication"], anchor["vectors_fixture_cohort"]
    out = []
    for t, i, c, val in zip(table["target"], table["indication"], table["cohort"], table["log2_tpm"], strict=True):
        if t == target and i == indication and c == cohort:
            out.append(float(val))
    return out


def _rederive(monkeypatch, tumor: list, target: str, indication: str) -> dict:
    monkeypatch.setattr(rd, "read_tumor_samples", lambda t, i: list(tumor))
    return rd.read_tumor_expression_distribution(target, indication)


def _anchor_id(path: Path) -> str:
    return path.name.replace(".tumor_rna_distribution.json", "")


ANCHOR_FILES = _anchor_files()
ANCHOR_PARAMS = [pytest.param(p, id=_anchor_id(p)) for p in ANCHOR_FILES]


def test_anchor_set_is_not_vacuous():
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} recomputation anchor(s), found {len(ANCHOR_FILES)} in {ANCHOR_DIR}"
    )
    classes = {_load_anchor(p)["expected_tumor_expression_class"] for p in ANCHOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classifier branches; found {sorted(classes)}"
    )
    assert any(_anchor_id(p) == "epcam_coadread" for p in ANCHOR_FILES), (
        "the EPCAM/COADREAD flagship anchor is required and missing"
    )


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_vector_is_full_not_truncated(anchor_path: Path):
    anchor = _load_anchor(anchor_path)
    tumor = _load_tumor_vector(anchor)
    assert len(tumor) == anchor["n_tumor_samples"], "frozen tumor vector size drifted from captured n"
    assert len(tumor) >= MIN_TUMOR_SAMPLES, f"tumor vector too small ({len(tumor)}) — fixture truncated?"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_rederives_from_raw_tumor_vector(monkeypatch, anchor_path: Path):
    """The pinned class + every distribution field must re-derive from the raw per-sample tumor
    vector via the REAL pipeline — exact float64 reproduction, not a stored echo."""
    anchor = _load_anchor(anchor_path)
    tumor = _load_tumor_vector(anchor)
    r = _rederive(monkeypatch, tumor, anchor["target"], anchor["indication"])

    assert r["tumor_expression_class"] == anchor["expected_tumor_expression_class"]
    assert r["n_tumor_samples"] == anchor["n_tumor_samples"]
    assert r["median_log2tpm"] == anchor["expected_median_log2tpm"]
    assert r["p95_log2tpm"] == anchor["expected_p95_log2tpm"]
    assert r["p99_log2tpm"] == anchor["expected_p99_log2tpm"]
    assert r["min_log2tpm"] == anchor["expected_min_log2tpm"]
    assert r["max_log2tpm"] == anchor["expected_max_log2tpm"]
    assert r["coefficient_of_variation"] == anchor["expected_coefficient_of_variation"]
    assert r["distribution_pattern"] == anchor["expected_distribution_pattern"]
    assert r["detectable_fraction"] == anchor["expected_detectable_fraction"]
    assert r["moderate_fraction"] == anchor["expected_moderate_fraction"]
    assert r["high_fraction"] == anchor["expected_high_fraction"]


# ---------------------------------------------------------------------------
# Teeth: the assertions above must FAIL when the input moves. Each mutation runs on a COPY.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_raising_every_sample_high_forces_broadly_high(monkeypatch, anchor_path: Path):
    """Pushing every tumor sample well above the high cutoff must drive high_fraction to 1.0 and the
    class to broadly_high — proving high_fraction is a live mean over the whole vector, not echoed
    from the pin. Guarded: skip if already broadly_high (no headroom)."""
    anchor = _load_anchor(anchor_path)
    if anchor["expected_tumor_expression_class"] == "broadly_high":
        pytest.skip("anchor already broadly_high — no headroom for this mutation")
    tumor = _load_tumor_vector(anchor)
    mutated = [10.0] * len(tumor)
    r = _rederive(monkeypatch, mutated, anchor["target"], anchor["indication"])
    assert r["high_fraction"] == 1.0
    assert r["high_fraction"] != anchor["expected_high_fraction"]
    assert r["tumor_expression_class"] == "broadly_high"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_silencing_every_sample_forces_broadly_low(monkeypatch, anchor_path: Path):
    """Dropping every tumor sample to zero must collapse detectable_fraction to 0.0 and the class to
    broadly_low — proving detectable_fraction is re-derived live, not a stored echo."""
    anchor = _load_anchor(anchor_path)
    tumor = _load_tumor_vector(anchor)
    mutated = [0.0] * len(tumor)
    r = _rederive(monkeypatch, mutated, anchor["target"], anchor["indication"])
    assert r["detectable_fraction"] == 0.0
    assert r["detectable_fraction"] != anchor["expected_detectable_fraction"]
    assert r["tumor_expression_class"] == "broadly_low"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_emptying_tumor_vector_collapses_to_data_unavailable(monkeypatch, anchor_path: Path):
    """Removing the tumor vector entirely must collapse tumor_expression_class to data_unavailable —
    proving the class is a live function of the tumor substrate, not a decoration over a constant."""
    anchor = _load_anchor(anchor_path)
    r = _rederive(monkeypatch, [], anchor["target"], anchor["indication"])
    assert r["tumor_expression_class"] == "data_unavailable"
    assert r["tumor_expression_class"] != anchor["expected_tumor_expression_class"]
