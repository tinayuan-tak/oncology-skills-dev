"""AM#726 — Card 10 CPTAC protein-by-subtype read-path: `read_per_sample` hardening.

F9: `read_per_sample` must not launder EVERY FileNotFoundError into a fabricated
data_unavailable — a version-dependent 403-masquerade (missing s3:ListBucket) can surface as a
pyarrow FileNotFoundError for a key that actually EXISTS. The fix probes `get_file_info` before
trusting the FileNotFoundError as absence, mirroring `_ensure_derived_cached`'s discipline.

F10: `read_per_sample` is now `@lru_cache`'d on `target` — the pooled-baseline + per-stratum
fan-out in `build_protein_subtype_panorama` must not re-stream the same target's S3 predicate
read N+1 times per panorama.
"""

from __future__ import annotations

r = __import__("onc_methods.cptac_protein_deg.read", fromlist=["read"])


def test_read_per_sample_is_lru_cached():
    assert hasattr(r.read_per_sample, "cache_info")


def test_read_per_sample_dedupes_identical_target(monkeypatch):
    """A second identical-target call is a cache HIT — stops the panorama's pooled + per-stratum
    fan-out from re-issuing the same S3 predicate-pushdown read N+1 times."""
    import pandas as pd

    calls = {"n": 0}

    def fake_read_table(*args, **kwargs):
        calls["n"] += 1

        class _Tbl:
            def to_pandas(self_inner):
                return pd.DataFrame(columns=r._PER_SAMPLE_COLS)

        return _Tbl()

    monkeypatch.setattr("pyarrow.parquet.read_table", fake_read_table)
    r.read_per_sample.cache_clear()
    r.read_per_sample("EGFR")
    r.read_per_sample("EGFR")
    ci = r.read_per_sample.cache_info()
    assert ci.hits >= 1 and ci.misses >= 1, f"expected 1 miss + 1 hit, got {ci}"


def test_filenotfound_swallowed_only_when_probe_confirms_notfound(monkeypatch):
    """A FileNotFoundError raised by the pyarrow read is swallowed as data_unavailable ONLY when a
    direct get_file_info probe confirms the object is genuinely NotFound -- not on exception type
    alone (guards against the 403-masquerade)."""
    import pyarrow.fs as pafs

    r.read_per_sample.cache_clear()

    def raise_fnf(*args, **kwargs):
        raise FileNotFoundError("Path does not exist")

    monkeypatch.setattr("pyarrow.parquet.read_table", raise_fnf)

    class _Info:
        type = pafs.FileType.NotFound

    class _FakeFS:
        def get_file_info(self, uri):
            return _Info()

    monkeypatch.setattr(r, "_get_s3fs", lambda: _FakeFS())

    out = r.read_per_sample("EGFR")
    assert out.empty


def test_filenotfound_reraised_when_probe_shows_object_present(monkeypatch):
    """The 403-masquerade case: pyarrow raises FileNotFoundError but the object actually EXISTS
    (get_file_info reports File, not NotFound) -- must propagate, never fabricate absence."""
    import pyarrow.fs as pafs

    r.read_per_sample.cache_clear()

    def raise_fnf(*args, **kwargs):
        raise FileNotFoundError("Path does not exist")

    monkeypatch.setattr("pyarrow.parquet.read_table", raise_fnf)

    class _Info:
        type = pafs.FileType.File

    class _FakeFS:
        def get_file_info(self, uri):
            return _Info()

    monkeypatch.setattr(r, "_get_s3fs", lambda: _FakeFS())

    try:
        r.read_per_sample("EGFR2")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("expected the FileNotFoundError to propagate when the object is present")
