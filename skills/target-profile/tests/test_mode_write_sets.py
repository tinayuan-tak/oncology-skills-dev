"""PR-2 — tp_emit single sink. Pins the per-mode artifact write-set (MODE_WRITE_SETS) so a run mode can
never silently gain or drop a dashboard/spine artifact. Pure logic (no S3/render)."""
from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_emit", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_load()                 # bootstraps scripts/ onto sys.path
import tp_emit          # noqa: E402


def _args(**kw):
    base = dict(emit="nomination", verdict_only=False, no_figures=False, ground=None, full_package=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


CORE = {"nomination", "markdown", "html", "provenance"}


def test_default_mode():
    assert tp_emit.expected_artifacts(_args()) == frozenset(CORE)


def test_verdict_only_and_no_figures_same_core():
    assert tp_emit.expected_artifacts(_args(verdict_only=True)) == frozenset(CORE)
    assert tp_emit.expected_artifacts(_args(no_figures=True)) == frozenset(CORE)


def test_emit_evidence_package_is_envelope_only():
    assert tp_emit.expected_artifacts(_args(emit="evidence-package")) == frozenset({"evidence_package"})


def test_ground_and_full_package_add_envelope():
    assert tp_emit.expected_artifacts(_args(ground="engine")) == frozenset(CORE | {"evidence_package"})
    assert tp_emit.expected_artifacts(_args(full_package=True)) == frozenset(CORE | {"evidence_package"})


def test_run_mode_precedence():
    assert tp_emit.run_mode(_args(emit="evidence-package", verdict_only=True)) == "evidence-package"
    assert tp_emit.run_mode(_args(verdict_only=True, no_figures=True)) == "verdict-only"
    assert tp_emit.run_mode(_args(no_figures=True)) == "no-figures"
    assert tp_emit.run_mode(_args()) == "default"


def test_write_artifact_uses_canonical_filename(tmp_path):
    p = tp_emit.write_artifact(tmp_path, "nomination", '{"x":1}')
    assert p == tmp_path / "nomination.json" and p.read_text() == '{"x":1}'
    with pytest.raises(KeyError):
        tp_emit.write_artifact(tmp_path, "bogus", "x")


def test_assert_write_set_tracks_written_not_disk():
    # keys on the run-scoped `written` set, NOT files on disk. Required = expected − best-effort(html).
    # missing a required kind → raises.
    with pytest.raises(AssertionError):
        tp_emit.assert_write_set(_args(), {"nomination", "markdown"})            # missing provenance
    # required present, html omitted (best-effort) → OK.
    tp_emit.assert_write_set(_args(), {"nomination", "markdown", "provenance"})
    # html present too → still OK (within expected).
    tp_emit.assert_write_set(_args(), {"nomination", "markdown", "provenance", "html"})
    # an UNEXPECTED extra kind → raises.
    with pytest.raises(AssertionError):
        tp_emit.assert_write_set(_args(), {"nomination", "markdown", "provenance", "evidence_package"})


def test_assert_write_set_robust_to_reused_out():
    # regression for the stale-file crash: --emit mode with ONLY evidence_package written this run passes
    # even though a prior default run left spine files in the same --out (we track writes, not disk).
    tp_emit.assert_write_set(_args(emit="evidence-package"), {"evidence_package"})
    # html render failed (fail-open) on a default run → html absent from written, still passes.
    tp_emit.assert_write_set(_args(), {"nomination", "markdown", "provenance"})
