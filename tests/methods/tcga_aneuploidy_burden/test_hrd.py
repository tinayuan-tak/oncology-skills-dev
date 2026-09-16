"""HRD genomic-scar score (hrd.py) + hrd_score_for_indication roll-up.

Unit-tests each scar component (HRD-LOH / LST / ntAI) against hand-constructed segment sets with
known counts, then the per-indication cohort roll-up with the S3 loaders mocked (no network).
Chromosome 1 (hg19: len 249.25 Mb, centromere 125 Mb) is used throughout so the geometry is explicit.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.tcga_aneuploidy_burden import hrd as h  # noqa: E402
from methods.tcga_aneuploidy_burden import read as r  # noqa: E402

CHR1_LEN = 249_250_621
CHR1_CEN = 125_000_000
MB = 1_000_000


def _seg(chrom, start, end, hscn1, hscn2, loh):
    return {
        "Chromosome": float(chrom),
        "Start": float(start),
        "End": float(end),
        "Length": float(end - start),
        "Modal_HSCN_1": hscn1,
        "Modal_HSCN_2": hscn2,
        "LOH": float(loh),
    }


# ---------------- HRD-LOH ----------------


def test_hrd_loh_counts_large_non_whole_chrom_loh():
    # A 20 Mb LOH region on chr1 p-arm (10-30 Mb): > 15 Mb, not whole-chromosome → counts 1.
    segs = [_seg(1, 10 * MB, 30 * MB, 1, 0, loh=1)]
    out = h.hrd_scars_for_sample(segs)
    assert out["hrd_loh"] == 1


def test_hrd_loh_excludes_whole_chromosome_loh():
    # LOH spanning the entire chromosome (0 → len) is mitotic missegregation, NOT an HR scar.
    segs = [_seg(1, 0, CHR1_LEN, 1, 0, loh=1)]
    out = h.hrd_scars_for_sample(segs)
    assert out["hrd_loh"] == 0


def test_hrd_loh_excludes_small_loh():
    # A 5 Mb LOH region (< 15 Mb) does not count.
    segs = [_seg(1, 10 * MB, 15 * MB, 1, 0, loh=1)]
    out = h.hrd_scars_for_sample(segs)
    assert out["hrd_loh"] == 0


# ---------------- ntAI (telomeric allelic imbalance) ----------------


def test_ntai_counts_telomeric_imbalance():
    # AI segment (hscn 2 vs 1) touching the p-telomere (start ~0), not crossing centromere → 1.
    segs = [_seg(1, 0, 40 * MB, 2, 1, loh=0)]
    out = h.hrd_scars_for_sample(segs)
    assert out["ntai"] == 1


def test_ntai_excludes_interstitial_imbalance():
    # AI segment in the middle of the p-arm (not touching a telomere) → 0.
    segs = [_seg(1, 40 * MB, 80 * MB, 2, 1, loh=0)]
    out = h.hrd_scars_for_sample(segs)
    assert out["ntai"] == 0


def test_ntai_excludes_balanced_segment():
    # Telomeric but allele-balanced (hscn 1 == 1) → not AI → 0.
    segs = [_seg(1, 0, 40 * MB, 1, 1, loh=0)]
    out = h.hrd_scars_for_sample(segs)
    assert out["ntai"] == 0


# ---------------- LST (large-scale state transitions) ----------------


def test_lst_counts_transition_between_large_segments():
    # Two adjacent >=10 Mb segments on the p-arm (both retained after 3 Mb smoothing) → 1 transition.
    segs = [
        _seg(1, 0, 60 * MB, 2, 2, loh=0),  # 60 Mb, p-arm
        _seg(1, 60 * MB, 120 * MB, 1, 1, loh=0),  # 60 Mb, p-arm (adjacent)
    ]
    out = h.hrd_scars_for_sample(segs)
    assert out["lst"] == 1


def test_lst_smoothing_drops_small_segments():
    # A 2 Mb segment (< 3 Mb) between two large ones is smoothed out; the two large flanks are then
    # adjacent → still 1 transition (not 2).
    segs = [
        _seg(1, 0, 60 * MB, 2, 2, loh=0),
        _seg(1, 60 * MB, 62 * MB, 3, 3, loh=0),  # 2 Mb — smoothed away
        _seg(1, 62 * MB, 120 * MB, 1, 1, loh=0),
    ]
    out = h.hrd_scars_for_sample(segs)
    assert out["lst"] == 1


def test_lst_not_counted_across_centromere():
    # A large p-arm segment and a large q-arm segment are on different arms — no cross-centromere LST.
    segs = [
        _seg(1, 0, 120 * MB, 2, 2, loh=0),  # p-arm (ends before centromere 125 Mb)
        _seg(1, 130 * MB, CHR1_LEN, 1, 1, loh=0),  # q-arm
    ]
    out = h.hrd_scars_for_sample(segs)
    assert out["lst"] == 0


# ---------------- score sum + X exclusion ----------------


def test_hrd_score_is_sum_of_three():
    segs = [
        _seg(1, 10 * MB, 30 * MB, 1, 0, loh=1),  # HRD-LOH +1 (also AI+telomeric? start 10Mb > slack → no ntAI)
        _seg(1, 0, 60 * MB, 2, 1, loh=0),  # ntAI +1 (telomeric AI)
        _seg(1, 60 * MB, 120 * MB, 1, 1, loh=0),  # + prior → LST +1
    ]
    out = h.hrd_scars_for_sample(segs)
    assert out["hrd_score"] == out["hrd_loh"] + out["lst"] + out["ntai"]
    assert out["hrd_score"] >= 1


def test_x_chromosome_excluded():
    # Chromosome 23 (X) segments must be ignored (sex/X-inactivation confound).
    segs = [_seg(23, 10 * MB, 40 * MB, 1, 0, loh=1)]
    out = h.hrd_scars_for_sample(segs)
    assert out["hrd_loh"] == 0 and out["hrd_score"] == 0


# ---------------- cohort roll-up (S3 mocked) ----------------


def _mock_segtabs(monkeypatch, seg_rows, cancer_map):
    # Force the LIVE segtabs computation: hrd_score_for_indication tries the per-indication product
    # first, so stub it absent (else this offline test would attempt a real S3 read of the product).
    monkeypatch.setattr(r, "_hrd_from_product", lambda *a, **k: None)
    r._load_absolute_segtabs.cache_clear()
    r._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(r, "_load_absolute_segtabs", lambda: pd.DataFrame(seg_rows))
    monkeypatch.setattr(r, "_load_sample_cancer_types", lambda: cancer_map)


def test_indication_rollup_scopes_and_classifies(monkeypatch):
    # 2 COAD samples, one HRD-high (many large LOH regions), one quiet; 1 LUAD excluded.
    rows = []
    # sample A (COAD): 45 large non-whole LOH regions spread across arms → score >> 42
    for i in range(45):
        s = 2 * i * MB + MB
        rows.append({**_seg(1 + (i % 22), s, s + 16 * MB, 1, 0, 1), "Sample": "TCGA-A6-0001-01"})
    # sample B (COAD): one small balanced segment → score 0
    rows.append({**_seg(1, 40 * MB, 45 * MB, 1, 1, 0), "Sample": "TCGA-A6-0002-01"})
    # sample C (LUAD): high, but must be excluded from COADREAD
    rows.append({**_seg(1, 10 * MB, 40 * MB, 1, 0, 1), "Sample": "TCGA-05-9999-01"})
    cancer = {"TCGA-A6-0001": "COAD", "TCGA-A6-0002": "COAD", "TCGA-05-9999": "LUAD"}
    _mock_segtabs(monkeypatch, rows, cancer)
    out = r.hrd_score_for_indication("COADREAD")
    assert out["n_samples"] == 2  # LUAD excluded
    assert out["n_hrd_high"] == 1  # only sample A clears 42
    assert out["hrd_class"] in ("hrd_enriched", "hrd_intermediate")


def test_indication_unavailable_no_mapping(monkeypatch):
    _mock_segtabs(monkeypatch, [], {})
    out = r.hrd_score_for_indication("NOT_A_REAL_INDICATION")
    assert out["hrd_class"] == "data_unavailable"
    assert out["n_samples"] == 0


def test_indication_unavailable_empty_segtabs(monkeypatch):
    monkeypatch.setattr(r, "_hrd_from_product", lambda *a, **k: None)  # force live path (see _mock_segtabs)
    r._load_absolute_segtabs.cache_clear()
    r._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(r, "_load_absolute_segtabs", lambda: pd.DataFrame())
    monkeypatch.setattr(r, "_load_sample_cancer_types", lambda: {"TCGA-A6-0001": "COAD"})
    out = r.hrd_score_for_indication("COADREAD")
    assert out["hrd_class"] == "data_unavailable"


# ---------------- the PRODUCT path's type reconstruction ----------------
#
# Every test above stubs _hrd_from_product out to force the LIVE path, so the product path's own
# contract was untested. That contract is a byte-identity claim: hrd_score_for_indication promises the
# summary is "byte-identical either way", and the product path can only honour it by rebuilding the
# EXACT python types the live path returns — parquet round-trips numpy scalars (np.float64, np.int64),
# and a numpy scalar serialises differently from a python float in the emitted card.


def _fake_product_table(rows):
    """A REAL pyarrow Table, so .to_pandas() yields genuine numpy scalars rather than python ones.
    Building this from a dict would defeat the test: the construction path IS the test here."""
    import pyarrow as pa

    return pa.Table.from_pandas(pd.DataFrame(rows), preserve_index=False)


def _mock_product(monkeypatch, rows):
    import pyarrow.fs
    import pyarrow.parquet

    monkeypatch.setattr(r, "s3_uri_for", lambda _pid: "s3://bucket/key.parquet")
    # S3FileSystem() is constructed inside the function and can try to resolve a region; neuter it.
    monkeypatch.setattr(pyarrow.fs, "S3FileSystem", lambda *a, **k: None)
    monkeypatch.setattr(pyarrow.parquet, "read_table", lambda *a, **k: _fake_product_table(rows))


_PRODUCT_ROW = {
    "indication": "BRCA",
    "hrd_class": "hrd_enriched",
    "hrd_high_fraction": 0.42,
    "n_hrd_high": 42,
    "median_hrd_score": 21.5,
    "p75_hrd_score": 33.0,
    "n_samples": 100,
    "hrd_context": "high scar burden",
    "method_version": "hrd-0.1.0",
    "_data_source": "gdc-pancanatlas-cnv-2018",
}


def test_product_path_returns_PLAIN_python_types_not_numpy_scalars(monkeypatch):
    """The property the byte-identity claim rests on, asserted on types rather than on values.

    A value test would pass against a summary full of np.float64: `np.float64(0.42) == 0.42` is True.
    So this checks `type(v) is float`, not equality — the numpy scalar is the failure mode that a
    value-based assertion cannot see.
    """
    _mock_product(monkeypatch, [_PRODUCT_ROW])
    out = r.hrd_score_for_indication("BRCA")
    assert out is not None and out["hrd_class"] == "hrd_enriched"
    expected = {
        "hrd_class": str,
        "hrd_high_fraction": float,
        "n_hrd_high": int,
        "median_hrd_score": float,
        "p75_hrd_score": float,
        "n_samples": int,
        "hrd_context": str,
        "method_version": str,
        "_data_source": str,
    }
    wrong = {k: type(out[k]).__name__ for k, t in expected.items() if type(out[k]) is not t}
    assert not wrong, f"product path leaked non-python types (numpy scalars serialise differently): {wrong}"


def test_product_path_nulls_the_nullable_numerics_instead_of_emitting_nan(monkeypatch):
    """A null median/p75/fraction in the product must come back None, never float nan.

    This is the absence guard the cell_absence adoption replaced (`pd.isna` -> `ca.is_missing`). It is
    asserted here on the REAL parquet round-trip rather than on the predicate alone, because the
    sentinel a missing cell arrives as is a property of the construction path, not of the guard.
    """
    row = dict(_PRODUCT_ROW, hrd_high_fraction=None, median_hrd_score=None, p75_hrd_score=None, hrd_context=None)
    _mock_product(monkeypatch, [row])
    out = r.hrd_score_for_indication("BRCA")
    for k in ("hrd_high_fraction", "median_hrd_score", "p75_hrd_score", "hrd_context"):
        assert out[k] is None, f"{k} came back {out[k]!r} ({type(out[k]).__name__}) rather than None"
    # the non-nullable counts are still real ints — absence there is NOT expected and not guarded
    assert type(out["n_samples"]) is int and type(out["n_hrd_high"]) is int
