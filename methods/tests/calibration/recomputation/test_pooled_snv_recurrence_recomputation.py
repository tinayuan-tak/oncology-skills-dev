"""T3 recomputation anchors — pooled multi-cohort SNV driver-recurrence.

Plan foamy-bird, Stage I / tier T3: the ONLY tier that proves a NUMBER is right. It re-derives the
genomic-alteration-profile headline (pooled_mutation_frequency + pooled_driver_recurrence_percentile /
_class) from the IRREPRODUCIBLE raw input — the per-cohort {gene: (n_mut, n_cov)} slice, summed across
TCGA-MC3 (whole-exome) + AACR GENIE + MSK-CHORD (panels) — through the REAL
methods.pooled_snv_recurrence.read pipeline. See capture_pooled_snv_anchor.py for how an anchor is made.

Why this is not the green-for-the-wrong-reason trap the calibration snapshots fall into: a snapshot
stores a DERIVED value and asserts the code reproduces its own output — it can never catch a wrong
computation. Here the fixture is the raw per-cohort COUNTS, the pooled frequency is re-summed
(Σn_mut/Σn_cov) and the percentile is re-ranked by the same percentile_null the pipeline runs, and the
teeth below prove the assertion bites: inflate a count and the number must move; drop a cohort and the
JOIN must change the denominator; collapse the null and the percentile must shift. The fixture stores the
FULL per-cohort gene set (~20k rows), not just the anchor genes — the percentile is ranked against the
pooled null of every rankable gene (read.py:281-282), so a truncated fixture would BE the
comparator-collapse / wrong-denominator bug this tier exists to catch.

Anchors span the classifier's four branches in COADREAD: KRAS/APC/TP53 (top_1pct, the canonical CRC SNV
drivers), CTNNB1/ERBB2 (top_decile), KIT/IDH1 (mid), CD3D (bottom_decile — an immune-lineage marker,
NOT a CRC SNV driver, so the pipeline must NOT call it recurrent).

OFFLINE — reads only committed fixtures, monkeypatches the S3 cohort/product readers, no creds. Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

# The pipeline module does absolute `from onc_methods.…` imports at module scope; they resolve through
# the editable install from any cwd, so nothing has to be put on sys.path first and nothing rides on the
# suite's rootdir mechanism (skills#2237 deleted the insert this used to need). We test the REAL corpus
# code — re-deriving through it is what makes T3 a real test, not a self-echo.

import onc_methods.pooled_snv_recurrence.read as pr

MIN_ANCHORS = 6  # anti-vacuity floor below the current 8; a zeroed dir must never read as green
MIN_DISTINCT_CLASSES = 3  # the set must span classifier branches, not all sit in one
MIN_RANKED_GENES = 1000  # a truncated pooled null is the comparator-collapse bug

COHORT_OF_READER = {"_mc3_gene_counts": "TCGA-MC3", "_genie_gene_counts": "GENIE", "_msk_gene_counts": "MSK-CHORD"}


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.pooled_snv_recurrence.json"))


def _load_anchor(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_per_cohort(anchor: dict) -> dict[str, dict]:
    """{cohort: {gene: (n_mut, n_cov)}} exactly as captured — the irreproducible input slice."""
    table = pq.read_table(HERE / anchor["counts_fixture"]).to_pydict()
    out: dict[str, dict] = {}
    for cohort, gene, n_mut, n_cov in zip(
        table["cohort"], table["gene_symbol"], table["n_mut"], table["n_cov"], strict=True
    ):
        out.setdefault(cohort, {})[gene] = (int(n_mut), int(n_cov))
    return out


def _install(monkeypatch, per_cohort: dict[str, dict]) -> None:
    """Force the LIVE pooled path over the frozen counts — the same seam the sibling unit tests use
    (read.py builds the reader dict inside _pooled_for_indication precisely so it is monkeypatchable)."""
    monkeypatch.setattr(pr, "_pooled_from_product", lambda *a, **k: None)  # else it hits real S3
    monkeypatch.setattr(pr, "_mc3_gene_counts", lambda ind: dict(per_cohort.get("TCGA-MC3", {})))
    monkeypatch.setattr(pr, "_genie_gene_counts", lambda ind: dict(per_cohort.get("GENIE", {})))
    monkeypatch.setattr(pr, "_msk_gene_counts", lambda ind: dict(per_cohort.get("MSK-CHORD", {})))
    pr._pooled_for_indication.cache_clear()


def _rederive(monkeypatch, per_cohort: dict[str, dict], target: str, indication: str) -> dict:
    _install(monkeypatch, per_cohort)
    try:
        return pr.pooled_recurrence_for_gene(target, indication)
    finally:
        pr._pooled_for_indication.cache_clear()


ANCHOR_FILES = _anchor_files()
ANCHOR_PARAMS = [pytest.param(p, id=p.name.replace(".pooled_snv_recurrence.json", "")) for p in ANCHOR_FILES]


def test_anchor_set_is_not_vacuous():
    # A silently-empty anchor dir is indistinguishable from a passing suite — the trap this tier removes.
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} recomputation anchor(s), found {len(ANCHOR_FILES)} in {ANCHOR_DIR}"
    )
    classes = {_load_anchor(p)["expected_class"] for p in ANCHOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classifier branches; found {sorted(classes)}"
    )


def test_pooled_null_is_full_not_truncated():
    # The percentile is ranked against every rankable pooled gene; a truncated fixture would collapse
    # that comparator. Assert the frozen slice still yields a large rankable null.
    anchor = _load_anchor(ANCHOR_FILES[0])
    per_cohort = _load_per_cohort(anchor)
    pooled = pr.pool_gene_counts(per_cohort)
    rankable = [e for e in pooled.values() if e["n_cov"] >= pr._MIN_COVERED]
    assert len(rankable) >= MIN_RANKED_GENES, f"pooled null too small ({len(rankable)}) — fixture truncated?"
    assert len(rankable) == anchor["n_ranked_genes"], "rankable-null size drifted from the captured count"


def test_fixture_md5_matches_anchors():
    # Every anchor pins the same source-slice md5; the committed parquet must still hash to it, or a
    # re-derivation is running against a different (possibly hand-edited) input than was captured.
    for path in ANCHOR_FILES:
        anchor = _load_anchor(path)
        fixture = HERE / anchor["counts_fixture"]
        md5 = hashlib.md5(fixture.read_bytes()).hexdigest()
        assert md5 == anchor["_source"]["counts_fixture_md5"], f"{path.name}: fixture md5 drift"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_rederives_from_raw_counts(monkeypatch, anchor_path: Path):
    """The pinned frequency, percentile and class must re-derive from the raw per-cohort counts via the
    REAL pooled pipeline — exact float64 reproduction, not a stored echo."""
    anchor = _load_anchor(anchor_path)
    per_cohort = _load_per_cohort(anchor)
    r = _rederive(monkeypatch, per_cohort, anchor["target"], anchor["indication"])

    assert r["pooled_mutation_frequency"] == anchor["expected_pooled_freq"]
    assert r["pooled_driver_recurrence_percentile"] == anchor["expected_percentile"]
    assert r["pooled_driver_recurrence_class"] == anchor["expected_class"]
    assert r["n_mutated_pooled"] == anchor["n_mutated_pooled"]
    assert r["n_covered_pooled"] == anchor["n_covered_pooled"]
    assert r["n_ranked_genes"] == anchor["n_ranked_genes"]
    assert r["cohorts_contributing"] == anchor["cohorts_contributing"]
    # pooled_freq is exactly Σn_mut / Σn_cov over the frozen counts — the summed-counts/summed-coverage
    # denominator this tier exists to protect (never a mean of per-cohort frequencies).
    assert anchor["expected_pooled_freq"] == anchor["n_mutated_pooled"] / anchor["n_covered_pooled"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_agrees_with_shipped_product(anchor_path: Path):
    """The re-derived value must equal the value the shipped pooled-snv-recurrence product independently
    recorded — two records of the same number that must not diverge (captured via S3 pushdown)."""
    anchor = _load_anchor(anchor_path)
    cross = anchor["product_cross_ref"]
    assert cross["pooled_mutation_frequency"] == anchor["expected_pooled_freq"]
    assert cross["pooled_driver_recurrence_percentile"] == anchor["expected_percentile"]
    assert cross["pooled_driver_recurrence_class"] == anchor["expected_class"]


# ---------------------------------------------------------------------------
# Teeth: the assertions above must FAIL when the input moves. If they don't, the test is comparing a
# derived fixture to itself. Each mutation runs on a COPY of the frozen counts.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_inflating_the_target_moves_the_number(monkeypatch, anchor_path: Path):
    """Adding mutations to the target (raising Σn_mut, holding Σn_cov) must raise its pooled frequency
    and drive its percentile strictly up — proving re-derivation is live, not an echo of the pin."""
    anchor = _load_anchor(anchor_path)
    per_cohort = _load_per_cohort(anchor)
    target = anchor["target"]
    mutated = {c: dict(counts) for c, counts in per_cohort.items()}
    bumped = False
    for counts in mutated.values():
        if target in counts:
            n_mut, n_cov = counts[target]
            counts[target] = (n_cov, n_cov)  # saturate: every covered sample mutated in this cohort
            bumped = True
    assert bumped, f"{target} not present in any frozen cohort"
    r = _rederive(monkeypatch, mutated, target, anchor["indication"])
    # The frequency is recomputed from the mutated counts (Σn_mut/Σn_cov), so it must move strictly up —
    # this is the bite: an echo of the pinned value could not. The percentile can only rise or, for the
    # single highest-frequency gene (TP53) already at the rank-1 ceiling, hold; liveness of the ranking
    # itself is proven separately by the collapse-null tooth below.
    assert r["pooled_mutation_frequency"] > anchor["expected_pooled_freq"]
    assert r["pooled_driver_recurrence_percentile"] >= anchor["expected_percentile"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_dropping_a_cohort_changes_the_join(monkeypatch, anchor_path: Path):
    """Removing one contributing cohort must change the pooled denominator (the summed-coverage JOIN) —
    proving the multi-cohort sum is load-bearing. A single-cohort anchor (CD3D) becomes uncovered ⇒
    data_unavailable, which is the same JOIN made visible at its limit."""
    anchor = _load_anchor(anchor_path)
    per_cohort = _load_per_cohort(anchor)
    contributing = anchor["cohorts_contributing"]
    dropped = {c: counts for c, counts in per_cohort.items() if c != contributing[0]}
    r = _rederive(monkeypatch, dropped, anchor["target"], anchor["indication"])
    if len(contributing) == 1:
        assert r["pooled_driver_recurrence_class"] == "data_unavailable"
        assert r["n_covered_pooled"] in (0, None)
    else:
        assert r["n_covered_pooled"] != anchor["n_covered_pooled"]
        assert r["pooled_mutation_frequency"] != anchor["expected_pooled_freq"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_collapsing_the_null_moves_the_percentile(monkeypatch, anchor_path: Path):
    """Truncating the pooled null to just the target (a comparator collapse / wrong-reference-set bug)
    must move the re-derived percentile away from the pinned value — proving the full ~18k-gene
    reference set is load-bearing, not a self-echo. The frequency (a per-gene quantity) is unchanged;
    the percentile is not."""
    anchor = _load_anchor(anchor_path)
    per_cohort = _load_per_cohort(anchor)
    target = anchor["target"]
    only_target = {c: {target: counts[target]} for c, counts in per_cohort.items() if target in counts}
    r = _rederive(monkeypatch, only_target, target, anchor["indication"])
    # Frequency is intrinsic to the gene's own counts, so it must NOT move …
    if anchor["n_covered_pooled"] >= pr._MIN_COVERED:
        assert r["pooled_mutation_frequency"] == anchor["expected_pooled_freq"]
    # … but the percentile, ranked against a collapsed null, must.
    assert r["pooled_driver_recurrence_percentile"] != anchor["expected_percentile"]
