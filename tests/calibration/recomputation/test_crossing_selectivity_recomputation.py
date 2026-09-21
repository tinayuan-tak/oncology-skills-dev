"""T3 recomputation anchors — tumor-vs-normal percentile-crossing selectivity.

Plan foamy-bird, Stage I / tier T3 (the ONLY tier that proves a NUMBER is right), sixth skill. Re-derives
the tumor-vs-normal-percentile-crossing card's headline fields — selectivity_class,
fraction_tumor_above_normal_p95/p99, distribution_overlap_tumor_normal, the normal p95/p99 cutoffs and the
sample counts — from the IRREPRODUCIBLE raw input (the per-sample tumor log2(TPM+1) vector and the
per-sample matched-normal GTEx vector) through the REAL
methods.tcga_gtex_expression_distribution.read.read_tumor_vs_normal_percentile_crossing pipeline. See
capture_crossing_selectivity_anchor.py for how an anchor is made.

Why this is not the green-for-the-wrong-reason trap the calibration snapshots fall into: a snapshot stores
a DERIVED value and asserts the code reproduces its own output — it can never catch a wrong computation.
Here the fixture is the raw per-SAMPLE log2(TPM+1) values; the fraction-above-normal-percentile is
re-computed against the normal p95/p99 cutoffs, the overlap is re-binned, and selectivity_class is
re-classified through the real _classify_percentile_crossing. The teeth below prove the assertions bite:
shift the tumor vector down and the p95-crossing fraction must fall; shift the NORMAL vector up (raising
its p95 bar) and the fraction must fall too — proving the matched-normal is the live comparator, not a
constant; empty the normal vector and the class must collapse to data_unavailable.

Anchors span the classifier's branches: APC-COADREAD (not_enriched), ERBB2/KLK3 (enriched_subset),
CEACAM5/EPCAM/FOLR1/MET/MSLN/TACSTD2 (strongly_tumor_enriched), DLL3-SCLC (data_unavailable — SCLC has no
matched GTEx normal). All ten are tumor-selectivity roster pairs carrying a percentile_crossing_class
headline, so every anchor's class is cross-checked against that independently-captured record.

OFFLINE — reads only committed fixtures, monkeypatches the two per-sample readers, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

# The pipeline module does absolute `from methods.…` imports at module scope, so the analysis-methods root
# must be importable. Insert it explicitly (the sibling tests/methods/… tests import the same way). We test
# the REAL card code — re-deriving through it is what makes T3 a real test, not a self-echo.
_AM_ROOT = HERE.parents[2]
if str(_AM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AM_ROOT))

import methods.tcga_gtex_expression_distribution.read as rd  # noqa: E402

MIN_ANCHORS = 8  # anti-vacuity floor below the current 10; a zeroed dir must never read as green
MIN_DISTINCT_CLASSES = 3  # the set must span classifier branches, not all sit in one
MIN_TUMOR_SAMPLES = 50  # a truncated tumor vector would collapse the distribution the fields summarize


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.percentile_crossing.json"))


def _load_anchor(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_vectors(anchor: dict) -> tuple[list[float], list[float]]:
    """(tumor_vector, normal_vector) for this anchor's (target, indication), read exactly as frozen — the
    irreproducible per-sample input slice."""
    table = pq.read_table(HERE / anchor["vectors_fixture"]).to_pydict()
    target, indication = anchor["target"], anchor["indication"]
    tumor: list[float] = []
    normal: list[float] = []
    for t, i, cohort, val in zip(table["target"], table["indication"], table["cohort"], table["log2_tpm"], strict=True):
        if t == target and i == indication:
            (tumor if cohort == "tumor" else normal).append(float(val))
    return tumor, normal


def _rederive(monkeypatch, tumor: list, normal: list, tissue, target: str, indication: str) -> dict:
    """Force the pipeline down the frozen-vector path. read_tumor_samples → the frozen tumor list;
    read_normal_samples → (frozen normal list, frozen tissue). Then call the REAL library entry point,
    which re-computes every field over those two vectors."""
    monkeypatch.setattr(rd, "read_tumor_samples", lambda t, i: list(tumor))
    monkeypatch.setattr(rd, "read_normal_samples", lambda t, i: (list(normal), tissue))
    return rd.read_tumor_vs_normal_percentile_crossing(target, indication)


ANCHOR_FILES = _anchor_files()
ANCHOR_PARAMS = [pytest.param(p, id=p.name.replace(".percentile_crossing.json", "")) for p in ANCHOR_FILES]
# Measured anchors only (selectivity_class != data_unavailable) — the teeth that move a numeric field are
# defined on the anchors that HAVE one.
MEASURED_PARAMS = [
    pytest.param(p, id=p.name.replace(".percentile_crossing.json", ""))
    for p in ANCHOR_FILES
    if _load_anchor(p)["expected_selectivity_class"] != "data_unavailable"
]


def test_anchor_set_is_not_vacuous():
    # A silently-empty anchor dir is indistinguishable from a passing suite — the trap this tier removes.
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} recomputation anchor(s), found {len(ANCHOR_FILES)} in {ANCHOR_DIR}"
    )
    classes = {_load_anchor(p)["expected_selectivity_class"] for p in ANCHOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classifier branches; found {sorted(classes)}"
    )


def test_fixture_md5_matches_anchors():
    # Every anchor pins the same source-slice md5; the committed parquet must still hash to it, or a
    # re-derivation is running against a different (possibly hand-edited) input than was captured.
    for path in ANCHOR_FILES:
        anchor = _load_anchor(path)
        fixture = HERE / anchor["vectors_fixture"]
        md5 = hashlib.md5(fixture.read_bytes()).hexdigest()
        assert md5 == anchor["_source"]["vectors_fixture_md5"], f"{path.name}: fixture md5 drift"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_vectors_are_full_not_truncated(anchor_path: Path):
    # The distribution fields summarize the WHOLE per-sample vectors; a truncated slice would silently
    # change every one of them. Assert the frozen vectors still hold the counts the anchor was captured over.
    anchor = _load_anchor(anchor_path)
    tumor, normal = _load_vectors(anchor)
    assert len(tumor) == anchor["n_tumor_samples"], "frozen tumor vector size drifted from captured n"
    assert len(normal) == anchor["n_normal_samples"], "frozen normal vector size drifted from captured n"
    assert len(tumor) >= MIN_TUMOR_SAMPLES, f"tumor vector too small ({len(tumor)}) — fixture truncated?"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_rederives_from_raw_samples(monkeypatch, anchor_path: Path):
    """The pinned class, fractions, cutoffs, overlap and counts must re-derive from the raw per-sample
    vectors via the REAL pipeline — exact float64 reproduction, not a stored echo."""
    anchor = _load_anchor(anchor_path)
    tumor, normal = _load_vectors(anchor)
    r = _rederive(monkeypatch, tumor, normal, anchor["matched_normal_tissue"], anchor["target"], anchor["indication"])

    assert r["selectivity_class"] == anchor["expected_selectivity_class"]
    assert r["n_tumor_samples"] == anchor["n_tumor_samples"]
    assert r["n_normal_samples"] == anchor["n_normal_samples"]
    assert r["matched_normal_tissue"] == anchor["matched_normal_tissue"]
    assert r["fraction_tumor_above_normal_p95"] == anchor["expected_fraction_tumor_above_normal_p95"]
    assert r["fraction_tumor_above_normal_p99"] == anchor["expected_fraction_tumor_above_normal_p99"]
    assert r.get("normal_p95_log2tpm") == anchor["expected_normal_p95_log2tpm"]
    assert r.get("normal_p99_log2tpm") == anchor["expected_normal_p99_log2tpm"]
    assert r["distribution_overlap_tumor_normal"] == anchor["expected_distribution_overlap_tumor_normal"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_agrees_with_roster_snapshot(anchor_path: Path):
    """Every anchor is a tumor-selectivity roster pair; its re-derived selectivity_class must equal that
    snapshot's independently-captured percentile_crossing_class — two records of the same categorical that
    must not diverge. An anchor the roster does not cover carries a null cross_ref and is skipped here."""
    anchor = _load_anchor(anchor_path)
    cross = anchor.get("snapshot_cross_ref")
    if cross is None:
        pytest.skip("pair not in the tumor-selectivity roster")
    assert cross["percentile_crossing_class"] == anchor["expected_selectivity_class"]


def test_at_least_one_roster_cross_ref_present():
    # test_agrees_with_roster_snapshot pytest.skips when a pair is not in the roster; guard against ALL of
    # them skipping (which would make that assertion vacuously green — the missing-sibling trap).
    assert any(_load_anchor(p).get("snapshot_cross_ref") for p in ANCHOR_FILES), (
        "no anchor carries a roster snapshot_cross_ref — the cross-repo assertion is vacuous"
    )


# ---------------------------------------------------------------------------
# Teeth: the assertions above must FAIL when the input moves. If they don't, the test is comparing a
# derived fixture to itself. Each mutation runs on a COPY of the frozen vectors.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_shifting_tumor_down_lowers_the_crossing_fraction(monkeypatch, anchor_path: Path):
    """Subtracting a large constant from every tumor sample (pushing the whole tumor vector below the
    matched-normal p95) must strictly LOWER the re-derived fraction-above-normal-p95 — proving the fraction
    is re-computed live over the tumor vector, not echoed from the pin."""
    anchor = _load_anchor(anchor_path)
    tumor, normal = _load_vectors(anchor)
    shifted = [v - 8.0 for v in tumor]
    r = _rederive(monkeypatch, shifted, normal, anchor["matched_normal_tissue"], anchor["target"], anchor["indication"])
    assert r["fraction_tumor_above_normal_p95"] < anchor["expected_fraction_tumor_above_normal_p95"]


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_raising_normal_lowers_the_crossing_fraction(monkeypatch, anchor_path: Path):
    """Adding a large constant to every NORMAL sample raises the matched-normal p95 bar, so strictly fewer
    tumors clear it — the re-derived fraction must strictly fall. This proves the matched-normal vector is
    the LIVE comparator (a wrong join or a constant cutoff would leave the fraction unmoved)."""
    anchor = _load_anchor(anchor_path)
    tumor, normal = _load_vectors(anchor)
    raised = [v + 8.0 for v in normal]
    r = _rederive(monkeypatch, tumor, raised, anchor["matched_normal_tissue"], anchor["target"], anchor["indication"])
    assert r["fraction_tumor_above_normal_p95"] < anchor["expected_fraction_tumor_above_normal_p95"]


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_emptying_normal_collapses_to_data_unavailable(monkeypatch, anchor_path: Path):
    """Removing the matched-normal vector entirely must collapse selectivity_class to data_unavailable —
    proving the tumor-vs-normal join is load-bearing for the class, not a decoration over a tumor-only
    statistic. Mirrors the DLL3-SCLC anchor, where the absence is real."""
    anchor = _load_anchor(anchor_path)
    tumor, _ = _load_vectors(anchor)
    r = _rederive(monkeypatch, tumor, [], anchor["matched_normal_tissue"], anchor["target"], anchor["indication"])
    assert r["selectivity_class"] == "data_unavailable"
    assert r["selectivity_class"] != anchor["expected_selectivity_class"]


@pytest.mark.parametrize("anchor_path", MEASURED_PARAMS)
def test_teeth_separating_the_distributions_lowers_overlap(monkeypatch, anchor_path: Path):
    """Pushing the tumor vector far above normal must strictly lower the distribution overlap toward zero —
    proving the overlap is re-binned live over both vectors. Guarded to anchors whose captured overlap is
    large enough that a strict decrease is unambiguous (a near-zero overlap can only stay near zero)."""
    anchor = _load_anchor(anchor_path)
    expected_overlap = anchor["expected_distribution_overlap_tumor_normal"]
    if expected_overlap is None or expected_overlap <= 0.05:
        pytest.skip("captured overlap too small for an unambiguous strict decrease")
    tumor, normal = _load_vectors(anchor)
    shifted = [v + 20.0 for v in tumor]
    r = _rederive(monkeypatch, shifted, normal, anchor["matched_normal_tissue"], anchor["target"], anchor["indication"])
    assert r["distribution_overlap_tumor_normal"] < expected_overlap
