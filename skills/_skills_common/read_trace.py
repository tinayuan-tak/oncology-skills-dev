"""Opt-in per-card IO capture for the chain-audit dev tooling.

The declared card -> method -> product -> S3-object chain is spread across three repos and never
joined against what a run ACTUALLY read. A ``ReadTrace`` closes half that gap at runtime: for the
duration of a ``with trace.capture(card_id):`` block it records every data read a card's reader
performs -- the object opened, the columns requested, the row filter pushed down, and the rows/cols
that came back -- so the audit tool can diff *declared* wiring against *measured* IO.

Design (mirrors the ``plot_data_root`` opt-in in ``_resolve_one_card``):

* **Opt-in / byte-identical when off.** ``resolve_cards(..., trace=None)`` patches nothing; the read
  entry points are the originals. A ``ReadTrace`` patches them only inside ``with trace.installed():``
  and unconditionally restores them on exit (even on exception). So an untraced run is behaviorally
  identical to today.
* **Transparent wrappers.** Each patched function calls the original, returns its result unchanged,
  and records only metadata on the side. A read that raises propagates exactly as untraced; the event
  still records ``op`` + ``error`` so a card that failed mid-read is *measured*, not silently empty.
* **One event per logical read (re-entrancy guard).** ``pandas.read_parquet`` delegates to
  ``pyarrow.parquet.read_table``, and a columnar S3 read fans out into many internal ``GetObject``
  calls via s3fs. Recording every layer would double-count and flood the trace. A thread-local depth
  counter records only the OUTERMOST read of the read-family (read_table / read_parquet / read_csv)
  and suppresses everything nested inside it -- including nested ``GetObject``. A fetch that stands
  ALONE (a bare ``aws s3 cp`` or a direct ``get_object``) is at depth 0 and records.
* **Per-card, per-thread sink.** Events land in a ``threading.local`` list scoped by ``capture()``.
  ``resolve_cards`` forces the SEQUENTIAL read path under ``--trace`` (``SKILLS_READ_WORKERS=1``, the
  documented "exact former code path"), so each card's reads run start-to-finish on one thread and
  attribute unambiguously; the thread-local sink is belt-and-braces for any embedded caller.

Capture points, in priority order (see the plan's "design constraints"):

* ``pyarrow.parquet.read_table`` -- the highest-value point (105 call sites), the only one that also
  yields the pushed-down row ``filters`` and the requested ``columns``.
* ``pandas.read_parquet`` / ``pandas.read_csv`` -- the rest of the direct pandas reads.
* ``polars.read_parquet`` / ``polars.read_csv`` -- the pilot is migrating pandas -> polars, and polars
  reads through a native Rust reader (NOT pandas or pyarrow.parquet.read_table), so these are captured
  directly. ``polars.scan_parquet`` / ``scan_csv`` are LAZY: the object is recorded but rows/pushdown
  are left unmeasured (``lazy: true``) because the real IO fires at ``LazyFrame.collect()`` in native
  code no Python patch can observe.
* ``subprocess.run`` -- recorded ONLY when argv is an ``aws s3 …`` call (the ``aws s3 cp <uri> -``
  streaming family in ``methods/derived_product.py``); everything else passes through unrecorded.
* ``botocore`` ``get_object`` -- boto3 object fetches that are NOT nested inside a read-family call.

A URI-less buffer read (``pd.read_parquet(BytesIO(...))`` after an ``aws s3 cp``) records ``uri=None``
and is attributed to the most recent same-thread fetch event, labelled
``uri_attribution="preceding_fetch_same_thread"`` -- a heuristic that SAYS it is a heuristic, never an
assertion. If there is no preceding fetch it stays ``uri_attribution="none"``.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Any, Optional

# Event op labels (stable strings — the audit tool keys on these).
OP_READ_TABLE = "pyarrow.read_table"
OP_READ_PARQUET = "pandas.read_parquet"
OP_READ_CSV = "pandas.read_csv"
OP_PL_READ_PARQUET = "polars.read_parquet"
OP_PL_READ_CSV = "polars.read_csv"
OP_PL_SCAN_PARQUET = "polars.scan_parquet"
OP_PL_SCAN_CSV = "polars.scan_csv"
OP_AWS_CP = "subprocess.aws_s3"
OP_GET_OBJECT = "botocore.get_object"

# The EAGER read-family (a nested one of these is suppressed by the depth guard). polars' eager readers
# join it; the pilot is migrating pandas -> polars, and polars uses a native Rust reader (NOT pandas or
# pyarrow.parquet.read_table), so without these the tracer would go blind exactly as the migration lands.
_READ_FAMILY = (OP_READ_TABLE, OP_READ_PARQUET, OP_READ_CSV, OP_PL_READ_PARQUET, OP_PL_READ_CSV)
# LAZY scans (polars): record the object targeted; the actual IO + column/row pushdown happens later at
# LazyFrame.collect() through polars' own object-store — invisible to a Python-level patch — so rows are
# left unmeasured (null, never 0) and the event is marked lazy. Not depth-guarded: a scan does ~no IO.
_LAZY_SCAN_OPS = (OP_PL_SCAN_PARQUET, OP_PL_SCAN_CSV)
# ops that establish a URI on a thread, so a following URI-less buffer read can be attributed to them.
_FETCH_OPS = (OP_AWS_CP, OP_GET_OBJECT) + _READ_FAMILY


def _uri_of(path_or_buf: Any) -> Optional[str]:
    """Best-effort string URI from the first positional of a read. A file-like/buffer -> None (the
    URI-less family); a str/os.PathLike -> str. Never raises — an odd type just yields None."""
    if path_or_buf is None:
        return None
    if isinstance(path_or_buf, str):
        return path_or_buf
    try:
        import os

        if isinstance(path_or_buf, os.PathLike):
            return os.fspath(path_or_buf)
    except Exception:  # noqa: BLE001 — attribution is best-effort, never fatal
        pass
    return None


def _shape(result: Any) -> tuple[Optional[int], Optional[int]]:
    """(rows, cols) of a pyarrow Table or pandas DataFrame, else (None, None). Never raises."""
    try:
        num_rows = getattr(result, "num_rows", None)
        if num_rows is not None:  # pyarrow.Table
            ncols = getattr(result, "num_columns", None)
            return int(num_rows), (int(ncols) if ncols is not None else None)
        shape = getattr(result, "shape", None)
        if shape is not None and len(shape) == 2:  # pandas.DataFrame
            return int(shape[0]), int(shape[1])
    except Exception:  # noqa: BLE001
        pass
    return None, None


class ReadTrace:
    """Records data-read IO per card. Not reused across runs; create one per traced ``resolve_cards``.

    Usage::

        trace = ReadTrace()
        with trace.installed():
            for cid in card_ids:
                with trace.capture(cid):
                    read_live(cid, ...)
        trace.events_for(cid)  # -> list[dict]
    """

    def __init__(self) -> None:
        self._by_card: dict[str, list[dict]] = {}
        self._local = threading.local()
        self._install_depth = 0
        self._install_lock = threading.Lock()
        self._saved: dict[str, Any] = {}

    # ── sink management ──────────────────────────────────────────────────────
    @property
    def _sink(self) -> Optional[list]:
        return getattr(self._local, "sink", None)

    def _record(self, event: dict) -> None:
        sink = self._sink
        if sink is None:  # a read outside any capture() block — not attributable to a card, drop it
            return
        # attribute a URI-less buffer read to the preceding same-thread fetch (heuristic, labelled).
        if event.get("uri") is None and event["op"] not in (OP_AWS_CP, OP_GET_OBJECT):
            prior = next((e for e in reversed(sink) if e.get("uri") and e["op"] in _FETCH_OPS), None)
            if prior is not None:
                event["uri"] = prior["uri"]
                event["uri_attribution"] = "preceding_fetch_same_thread"
            else:
                event["uri_attribution"] = "none"
        sink.append(event)

    # ── re-entrancy depth (per thread) ───────────────────────────────────────
    def _suppressed(self) -> bool:
        """True when we are already inside an outer read-family call on this thread."""
        return getattr(self._local, "depth", 0) > 0

    def _enter_read(self) -> None:
        self._local.depth = getattr(self._local, "depth", 0) + 1

    def _exit_read(self) -> None:
        self._local.depth = getattr(self._local, "depth", 0) - 1

    @contextmanager
    def capture(self, card_id: str):
        """Scope the event sink to one card. Nested/re-entrant captures on the same thread are not
        expected (the sequential read path calls one card at a time); the inner sink wins and is
        restored on exit."""
        prev = getattr(self._local, "sink", None)
        sink: list[dict] = []
        self._local.sink = sink
        try:
            yield sink
        finally:
            self._local.sink = prev
            # last write wins if a card_id is captured twice (shouldn't happen on the sequential path)
            self._by_card[card_id] = sink

    def events_for(self, card_id: str) -> list[dict]:
        return list(self._by_card.get(card_id, []))

    def as_dict(self) -> dict[str, list[dict]]:
        return {cid: list(evs) for cid, evs in self._by_card.items()}

    # ── patch install / restore ──────────────────────────────────────────────
    @contextmanager
    def installed(self):
        """Patch the read entry points for the duration of the block, restoring the originals on exit
        (even on exception). Re-entrant: only the outermost block patches/restores."""
        with self._install_lock:
            first = self._install_depth == 0
            self._install_depth += 1
            if first:
                self._patch()
        try:
            yield self
        finally:
            with self._install_lock:
                self._install_depth -= 1
                if self._install_depth == 0:
                    self._unpatch()

    def _run_read(self, orig, op, uri, kwargs, args, kw):
        """Shared body for the read-family wrappers: suppress if nested, else record the OUTERMOST read
        (incrementing the depth so inner delegated reads / GetObjects are suppressed)."""
        if self._suppressed():
            return orig(*args, **kw)
        t0 = time.perf_counter()
        self._enter_read()
        try:
            result = orig(*args, **kw)
        except Exception as e:  # noqa: BLE001 — record then re-raise unchanged
            self._record(_mk(op, uri, kwargs, t0, error=e))
            raise
        finally:
            self._exit_read()
        rows, cols = _shape(result)
        self._record(_mk(op, uri, kwargs, t0, rows=rows, cols=cols))
        return result

    def _patch(self) -> None:
        self._saved = {}

        # pyarrow.parquet.read_table — the richest capture (filters + columns + num_rows).
        try:
            import pyarrow.parquet as _pq

            orig_rt = _pq.read_table
            self._saved["pq.read_table"] = (_pq, "read_table", orig_rt)

            def _traced_read_table(*args, **kwargs):
                uri = _uri_of(args[0] if args else kwargs.get("source"))
                return self._run_read(orig_rt, OP_READ_TABLE, uri, kwargs, args, kwargs)

            _pq.read_table = _traced_read_table
        except Exception:  # noqa: BLE001 — pyarrow absent/odd: skip this capture point, never fatal
            pass

        # pandas.read_parquet / read_csv.
        try:
            import pandas as _pd

            for fname, op in (("read_parquet", OP_READ_PARQUET), ("read_csv", OP_READ_CSV)):
                orig = getattr(_pd, fname)
                self._saved[f"pd.{fname}"] = (_pd, fname, orig)
                setattr(_pd, fname, self._make_pandas_wrapper(orig, op))
        except Exception:  # noqa: BLE001
            pass

        # polars — the pilot's target reader. Eager read_parquet/read_csv join the depth-guarded
        # read-family (full rows/cols capture). scan_parquet/scan_csv are LAZY: record the object only,
        # marked lazy with rows unmeasured (the read happens at .collect() in native code we can't see).
        try:
            import polars as _pl

            for fname, op in (("read_parquet", OP_PL_READ_PARQUET), ("read_csv", OP_PL_READ_CSV)):
                if hasattr(_pl, fname):
                    orig = getattr(_pl, fname)
                    self._saved[f"pl.{fname}"] = (_pl, fname, orig)
                    setattr(_pl, fname, self._make_pandas_wrapper(orig, op))
            for fname, op in (("scan_parquet", OP_PL_SCAN_PARQUET), ("scan_csv", OP_PL_SCAN_CSV)):
                if hasattr(_pl, fname):
                    orig = getattr(_pl, fname)
                    self._saved[f"pl.{fname}"] = (_pl, fname, orig)
                    setattr(_pl, fname, self._make_lazy_scan_wrapper(orig, op))
        except Exception:  # noqa: BLE001
            pass

        # subprocess.run — recorded ONLY for `aws s3 …` argv (and never when nested inside a read).
        try:
            import subprocess as _sp

            orig_run = _sp.run
            self._saved["sp.run"] = (_sp, "run", orig_run)

            def _traced_run(*args, **kwargs):
                argv = args[0] if args else kwargs.get("args")
                if self._suppressed() or not _is_aws_argv(argv):
                    return orig_run(*args, **kwargs)
                uri = _aws_s3_uri(argv)
                t0 = time.perf_counter()
                try:
                    result = orig_run(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    self._record(_mk(OP_AWS_CP, uri, {}, t0, error=e, argv=argv))
                    raise
                self._record(_mk(OP_AWS_CP, uri, {}, t0, argv=argv))
                return result

            _sp.run = _traced_run
        except Exception:  # noqa: BLE001
            pass

        # botocore GetObject (boto3 client method lives on the generated class). Suppressed when nested
        # inside a read-family call (s3fs fires many per read); a standalone fetch records.
        try:
            from botocore.client import BaseClient as _BC

            orig_api = _BC._make_api_call
            self._saved["bc._make_api_call"] = (_BC, "_make_api_call", orig_api)

            def _traced_api_call(self_client, operation_name, api_params):
                if operation_name != "GetObject" or self._suppressed():
                    return orig_api(self_client, operation_name, api_params)
                bucket = api_params.get("Bucket")
                key = api_params.get("Key")
                uri = f"s3://{bucket}/{key}" if bucket and key else None
                t0 = time.perf_counter()
                try:
                    result = orig_api(self_client, operation_name, api_params)
                except Exception as e:  # noqa: BLE001
                    self._record(_mk(OP_GET_OBJECT, uri, {}, t0, error=e))
                    raise
                self._record(_mk(OP_GET_OBJECT, uri, {}, t0))
                return result

            _BC._make_api_call = _traced_api_call
        except Exception:  # noqa: BLE001
            pass

    def _make_pandas_wrapper(self, orig, op):
        def _wrapper(*args, **kwargs):
            uri = _uri_of(
                args[0] if args else kwargs.get("filepath_or_buffer") or kwargs.get("source") or kwargs.get("path")
            )
            return self._run_read(orig, op, uri, kwargs, args, kwargs)

        return _wrapper

    def _make_lazy_scan_wrapper(self, orig, op):
        """A polars scan_* wrapper: record the object targeted (URI + declared columns) and mark it
        lazy with rows unmeasured — the actual read/pushdown fires later at LazyFrame.collect() in
        native code no Python patch can see. Never depth-guarded (a scan does ~no IO) and always passes
        the LazyFrame through unchanged."""

        def _wrapper(*args, **kwargs):
            uri = _uri_of(args[0] if args else kwargs.get("source"))
            t0 = time.perf_counter()
            try:
                result = orig(*args, **kwargs)
            except Exception as e:  # noqa: BLE001
                self._record(_mk(op, uri, kwargs, t0, error=e, lazy=True))
                raise
            self._record(_mk(op, uri, kwargs, t0, lazy=True))
            return result

        return _wrapper

    def _unpatch(self) -> None:
        for mod, attr, orig in self._saved.values():
            try:
                setattr(mod, attr, orig)
            except Exception:  # noqa: BLE001 — restore is best-effort; a failure must not mask the run
                pass
        self._saved = {}


def _mk(op, uri, kwargs, t0, *, rows=None, cols=None, error=None, argv=None, lazy=False) -> dict:
    """Build one trace event. `columns`/`filters` are lifted from a read's kwargs when present."""
    ev: dict[str, Any] = {
        "op": op,
        "uri": uri,
        "columns": _norm_columns(kwargs.get("columns")) if kwargs else None,
        "filters": _norm_filters(kwargs.get("filters")) if kwargs else None,
        "rows": rows,
        "cols": cols,
        "ms": round((time.perf_counter() - t0) * 1000.0, 3),
    }
    if lazy:
        # a lazy scan measures no rows here (pushdown/read deferred to .collect()); say so explicitly.
        ev["lazy"] = True
    if error is not None:
        ev["error"] = f"{type(error).__name__}: {error}"
    if argv is not None:
        ev["argv"] = [str(a) for a in argv] if isinstance(argv, (list, tuple)) else str(argv)
    return ev


def _norm_columns(cols) -> Optional[list]:
    if cols is None:
        return None
    try:
        return [str(c) for c in cols]
    except Exception:  # noqa: BLE001
        return None


def _norm_filters(filters) -> Optional[str]:
    """pyarrow filters are a list of (col, op, val) tuples or an Expression — repr() is stable enough
    for a hand-checkable log and always serialisable."""
    if filters is None:
        return None
    try:
        return repr(filters)
    except Exception:  # noqa: BLE001
        return "<unrepr-able filters>"


def _is_aws_argv(argv) -> bool:
    try:
        return bool(argv) and str(argv[0]).endswith("aws") and str(argv[1]) == "s3"
    except Exception:  # noqa: BLE001
        return False


def _aws_s3_uri(argv) -> Optional[str]:
    """First s3:// token in an `aws s3 …` argv, else None."""
    try:
        if not _is_aws_argv(argv):
            return None
        for tok in argv[2:]:
            s = str(tok)
            if s.startswith("s3://"):
                return s
    except Exception:  # noqa: BLE001
        pass
    return None
