"""HPA reader disk-latch + lru cache (perf Stage 3, 2026-07-23).

Previously _read_hpa re-downloaded + re-parsed the whole HPA master zip on EVERY call (no cache).
Now: a disk cache (download once/machine) + an lru_cache on the parsed default frame. Tests pin:
  - the explicit hpa_path OVERRIDE path still works + is NOT cached (tests/local files vary);
  - the override returns the expected columns;
  - the lru default read parses once (second call reuses) — mocked so no S3.
No live S3: the default S3 path is exercised via a monkeypatched _ensure_hpa_cached + a temp zip.
"""
from __future__ import annotations

import importlib
import sys
import zipfile
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

cli = importlib.import_module("methods.hpa_normal_tissue_liability.cli")


def _write_hpa_zip(tmp_path, rows):
    """Write a minimal HPA master TSV (the 4 columns the reader uses) into a zip."""
    cols = [cli.HPA_GENE_COL, cli.HPA_DIST_COL, cli.HPA_SPEC_COL, cli.HPA_INTENSITY_COL]
    df = pd.DataFrame(rows, columns=cols)
    tsv = df.to_csv(sep="\t", index=False)
    zpath = tmp_path / "proteinatlas.tsv.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("proteinatlas.tsv", tsv)
    return zpath


def test_override_path_reads_and_is_not_cached(tmp_path):
    z1 = _write_hpa_zip(tmp_path, [["KRAS", "Detected in all", "Low tissue specificity", ""]])
    df1 = cli._read_hpa(hpa_path=z1)
    assert list(df1.columns) == [cli.HPA_GENE_COL, cli.HPA_DIST_COL, cli.HPA_SPEC_COL, cli.HPA_INTENSITY_COL]
    assert df1.iloc[0][cli.HPA_GENE_COL] == "KRAS"
    # a DIFFERENT override path returns different data (override is not lru-cached)
    z2 = _write_hpa_zip(tmp_path / "d2" if (tmp_path / "d2").mkdir() or True else tmp_path,
                        [["EGFR", "Detected in many", "x", ""]])
    df2 = cli._read_hpa(hpa_path=z2)
    assert df2.iloc[0][cli.HPA_GENE_COL] == "EGFR"


def test_default_path_lru_parses_once(tmp_path, monkeypatch):
    # point the disk-cache at a temp zip; count how many times the zip is parsed
    z = _write_hpa_zip(tmp_path, [["KRAS", "Detected in all", "y", ""]])
    monkeypatch.setattr(cli, "_ensure_hpa_cached", lambda: z)
    cli._read_hpa_cached_default.cache_clear()
    calls = {"n": 0}
    orig = cli._read_zip_cols

    def _counting(zip_path, cols):
        calls["n"] += 1
        return orig(zip_path, cols)

    monkeypatch.setattr(cli, "_read_zip_cols", _counting)
    a = cli._read_hpa()   # cold -> parse
    b = cli._read_hpa()   # lru reuse -> no parse
    assert calls["n"] == 1, "default read must parse the zip only once (lru)"
    # returns a COPY (callers can mutate without corrupting the cached frame)
    a.loc[0, cli.HPA_GENE_COL] = "MUTATED"
    assert b.iloc[0][cli.HPA_GENE_COL] == "KRAS"
    cli._read_hpa_cached_default.cache_clear()


def test_ensure_hpa_cached_hits_existing_disk_file(tmp_path, monkeypatch):
    # if the cache zip already exists + nonempty, no S3 download is attempted
    monkeypatch.setattr(cli, "HPA_CACHE_DIR", tmp_path)
    z = tmp_path / "proteinatlas.tsv.zip"
    monkeypatch.setattr(cli, "HPA_CACHE_ZIP", z)
    _write_hpa_zip(tmp_path, [["KRAS", "Detected in all", "y", ""]])  # writes proteinatlas.tsv.zip
    def _boom(*a, **k):
        raise AssertionError("must not download when disk cache exists")
    monkeypatch.setattr(cli, "ensure_aws_profile", _boom)
    assert cli._ensure_hpa_cached() == z
