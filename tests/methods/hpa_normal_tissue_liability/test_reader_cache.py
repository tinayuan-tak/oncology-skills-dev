"""HPA reader disk-latch + lru cache (perf Stage 3, 2026-07-23; polars pilot 2026-09-16).

Previously _read_hpa re-downloaded + re-parsed the whole HPA master zip on EVERY call (no cache).
Now: a disk cache (download once/machine) + an lru_cache on the parsed default frame. Tests pin:
  - the explicit hpa_path OVERRIDE path still works + is NOT cached (tests/local files vary);
  - the override returns the expected columns;
  - the lru default read parses once (second call reuses) — mocked so no S3;
  - the cached frame cannot be corrupted by a caller (see below);
  - the gene index is invalidated TOGETHER with the frame it derives from.
No live S3: the default S3 path is exercised via a monkeypatched _ensure_hpa_cached + a temp zip.

WHY THE MUTATION TEST CHANGED SHAPE (polars pilot). Under pandas, _read_hpa returned
`cached.copy()` and this file proved the copy by MUTATING the result in place and asserting the
cached frame was unaffected. polars frames are immutable, so that mutation cannot be expressed —
and the copy it existed to prove is no longer needed. The guarantee is now pinned the other way
round: _read_hpa hands back the cached object ITSELF (no copy), and a derivation returns a NEW
frame while the cached one is untouched. That is strictly stronger than the old assertion, which
is why the check was rewritten rather than dropped.

Fixtures are built with plain string joins, NOT a dataframe library. The previous
`pd = pytest.importorskip("pandas")` meant that if pandas were absent these tests would SILENTLY
SKIP rather than fail — and skipping is not passing.
"""

from __future__ import annotations

import importlib
import sys
import zipfile
from pathlib import Path

import polars as pl
import pytest  # noqa: F401 — kept for fixtures/markers

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

cli = importlib.import_module("methods.hpa_normal_tissue_liability.cli")


def _write_hpa_zip(tmp_path, rows):
    """Write a minimal HPA master TSV (the 4 columns the reader uses) into a zip.
    Library-free on purpose — the fixture must not depend on the frame library under test."""
    cols = [cli.HPA_GENE_COL, cli.HPA_DIST_COL, cli.HPA_SPEC_COL, cli.HPA_INTENSITY_COL]
    lines = ["\t".join(cols)] + ["\t".join("" if c is None else str(c) for c in row) for row in rows]
    tsv = "\n".join(lines) + "\n"
    zpath = tmp_path / "proteinatlas.tsv.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("proteinatlas.tsv", tsv)
    return zpath


def test_override_path_reads_and_is_not_cached(tmp_path):
    z1 = _write_hpa_zip(tmp_path, [["KRAS", "Detected in all", "Low tissue specificity", ""]])
    df1 = cli._read_hpa(hpa_path=z1)
    assert list(df1.columns) == [cli.HPA_GENE_COL, cli.HPA_DIST_COL, cli.HPA_SPEC_COL, cli.HPA_INTENSITY_COL]
    assert df1.row(0, named=True)[cli.HPA_GENE_COL] == "KRAS"
    # a DIFFERENT override path returns different data (override is not lru-cached)
    z2 = _write_hpa_zip(
        tmp_path / "d2" if (tmp_path / "d2").mkdir() or True else tmp_path, [["EGFR", "Detected in many", "x", ""]]
    )
    df2 = cli._read_hpa(hpa_path=z2)
    assert df2.row(0, named=True)[cli.HPA_GENE_COL] == "EGFR"


def test_override_read_keeps_every_column_as_string(tmp_path):
    """infer_schema_length=0 must stand in for the old pandas dtype=str: NO column may be type-
    inferred, or a downstream `.strip()` / `.split(";")` hits an int and raises.

    The fixture is deliberately ALL-NUMERIC in every column, which is not what HPA ships — an
    earlier version of this test used realistic values ("KRAS", "Detected in all", "liver: 500"),
    none of which polars would infer as a number, so it passed even with infer_schema_length=0
    REMOVED. It asserted the reader's contract using data that could not violate it. This fixture
    can: drop infer_schema_length=0 and all four columns come back Int64."""
    z = _write_hpa_zip(tmp_path, [["7", "1", "2", "500"], ["8", "3", "4", "600"]])
    df = cli._read_hpa(hpa_path=z)
    assert set(df.dtypes) == {pl.String}, f"expected all-Utf8 (no inference), got {df.dtypes}"


