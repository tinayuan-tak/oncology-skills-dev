"""ReadTrace opt-in IO capture (2026-09-20, chain-audit dev tooling).

Hermetic — no live S3. Writes tiny local parquet/csv and asserts the tracer records the object,
columns, row filter and rows returned; that patches are RESTORED on exit (incl. on exception); that
a URI-less buffer read is attributed to the preceding same-thread fetch (a labelled heuristic); and
that resolve_cards(trace=...) surfaces provenance.datasets while trace=None stays byte-identical.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import _skills_common as skc  # noqa: E402
import _skills_common.read_trace as rt  # noqa: E402

# ── the wrappers record, and pass the result through unchanged ───────────────


def test_read_table_records_uri_columns_filters_rows(tmp_path):
    p = tmp_path / "t.parquet"
    pd.DataFrame({"gene_symbol": ["EGFR", "KRAS", "EGFR"], "tpm": [1.0, 2.0, 3.0]}).to_parquet(p)
    t = rt.ReadTrace()
    with t.installed(), t.capture("c1"):
        tbl = pq.read_table(str(p), columns=["tpm"], filters=[("gene_symbol", "=", "EGFR")])
    # result passed through unchanged
    assert tbl.num_columns == 1 and tbl.num_rows == 2
    (ev,) = t.events_for("c1")
    assert ev["op"] == rt.OP_READ_TABLE
    assert ev["uri"] == str(p)
    assert ev["columns"] == ["tpm"]
    assert "gene_symbol" in ev["filters"] and "EGFR" in ev["filters"]
    assert ev["rows"] == 2 and ev["cols"] == 1
    assert isinstance(ev["ms"], float)


def test_read_csv_and_read_parquet_record(tmp_path):
    csv = tmp_path / "x.csv"
    csv.write_text("a,b\n1,2\n3,4\n5,6\n")
    pqf = tmp_path / "x.parquet"
    pd.DataFrame({"a": [1, 2]}).to_parquet(pqf)
    t = rt.ReadTrace()
    with t.installed(), t.capture("c1"):
        d1 = pd.read_csv(csv)
        d2 = pd.read_parquet(pqf)
    assert list(d1.columns) == ["a", "b"] and len(d2) == 2  # results intact
    ops = [e["op"] for e in t.events_for("c1")]
    assert ops == [rt.OP_READ_CSV, rt.OP_READ_PARQUET]
    assert t.events_for("c1")[0]["rows"] == 3


def test_pandas_read_parquet_not_double_counted(tmp_path):
    """pd.read_parquet delegates to pyarrow.parquet.read_table; the depth guard must record ONE event
    (the outer pandas read), not two. This is the re-entrancy trap the guard exists to prevent."""
    pqf = tmp_path / "x.parquet"
    pd.DataFrame({"a": [1, 2, 3]}).to_parquet(pqf)
    t = rt.ReadTrace()
    with t.installed(), t.capture("c1"):
        pd.read_parquet(pqf)
    ops = [e["op"] for e in t.events_for("c1")]
    assert ops == [rt.OP_READ_PARQUET], ops  # NOT [read_parquet, read_table]


# ── polars (the pilot's migration target) ────────────────────────────────────


def test_polars_eager_read_parquet_records(tmp_path):
    pl = pytest.importorskip("polars")
    pqf = tmp_path / "p.parquet"
    pl.DataFrame({"g": ["EGFR", "KRAS"], "v": [1, 2]}).write_parquet(pqf)
    t = rt.ReadTrace()
    with t.installed(), t.capture("c1"):
        df = pl.read_parquet(pqf, columns=["v"])
    assert df.shape == (2, 1)  # result intact
    (ev,) = t.events_for("c1")
    assert ev["op"] == rt.OP_PL_READ_PARQUET
    assert ev["uri"] == str(pqf)
    assert ev["columns"] == ["v"]
    assert ev["rows"] == 2 and ev["cols"] == 1


def test_polars_scan_records_lazy_marker(tmp_path):
    """A lazy scan records the object but leaves rows UNMEASURED (null), marked lazy — the read fires
    at .collect() in native code the tracer cannot see. Unmeasured must read as null, never 0."""
    pl = pytest.importorskip("polars")
    pqf = tmp_path / "p.parquet"
    pl.DataFrame({"g": ["EGFR"], "v": [1]}).write_parquet(pqf)
    t = rt.ReadTrace()
    with t.installed(), t.capture("c1"):
        lf = pl.scan_parquet(pqf)
        _ = lf.collect()  # real IO — invisible to the tracer; no extra event expected
    scans = [e for e in t.events_for("c1") if e["op"] == rt.OP_PL_SCAN_PARQUET]
    assert len(scans) == 1
    assert scans[0]["uri"] == str(pqf)
    assert scans[0]["lazy"] is True
    assert scans[0]["rows"] is None  # NOT 0 — deferred, unmeasured


# ── restore discipline ───────────────────────────────────────────────────────


def test_patches_restored_on_normal_exit():
    orig_rt, orig_pq, orig_csv, orig_run = pq.read_table, pd.read_parquet, pd.read_csv, subprocess.run
    t = rt.ReadTrace()
    with t.installed():
        assert pq.read_table is not orig_rt  # patched inside
    assert pq.read_table is orig_rt
    assert pd.read_parquet is orig_pq
    assert pd.read_csv is orig_csv
    assert subprocess.run is orig_run


def test_patches_restored_on_exception():
    orig_rt = pq.read_table
    t = rt.ReadTrace()
    with pytest.raises(ValueError):
        with t.installed():
            raise ValueError("boom")
    assert pq.read_table is orig_rt  # restored despite the exception


def test_read_outside_capture_records_nothing(tmp_path):
    """A read while patched but OUTSIDE any capture() block is not attributable to a card → dropped."""
    csv = tmp_path / "x.csv"
    csv.write_text("a\n1\n")
    t = rt.ReadTrace()
    with t.installed():
        pd.read_csv(csv)  # no active capture
    assert t.as_dict() == {}


def test_failed_read_records_error_and_reraises():
    t = rt.ReadTrace()
    with t.installed(), t.capture("c1"):
        with pytest.raises(FileNotFoundError):
            pd.read_csv("/no/such/file/xyz.csv")
    (ev,) = t.events_for("c1")
    assert ev["op"] == rt.OP_READ_CSV
    assert ev.get("error") and "FileNotFoundError" in ev["error"]
    assert ev["rows"] is None


# ── URI attribution heuristic ────────────────────────────────────────────────


def test_uri_attribution_from_preceding_fetch(monkeypatch, tmp_path):
    """A URI-less buffer read after an `aws s3 cp` fetch is attributed to that fetch, labelled."""
    # Fake subprocess.run so no real aws binary is needed: the tracer patches subprocess.run to a
    # wrapper over the ORIGINAL, so we replace the original with a stub BEFORE installing the trace.
    calls = {}

    def fake_run(argv, *a, **k):
        calls["argv"] = argv
        return None

    monkeypatch.setattr(subprocess, "run", fake_run)
    pqf = tmp_path / "buf.parquet"
    pd.DataFrame({"a": [1, 2]}).to_parquet(pqf)
    buf = pqf.read_bytes()

    import io

    t = rt.ReadTrace()
    with t.installed(), t.capture("c1"):
        subprocess.run(["aws", "s3", "cp", "s3://bkt/key.parquet", "-"])
        pd.read_parquet(io.BytesIO(buf))  # URI-less
    evs = t.events_for("c1")
    assert [e["op"] for e in evs] == [rt.OP_AWS_CP, rt.OP_READ_PARQUET]
    assert evs[0]["uri"] == "s3://bkt/key.parquet"
    # the buffer read inherits the fetch's URI, and SAYS it was inferred
    assert evs[1]["uri"] == "s3://bkt/key.parquet"
    assert evs[1]["uri_attribution"] == "preceding_fetch_same_thread"


def test_non_aws_subprocess_not_recorded(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
    t = rt.ReadTrace()
    with t.installed(), t.capture("c1"):
        subprocess.run(["echo", "hello"])  # not aws s3 → passthrough, unrecorded
    assert t.events_for("c1") == []


# ── re-entrant install ───────────────────────────────────────────────────────


def test_installed_is_reentrant():
    orig = pq.read_table
    t = rt.ReadTrace()
    with t.installed():
        patched = pq.read_table
        with t.installed():
            assert pq.read_table is patched  # inner does not re-patch
        assert pq.read_table is patched  # inner exit does NOT restore (outer still active)
    assert pq.read_table is orig  # only the outermost restores


# ── resolve_cards integration ────────────────────────────────────────────────


def test_resolve_cards_trace_surfaces_datasets(monkeypatch, tmp_path):
    """resolve_cards(trace=...) captures the reader's IO and stamps provenance.datasets."""
    csv = tmp_path / "d.csv"
    csv.write_text("g,v\nEGFR,1\nEGFR,2\n")

    def fake_reader(cid, target, indication, **k):
        pd.read_csv(csv)  # a "reader" that performs one traced read
        return {"foo_class": "bar"}

    monkeypatch.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    monkeypatch.setattr(skc, "_import_dispatcher", lambda: fake_reader)
    monkeypatch.setattr(skc, "card_input_manifest_ids", lambda cid: ("m-1",))
    monkeypatch.setattr(skc, "card_declared_method_calls", lambda cid: ())

    trace = rt.ReadTrace()
    (card,) = skc.resolve_cards(["c-ok"], "EGFR", "PANCANCER", trace=trace)
    ds = card["provenance"]["datasets"]
    assert len(ds) == 1
    assert ds[0]["s3_uri"] == str(csv)
    assert ds[0]["rows_returned"] == 2
    assert ds[0]["op"] == rt.OP_READ_CSV
    # input_manifest_ids + method_calls still stamped alongside
    assert card["provenance"]["input_manifest_ids"] == ["m-1"]


def test_resolve_cards_without_trace_has_no_datasets_key(monkeypatch, tmp_path):
    """The positive control: trace=None ⇒ NO datasets key ⇒ byte-identical provenance to today."""
    csv = tmp_path / "d.csv"
    csv.write_text("g,v\nEGFR,1\n")

    def fake_reader(cid, target, indication, **k):
        pd.read_csv(csv)
        return {"foo_class": "bar"}

    monkeypatch.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    monkeypatch.setattr(skc, "_import_dispatcher", lambda: fake_reader)
    monkeypatch.setattr(skc, "card_input_manifest_ids", lambda cid: ("m-1",))
    monkeypatch.setattr(skc, "card_declared_method_calls", lambda cid: ())

    (card,) = skc.resolve_cards(["c-ok"], "EGFR", "PANCANCER")  # no trace
    assert "datasets" not in card["provenance"]
    # and the read entry points are unpatched (no lingering wrapper)
    assert pd.read_csv.__module__.startswith("pandas")
