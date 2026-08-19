"""The forked-process card-read pool (SKILLS_READ_POOL=process) must fork ONLY on the main thread.

Forking a MULTITHREADED process can deadlock (the child inherits copies of locks held by threads it
does not have). The composed target-profile fans its sub-skills out over a ThreadPoolExecutor and each
worker thread calls resolve_cards, so if SKILLS_READ_POOL=process were set globally those calls would
fork from a worker thread. _read_cards_process guards against this: it forks only when running on the
main thread, else transparently uses the thread pool. These tests pin BOTH arms of that guard without
actually forking (a fake process context stands in for the real fork pool)."""
from __future__ import annotations

import multiprocessing
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))  # skills/

import _skills_common as skc


class _FakePool:
    """Stand-in for a multiprocessing fork Pool — its .map tags each result 'PROC' so a test can tell
    the fork branch ran, without spawning a real process under pytest."""
    def __init__(self, processes=None):
        self.processes = processes

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def map(self, fn, args):
        return [f"PROC:{a[0]}" for a in args]


class _FakeCtx:
    def Pool(self, processes=None):
        return _FakePool(processes)


def _install_fakes(monkeypatch):
    """Fake the fork context (so no real fork) + tag the thread-pool fallback 'THREAD' so the two
    branches are distinguishable by their return values."""
    monkeypatch.setattr(multiprocessing, "get_context", lambda method: _FakeCtx())
    monkeypatch.setattr(
        skc, "_read_cards_threaded",
        lambda card_ids, target, indication, subgroup_context, max_workers, plot_data_root=None:
            [f"THREAD:{c}" for c in card_ids])


def test_forks_on_main_thread(monkeypatch):
    """On the main thread the fork pool engages (standalone skill run) — the documented
    SKILLS_READ_POOL=process fast path must NOT be silently downgraded to threads."""
    _install_fakes(monkeypatch)
    out = skc._read_cards_process(["a", "b"], "TGT", "IND", None, 8)
    assert out == ["PROC:a", "PROC:b"], "expected the fork pool on the main thread, got the thread fallback"


def test_falls_back_to_threads_off_main_thread(monkeypatch):
    """Off the main thread (the target-profile fan-out case) the guard forbids forking a live
    multithreaded process and delegates to the thread pool."""
    _install_fakes(monkeypatch)
    result = {}

    def _worker():
        result["out"] = skc._read_cards_process(["a", "b"], "TGT", "IND", None, 8)

    t = threading.Thread(target=_worker)
    t.start()
    t.join()
    assert result["out"] == ["THREAD:a", "THREAD:b"], (
        "off the main thread the fork pool must fall back to threads (fork-from-thread deadlock guard)")
