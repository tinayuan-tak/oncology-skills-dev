"""A missing indication must not be reported as a mutation frequency of zero.

Consumer report, 2026-09-16, against framework-run 2026-09-11-verdict-only-tables: "PIK3CA did not
pick up any hotspot mutations, which there definitely are."

The run's emitted table (PIK3CA-BRCA/subskills/genomic_alteration/tables/
mutation-hotspot-frequency_summary_stats.csv) said:

    overall_mutation_frequency,0.0
    n_samples_in_indication,          <- empty
    n_samples_mutated,0
    driver_recurrence_class,data_unavailable

PIK3CA is the most frequently mutated gene in breast cancer, so 0.0 is not a plausible measurement.
ROOT CAUSE, measured rather than inferred: the registered product tcga-mc3-hotspot-frequency-v1 held
exactly FOUR indications at the time of that run — COADREAD, GC, NSCLC, PAAD (700,775 rows; still
readable as the `hotspot_frequency.parquet.bak-4ind` sibling object) — and was expanded to 31
indications / 2,370,357 rows on 2026-09-13. BRCA was absent, so the pushdown on
(indication=BRCA, gene_symbol=PIK3CA) matched nothing and read_hotspot_summary's `num_rows == 0`
branch published a biological negative about a coverage gap. The `data_unavailable` recurrence class
sitting in the SAME row is the corroborating tell: the all-gene null for BRCA came back empty too,
which only happens when the indication has no rows at all.

Note what was NOT the cause, since an earlier draft of this fix assumed it: there was no stale local
cache involved. No `*_mc3_hotspots.parquet` exists anywhere on the host; `_read_product_table` went
straight to S3, and S3 genuinely lacked BRCA. That wrong hypothesis came from the card's own
`_data_source`, which named a local cache file — because `_data_source` is str(aggregate_path) on every
return path and aggregate_path is always the LOCAL path, whether or not it was read. A provenance field
whose value is fixed by construction reads as evidence while carrying none; `_data_source_kind` and the
last three tests in this file exist for that.

The consumer's specific row is now masked by the 2026-09-13 data refresh — PIK3CA/BRCA returns 69
rows today. The DEFECT is still live for any indication outside the product's coverage, and
JAK2/MPN reproduces it against today's product (0 rows for the indication). So these tests build
their own fixtures rather than depending on which indications the product happens to carry, which
would make them silently vacuous after the next refresh.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2].parent))

from methods.gdc_somatic_hotspot import read as hs  # noqa: E402

_SCHEMA = pa.schema(
    [
        ("indication", pa.string()),
        ("gene_symbol", pa.string()),
        ("n_samples_in_indication", pa.int64()),
        ("n_samples_mutated", pa.int64()),
        ("overall_mutation_frequency", pa.float64()),
        ("hotspot_protein_change", pa.string()),
        ("hotspot_n_samples", pa.int64()),
        ("hotspot_frequency", pa.float64()),
    ]
)


def _gene_rows(indication: str, gene: str, n_in_ind: int, n_mut: int):
    """One gene-summary row (null hotspot_protein_change) plus one hotspot row, matching the real
    product's shape (verified against the live schema on 2026-09-16)."""
    return [
        {
            "indication": indication,
            "gene_symbol": gene,
            "n_samples_in_indication": n_in_ind,
            "n_samples_mutated": n_mut,
            "overall_mutation_frequency": n_mut / n_in_ind,
            "hotspot_protein_change": None,
            "hotspot_n_samples": None,
            "hotspot_frequency": None,
        },
        {
            "indication": indication,
            "gene_symbol": gene,
            "n_samples_in_indication": n_in_ind,
            "n_samples_mutated": n_mut,
            "overall_mutation_frequency": n_mut / n_in_ind,
            "hotspot_protein_change": "H1047R",
            "hotspot_n_samples": n_mut,
            "hotspot_frequency": n_mut / n_in_ind,
        },
    ]