def test_gene_lookup_is_case_and_whitespace_insensitive(tmp_path, monkeypatch):
    """The pandas reader compared `df[Gene].str.upper() == gene.strip().upper()` — case-folded on
    BOTH sides. The index must fold the same way on the DATA side, not just the query side.
    Untested before this pilot (the existing case test covers the distribution VALUE, not the
    symbol), so a data-side fold could have been dropped silently."""
    z = _write_hpa_zip(tmp_path, [["kras", "Not detected", "y", ""]])  # lowercase in the SOURCE
    monkeypatch.setattr(cli, "_ensure_hpa_cached", lambda: z)
    cli.clear_hpa_caches()
    for query in ("KRAS", "kras", "  KRAS  "):
        got = cli.load_and_classify(query)["normal_tissue_breadth_class"]
        assert got == "not_detected_in_normal", f"query {query!r} did not resolve (got {got})"
    cli.clear_hpa_caches()


def test_duplicate_gene_row_first_wins(tmp_path, monkeypatch):
    """A duplicate symbol must resolve to the FIRST row, preserving the pandas reader's
    `hit.iloc[0]` semantics exactly. HPA ships one row per gene so this is defensive, but the
    index build makes 'which duplicate wins' an explicit choice where the boolean mask made it
    implicit — so it gets pinned."""
    z = _write_hpa_zip(
        tmp_path,
        [
            ["KRAS", "Not detected", "y", ""],  # FIRST — must win
            ["KRAS", "Detected in all", "y", ""],  # would flip breadth if last-wins
        ],
    )
    monkeypatch.setattr(cli, "_ensure_hpa_cached", lambda: z)
    cli.clear_hpa_caches()
    assert cli.load_and_classify("KRAS")["normal_tissue_breadth_class"] == "not_detected_in_normal"
    cli.clear_hpa_caches()


def test_default_path_lru_parses_once(tmp_path, monkeypatch):
    # point the disk-cache at a temp zip; count how many times the zip is parsed
    z = _write_hpa_zip(tmp_path, [["KRAS", "Detected in all", "y", ""]])
    monkeypatch.setattr(cli, "_ensure_hpa_cached", lambda: z)
    cli.clear_hpa_caches()
    calls = {"n": 0}
    orig = cli._read_zip_cols

    def _counting(zip_path, cols):
        calls["n"] += 1
        return orig(zip_path, cols)

    monkeypatch.setattr(cli, "_read_zip_cols", _counting)
    a = cli._read_hpa()  # cold -> parse
    b = cli._read_hpa()  # lru reuse -> no parse
    assert calls["n"] == 1, "default read must parse the zip only once (lru)"
    # NO copy is made — the cached object itself is handed back (polars frames are immutable, so
    # the defensive copy the pandas reader paid per call is unnecessary).
    assert a is b, "lru read must return the cached frame itself, not a per-call copy"
    # and the cached frame cannot be corrupted: a derivation yields a NEW frame, original untouched
    derived = a.with_columns(pl.lit("MUTATED").alias(cli.HPA_GENE_COL))
    assert derived is not a
    assert derived.row(0, named=True)[cli.HPA_GENE_COL] == "MUTATED"
    assert b.row(0, named=True)[cli.HPA_GENE_COL] == "KRAS", "cached frame must be unaffected"
    cli.clear_hpa_caches()


def test_gene_index_is_invalidated_with_the_frame(tmp_path, monkeypatch):
    """The frame and the index derived from it are TWO caches. Clearing them together is the
    whole contract of clear_hpa_caches(); if only the frame were cleared, a repointed source
    would still resolve genes from the PREVIOUS zip and the test would pass on stale data."""
    z1 = _write_hpa_zip(tmp_path, [["KRAS", "Detected in all", "y", ""]])
    monkeypatch.setattr(cli, "_ensure_hpa_cached", lambda: z1)
    cli.clear_hpa_caches()
    assert cli.load_and_classify("KRAS")["normal_tissue_breadth_class"] == "broad_normal_expression"
    assert cli.load_and_classify("EGFR")["normal_tissue_breadth_class"] == "data_unavailable"

    d2 = tmp_path / "d2"
    d2.mkdir()
    z2 = _write_hpa_zip(d2, [["EGFR", "Not detected", "y", ""]])
    monkeypatch.setattr(cli, "_ensure_hpa_cached", lambda: z2)
    cli.clear_hpa_caches()
    # both caches dropped -> the NEW source decides both answers
    assert cli.load_and_classify("EGFR")["normal_tissue_breadth_class"] == "not_detected_in_normal"
    assert cli.load_and_classify("KRAS")["normal_tissue_breadth_class"] == "data_unavailable"
    cli.clear_hpa_caches()


