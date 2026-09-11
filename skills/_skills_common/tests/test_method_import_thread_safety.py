"""Guard: method-module imports are serialized across resolver worker threads.

WHY (2026-09-11): cards resolve on a ThreadPoolExecutor, and target-profile nests a second
pool over its 15 sub-skills, so several threads reach a FIRST `methods.*` import at once.
CPython's per-module import lock then raised
`_DeadlockError: deadlock detected by _ModuleLock('methods.depmap_common.loaders')` whenever
two threads held each other's in-flight module. The reader caught it and the card was emitted
`availability_state: read_error` — an operational failure that reads like a coverage gap in
every rollup. Four cards (14 interpretation rules) died on EVERY composed run this way,
reproducibly, across five targets and two release dates.

These tests assert the invariant that makes the cycle impossible — no two threads inside the
import — rather than trying to reproduce a timing-dependent deadlock. They deliberately do NOT
touch the analysis-methods repo, so they hold in a clone that has no sibling checkout.
"""

from __future__ import annotations

import builtins
import sys
import threading
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR.parent))  # skills/

from _skills_common import _live_readers as lr  # noqa: E402


def test_import_lock_is_reentrant():
    """RLock, not Lock — a method module's top-level imports re-enter on the SAME thread,
    which a plain Lock would self-deadlock on."""
    assert isinstance(lr._IMPORT_LOCK, type(threading.RLock()))
    with lr._IMPORT_LOCK:  # nested acquisition on one thread must not block
        with lr._IMPORT_LOCK:
            pass


def _held_by_another_thread() -> bool:
    """True if a DIFFERENT thread cannot take the lock right now."""
    out = {}

    def probe():
        got = lr._IMPORT_LOCK.acquire(blocking=False)
        out["blocked"] = not got
        if got:
            lr._IMPORT_LOCK.release()

    t = threading.Thread(target=probe)
    t.start()
    t.join()
    return out["blocked"]


def test_import_method_holds_the_lock_while_importing(monkeypatch):
    """The lock must cover the ACTUAL import, not just the sys.path mutation."""
    observed = {}

    def fake_import(name, *a, **kw):
        observed["name"] = name
        observed["locked_out"] = _held_by_another_thread()
        return object()

    monkeypatch.setattr(builtins, "__import__", fake_import)
    lr._import_method("depmap_chronos.cli")

    assert observed["name"] == "methods.depmap_chronos.cli"
    assert observed["locked_out"], "another thread could enter __import__ concurrently"


def test_import_data_catalog_lib_holds_the_lock(monkeypatch):
    """The data-catalog resolver import runs on the same worker threads and shares the lock."""
    observed = {}

    def fake_import(name, *a, **kw):
        observed["name"] = name
        observed["locked_out"] = _held_by_another_thread()
        return object()

    monkeypatch.setattr(builtins, "__import__", fake_import)
    lr._import_data_catalog_lib("target_id_resolver")

    assert observed["name"] == "target_id_resolver"
    assert observed["locked_out"]


def test_no_unlocked_methods_import_remains():
    """Every `methods.*` import in the reader must route through _import_method.

    A bare `from methods.x.y import z` inside a dispatcher bypasses the lock and reopens the
    deadlock — including when only the PARENT was pre-imported, because the submodule import
    still happens unlocked on the worker thread.
    """
    src = (SKILL_DIR / "_live_readers.py").read_text().splitlines()
    offenders = [
        (i + 1, line.strip())
        for i, line in enumerate(src)
        if line.lstrip().startswith(("from methods.", "import methods"))
    ]
    assert not offenders, f"unlocked methods imports: {offenders}"