def _write(tmp_path: Path, rows) -> Path:
    out = tmp_path / "agg.parquet"
    pq.write_table(pa.Table.from_pylist(rows, schema=_SCHEMA), out)
    return out


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """GENIE and the pooled cohort are INDEPENDENT sources reached over the network; this file is
    about the MC3 branch only. Stub both, and clear the coverage/null lru_caches so a fixture from
    one test can never satisfy another (each test writes to its own tmp_path, but the caches are
    module-level and would outlive a path being reused)."""
    monkeypatch.setattr(hs, "_genie_recurrence_fields", lambda t, i: {"genie_driver_recurrence_class": "stubbed"})
    monkeypatch.setattr(hs, "_pooled_recurrence_fields", lambda t, i: {"pooled_driver_recurrence_class": "stubbed"})
    # Bind the REAL cached functions now: `monkeypatch` is torn down AFTER this fixture, so a test
    # that patches _indication_coverage would otherwise leave a plain lambda in place here and the
    # teardown would die on the missing .cache_clear. getattr-tolerant for the same reason in the
    # other direction: setup must not be the thing that fails, or a genuine behavioural regression
    # would surface as an ERROR in this fixture instead of as the assertion that names the defect.
    cached = [getattr(hs, n, None) for n in ("_indication_coverage", "_allgene_mutation_frequency_null")]
    clear = lambda: [f.cache_clear() for f in cached if hasattr(f, "cache_clear")]  # noqa: E731
    clear()
    yield
    clear()


# --------------------------------------------------------------------------------------------------
# 1. The regression: an uncovered indication is not a zero
# --------------------------------------------------------------------------------------------------


def test_a_gene_in_an_indication_the_aggregate_never_covered_is_not_reported_as_zero_percent(tmp_path):
    """The PIK3CA/BRCA shape exactly: the aggregate holds only the 4 indications the product held on
    2026-09-11, and BRCA is not among them."""
    agg = _write(tmp_path, sum([_gene_rows(ind, "KRAS", 500, 200) for ind in ("COADREAD", "GC", "NSCLC", "PAAD")], []))

    out = hs.read_hotspot_summary("PIK3CA", "BRCA", aggregate_path=agg)

    assert out["overall_mutation_frequency"] is None, (
        f"reported overall_mutation_frequency={out['overall_mutation_frequency']!r} for PIK3CA in BRCA "
        f"from an aggregate that contains no BRCA rows at all — a biological negative asserted on a "
        f"coverage gap. This is the consumer-reported defect."
    )
    assert out["n_samples_mutated"] is None, "a count of 0 mutated samples is the same false claim in integer form"
    assert out["driver_recurrence_class"] == "data_unavailable"
    assert out["_mc3_coverage"] == "uncovered"
    assert "never measured" in out["_data_note"], f"the note must say nothing was measured, got {out['_data_note']!r}"


def test_the_note_distinguishes_an_absent_indication_from_an_absent_product(tmp_path):
    """Two different operator actions. "The indication was never materialized" means run the producer
    for that indication; "no aggregate resolvable" means the product/manifest is missing entirely."""
    agg = _write(tmp_path, _gene_rows("COADREAD", "KRAS", 500, 200))
    uncovered = hs.read_hotspot_summary("PIK3CA", "BRCA", aggregate_path=agg)
    assert "is not present in the" in uncovered["_data_note"], "must name the indication as the thing missing"
    assert "no MC3 hotspot aggregate resolvable" not in uncovered["_data_note"], (
        "an indication missing FROM a readable product is being described as an unreadable product, "
        "which points the operator at the wrong remedy"
    )


# --------------------------------------------------------------------------------------------------
# 2. Do not over-correct: a genuine biological zero must survive
# --------------------------------------------------------------------------------------------------


def test_a_gene_absent_from_a_COVERED_indication_is_still_a_real_zero(tmp_path):
    """The over-correction guard, and the reason the fix needed a coverage probe rather than simply
    deleting the zero branch. BRCA IS in this aggregate; the queried gene is not. That is a genuine
    measured negative and must keep reporting 0.0."""
    agg = _write(tmp_path, _gene_rows("BRCA", "PIK3CA", 1026, 360))

    out = hs.read_hotspot_summary("GHOSTGENE", "BRCA", aggregate_path=agg)

    assert out["overall_mutation_frequency"] == 0.0, "a gene truly unmutated in a covered cohort is a real 0.0"
    assert out["n_samples_mutated"] == 0
    assert out["_mc3_coverage"] == "covered"


def test_the_real_zero_now_carries_the_denominator_it_is_a_zero_of(tmp_path):
    """The incoherent pair. Trunk emitted overall_mutation_frequency=0.0 beside
    n_samples_in_indication=None, so a reader could not tell a well-powered negative in 1026 samples
    from a coverage gap — the two are opposite conclusions. The cohort size is a property of the
    indication, not of the queried gene, so it is knowable even when the gene has no row.
    """
    agg = _write(tmp_path, _gene_rows("BRCA", "PIK3CA", 1026, 360))

    out = hs.read_hotspot_summary("GHOSTGENE", "BRCA", aggregate_path=agg)

    assert out["n_samples_in_indication"] == 1026, (
        f"a 0.0 frequency was emitted with n_samples_in_indication={out['n_samples_in_indication']!r}; "
        f"0 out of an unstated denominator is not an interpretable measurement"
    )