def test_ensure_hpa_cached_hits_existing_disk_file(tmp_path, monkeypatch):
    # if the cache zip already exists + nonempty, no S3 client is constructed / download attempted
    monkeypatch.setattr(cli, "HPA_CACHE_DIR", tmp_path)
    z = tmp_path / "proteinatlas.tsv.zip"
    monkeypatch.setattr(cli, "HPA_CACHE_ZIP", z)
    _write_hpa_zip(tmp_path, [["KRAS", "Detected in all", "y", ""]])  # writes proteinatlas.tsv.zip

    def _boom(*a, **k):
        raise AssertionError("must not touch S3 when disk cache exists")

    monkeypatch.setattr(cli, "s3_client", _boom)
    assert cli._ensure_hpa_cached() == z


def test_download_is_atomic_and_routes_through_s3_client(tmp_path, monkeypatch):
    """AM#746 F10a: the download must land atomically — stream to a temp file, then rename — so an
    interrupted download can't leave a truncated size>0 zip that the exists()+st_size guard then
    serves as a corrupt cache hit (BadZipFile on every later call). Also pins AM#746 F3: the
    download goes through cli.s3_client (fallback-capable), not a bare boto3 client."""
    src_zip = _write_hpa_zip(tmp_path, [["KRAS", "Detected in all", "y", ""]])
    cache_dir = tmp_path / "cache"
    final = cache_dir / "proteinatlas.tsv.zip"
    monkeypatch.setattr(cli, "HPA_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cli, "HPA_CACHE_ZIP", final)

    seen = {"dest": None, "final_existed_mid_download": None}

    class _FakeClient:
        def download_file(self, bucket, key, dest):
            seen["dest"] = dest
            # while bytes are being written, the FINAL path must not yet exist (atomic rename)
            seen["final_existed_mid_download"] = final.exists()
            Path(dest).write_bytes(Path(src_zip).read_bytes())

    called = {"n": 0}

    def _fake_s3_client(*a, **k):
        called["n"] += 1
        return _FakeClient()

    monkeypatch.setattr(cli, "s3_client", _fake_s3_client)

    got = cli._ensure_hpa_cached()
    assert called["n"] == 1, "download must route through cli.s3_client (F3)"
    assert got == final and final.exists()
    assert seen["dest"] != str(final), "download must target a temp path, not the final zip (F10a)"
    assert seen["final_existed_mid_download"] is False, "final zip must appear only after atomic rename"
    assert not list(cache_dir.glob("*.tmp.*")), "temp file must be renamed away / cleaned up"


def test_reader_survives_off_cbg_profile_absent(tmp_path, monkeypatch):
    """AM#746 F3 regression: with AWS_PROFILE unset and the preferred `cbg` SSO profile absent
    (CI / prod / instance-role / OIDC), the reader must still download via s3_client()'s ambient
    credential-chain fallback — not raise ProfileNotFound → read.py's bare except → every target
    data_unavailable (the whole normal-tissue safety axis silently dark).

    Reaches the REAL production fallback in target_id_sidecar.s3_client: patches boto3.Session so a
    NAMED profile raises ProfileNotFound (as it would off-cbg) while a bare Session() succeeds and
    its client's download_file writes the fixture zip. Store-the-raw-input / re-derive: the fixture
    holds the raw HPA rows; the assertion re-derives the classification through load_and_classify.
    If _ensure_hpa_cached still used ensure_aws_profile() + a bare boto3.client('s3'), AWS_PROFILE
    would be forced to cbg and this would raise instead."""
    import boto3
    from botocore.exceptions import ProfileNotFound

    monkeypatch.delenv("AWS_PROFILE", raising=False)

    src_zip = _write_hpa_zip(tmp_path, [["KRAS", "Detected in all", "Low tissue specificity", ""]])

    class _FakeClient:
        def download_file(self, bucket, key, dest):
            Path(dest).write_bytes(Path(src_zip).read_bytes())

    class _FakeSession:
        def __init__(self, *a, profile_name=None, **k):
            if profile_name is not None:  # off-cbg: the named SSO profile does not exist
                raise ProfileNotFound(profile=profile_name)

        def client(self, *a, **k):
            return _FakeClient()

    monkeypatch.setattr(boto3, "Session", _FakeSession)

    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(cli, "HPA_CACHE_DIR", cache_dir)
    monkeypatch.setattr(cli, "HPA_CACHE_ZIP", cache_dir / "proteinatlas.tsv.zip")
    cli.clear_hpa_caches()

    out = cli.load_and_classify("KRAS")
    assert out["normal_tissue_breadth_class"] == "broad_normal_expression", (
        "reader must re-derive off-cbg, not go data_unavailable"
    )
    assert (cache_dir / "proteinatlas.tsv.zip").exists()
    assert not list(cache_dir.glob("*.tmp.*")), "atomic download must leave no temp file"
    cli.clear_hpa_caches()