def test_a_populated_gene_is_unaffected(tmp_path):
    """The path the consumer's KRAS-COADREAD row took, kept byte-stable."""
    agg = _write(tmp_path, _gene_rows("COADREAD", "KRAS", 556, 235))

    out = hs.read_hotspot_summary("KRAS", "COADREAD", aggregate_path=agg)

    assert out["overall_mutation_frequency"] == pytest.approx(235 / 556)
    assert out["n_samples_in_indication"] == 556
    assert out["n_samples_mutated"] == 235
    assert [h["protein_change"] for h in out["hotspot_frequencies"]] == ["H1047R"]


# --------------------------------------------------------------------------------------------------
# 3. The coverage probe itself
# --------------------------------------------------------------------------------------------------


def test_the_coverage_probe_reports_unknown_rather_than_uncovered_when_no_source_resolves(tmp_path, monkeypatch):
    """ "I could not look" must not collapse into "I looked and found nothing".

    Those two license different downstream behaviour, and conflating them is precisely how a
    coverage gap gets rendered as a biological finding.
    """
    monkeypatch.setattr(hs, "_manifest_s3_path", lambda mid: None)
    status, n = hs._indication_coverage(str(tmp_path / "does-not-exist.parquet"), "BRCA")
    assert (status, n) == ("unknown", None)


def test_the_coverage_probe_finds_a_covered_indication_and_its_cohort_size(tmp_path):
    agg = _write(tmp_path, _gene_rows("BRCA", "PIK3CA", 1026, 360))
    assert hs._indication_coverage(str(agg), "BRCA") == ("covered", 1026)
    assert hs._indication_coverage(str(agg), "COADREAD") == ("uncovered", None)


def test_an_unresolvable_source_does_not_become_a_zero(tmp_path, monkeypatch):
    """The "unknown" status must route to data_unavailable too — reaching the zero branch with no
    readable source would be the original defect wearing a different hat."""
    agg = _write(tmp_path, _gene_rows("BRCA", "PIK3CA", 1026, 360))
    # The gene-level read succeeds and returns 0 rows, but the coverage probe cannot resolve anything.
    monkeypatch.setattr(hs, "_indication_coverage", lambda p, i: ("unknown", None))
    out = hs.read_hotspot_summary("GHOSTGENE", "BRCA", aggregate_path=agg)
    assert out["overall_mutation_frequency"] is None
    assert out["_mc3_coverage"] == "unknown"
    assert "no MC3 hotspot aggregate resolvable" in out["_data_note"]


def test_every_return_path_declares_its_coverage_status(tmp_path, monkeypatch):
    """A provenance key present on SOME paths is worse than absent on all of them.

    Caught in self-review of this very change: the first draft added _mc3_coverage only to the two
    branches it had touched, so a consumer reading it would hit a KeyError on the populated path and
    could not distinguish "not covered" from "this branch forgot to say". All four paths now declare
    it, and the values must be the ones the reader can act on.
    """
    agg = _write(tmp_path, _gene_rows("BRCA", "PIK3CA", 1026, 360))
    populated = hs.read_hotspot_summary("PIK3CA", "BRCA", aggregate_path=agg)
    real_zero = hs.read_hotspot_summary("GHOSTGENE", "BRCA", aggregate_path=agg)
    uncovered = hs.read_hotspot_summary("PIK3CA", "COADREAD", aggregate_path=agg)
    # `table is None`: no local file AND no manifest to fall back to.
    monkeypatch.setattr(hs, "_manifest_s3_path", lambda mid: None)
    no_source = hs.read_hotspot_summary("PIK3CA", "BRCA", aggregate_path=tmp_path / "nope.parquet")

    assert populated["_mc3_coverage"] == "covered"
    assert real_zero["_mc3_coverage"] == "covered"
    assert uncovered["_mc3_coverage"] == "uncovered"
    assert no_source["_mc3_coverage"] == "unknown"
    for name, row in (
        ("populated", populated),
        ("real_zero", real_zero),
        ("uncovered", uncovered),
        ("no_source", no_source),
    ):
        assert "_data_source_kind" in row, f"{name} path omits _data_source_kind"
        assert "_data_source" in row, (
            f"{name} path omits _data_source while its siblings emit it — a provenance key that "
            f"appears and vanishes by branch"
        )


# --------------------------------------------------------------------------------------------------
# 4. Provenance: _data_source names a path, not necessarily the thing that was read
# --------------------------------------------------------------------------------------------------


def test_a_card_served_from_the_registered_product_does_not_claim_a_local_file_as_its_source(tmp_path, monkeypatch):
    """The field that caused the misdiagnosis, pinned.

    `_data_source` is str(aggregate_path) on every return path, and aggregate_path is ALWAYS
    _resolve_aggregate_path()'s local cache path — the S3 key never leaves _read_product_table. So this
    state (no local file; rows served from the registered product) emitted a local
    *_mc3_hotspots.parquet filename as its provenance, indistinguishable from one actually read. The
    first investigation of the PIK3CA/BRCA zero read that filename and concluded a stale local cache was
    the cause. There was no such file on the host. _data_source_kind is what makes the two tellable
    apart, so assert the local path is still reported AND that it is no longer mistakable for a read.
    """
    absent_local = tmp_path / "brca_mc3_hotspots.parquet"
    served = pa.Table.from_pylist(_gene_rows("BRCA", "PIK3CA", 1026, 360), schema=_SCHEMA)
    monkeypatch.setattr(hs, "_manifest_s3_path", lambda mid: "bucket/hotspot_frequency.parquet")
    monkeypatch.setattr(hs, "_read_product_table", lambda p, m, **kw: served)

    out = hs.read_hotspot_summary("PIK3CA", "BRCA", aggregate_path=absent_local)

    assert out["overall_mutation_frequency"] == pytest.approx(360 / 1026), "fixture must serve real rows"
    assert not absent_local.exists(), "the premise of this test is that the local file does NOT exist"
    assert out["_data_source_kind"] == "registered_product", (
        f"a read served from the registered product reports _data_source={out['_data_source']!r} with "
        f"kind {out.get('_data_source_kind')!r}; on the evidence of _data_source alone a reader concludes "
        f"a local cache file was read, which is how this defect was misdiagnosed"
    )


def test_an_existing_local_cache_is_reported_as_a_local_cache(tmp_path):
    """The other side of the same discriminant — and the state the misdiagnosis ASSUMED. It must be
    distinguishable, not merely labelled."""
    agg = _write(tmp_path, _gene_rows("BRCA", "PIK3CA", 1026, 360))
    out = hs.read_hotspot_summary("PIK3CA", "BRCA", aggregate_path=agg)
    assert out["_data_source_kind"] == "local_cache"


def test_an_absent_s3_object_is_not_described_as_an_unresolved_manifest(tmp_path, monkeypatch):
    """A conjunctive note must not assert both halves on evidence for one.

    The unresolvable note said "neither local cache X nor the manifest/S3" on EVERY occurrence, but the
    ordinary case is a manifest that resolved perfectly and an S3 object that is missing. The two
    diagnoses have different remedies — republish the object vs fix the catalog entry — so the note has
    to name the half that actually failed.
    """
    monkeypatch.setattr(hs, "_manifest_s3_path", lambda mid: "bucket/gone.parquet")
    monkeypatch.setattr(hs, "_read_product_table", lambda p, m, **kw: None)

    out = hs.read_hotspot_summary("PIK3CA", "BRCA", aggregate_path=tmp_path / "nope.parquet")

    assert out["_data_source_kind"] == "registered_product"
    assert "manifest resolved but its S3 object is definitively absent" in out["_data_note"], (
        f"note does not name the object as the missing thing: {out['_data_note']!r}"
    )
    assert "resolved at all" not in out["_data_note"], (
        "the note claims the manifest never resolved, which sends the operator to the catalog instead "
        "of to the missing object"
    )


def test_a_genuinely_unresolvable_source_still_says_so(tmp_path, monkeypatch):
    """The other conjunct, so the branch above cannot swallow both cases."""
    monkeypatch.setattr(hs, "_manifest_s3_path", lambda mid: None)
    out = hs.read_hotspot_summary("PIK3CA", "BRCA", aggregate_path=tmp_path / "nope.parquet")
    assert out["_data_source_kind"] == "unresolvable"
    assert "resolved at all" in out["_data_note"]


def test_the_source_kind_mirrors_the_readers_own_local_first_order(tmp_path, monkeypatch):
    """_product_source_kind must agree with _read_product_table's precedence rather than guessing: when
    BOTH a local file and a manifest are available, the local file is what gets read."""
    agg = _write(tmp_path, _gene_rows("BRCA", "PIK3CA", 1026, 360))
    monkeypatch.setattr(hs, "_manifest_s3_path", lambda mid: "bucket/hotspot_frequency.parquet")
    assert hs._product_source_kind(agg) == "local_cache", "local-first order not mirrored"
    monkeypatch.setattr(hs, "_manifest_s3_path", lambda mid: None)
    assert hs._product_source_kind(tmp_path / "nope.parquet") == "unresolvable"
