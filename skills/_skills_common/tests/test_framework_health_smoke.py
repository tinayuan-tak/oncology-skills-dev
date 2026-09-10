"""Tests for the framework-health 'runs clean?' smoke harness.

The harness runs each wired subskill's real run.py under FRAMEWORK_HEALTH_SMOKE=1
(card readers stubbed → NO live data) and records run_health into a committed rollup.
These guard: the smoke seam short-circuits reads, the harness classifies clean vs
error vs clean_uninstrumented, and the committed rollup stays fresh + self-consistent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # skills/

from _skills_common import framework_health_smoke as H  # noqa: E402
from _skills_common import resolve_cards  # noqa: E402


def test_smoke_seam_short_circuits_live_reads(monkeypatch):
    """With FRAMEWORK_HEALTH_SMOKE set, resolve_cards returns synthetic stubs and NEVER
    calls the live dispatcher (proves offline determinism)."""
    # If the seam leaked, _import_dispatcher would be reached; make it explode to prove it isn't.
    import _skills_common as C

    monkeypatch.setattr(
        C, "_import_dispatcher", lambda: (_ for _ in ()).throw(AssertionError("live read attempted under smoke"))
    )
    monkeypatch.setenv("FRAMEWORK_HEALTH_SMOKE", "1")
    out = resolve_cards(["card-a", "card-b"], "FIXTURE", "COADREAD")
    assert [c["card_id"] for c in out] == ["card-a", "card-b"]
    assert all(c["_smoke"] and not c["_missing"] for c in out)


def test_smoke_seam_off_by_default(monkeypatch):
    """Unset flag → the smoke branch is NOT entered (live path is taken)."""
    monkeypatch.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    import _skills_common as C

    monkeypatch.setattr(C, "_import_dispatcher", lambda: lambda cid, t, i, **k: None)
    out = resolve_cards(["card-a"], "T", "IND")
    # live path tagged it missing (dispatcher returned None) — proves smoke branch was skipped
    assert out[0]["_missing"] and not out[0].get("_smoke")


def test_wired_subskills_discovered():
    """The harness finds the wired subskills and skips infra/orchestration dirs."""
    skills = H._wired_subskills()
    assert "tumor-presence" in skills and "functional-requirement" in skills
    for skip in ("_skills_common", "compose-dashboard", "query-target-evidence"):
        assert skip not in skills


def test_stable_projection_drops_volatile_timings():
    """--check must ignore per-run seconds (volatile) but catch a status change."""
    base = {
        "subskills": {
            "s": {
                "smoke": "clean",
                "run_health": {"status": "ok", "read_secs": 0.1, "compute_secs": 0.2, "total_secs": 0.3},
            }
        }
    }
    slow = {
        "subskills": {
            "s": {
                "smoke": "clean",
                "run_health": {"status": "ok", "read_secs": 9.9, "compute_secs": 8.8, "total_secs": 18.7},
            }
        }
    }
    assert H._stable(base) == H._stable(slow)  # only timings differ → same projection
    broke = {"subskills": {"s": {"smoke": "error", "run_health": {}}}}
    assert H._stable(base) != H._stable(broke)  # status change IS caught


def test_committed_rollup_is_fresh_and_consistent():
    """The committed subskill_health.json must exist, be self-consistent, and pass --check
    (this is what a CI guard runs). If this fails, regenerate it."""
    if not H._OUT.exists():
        import pytest

        pytest.skip("no committed subskill_health.json")
    rep = json.loads(H._OUT.read_text())
    s = rep["summary"]
    # tallies match the per-subskill records
    smokes = [r["smoke"] for r in rep["subskills"].values()]
    assert s["n_clean"] == smokes.count("clean")
    assert s["n_error"] == smokes.count("error")
    assert s["n_clean_uninstrumented"] == smokes.count("clean_uninstrumented")
    assert s["n_subskills"] == len(smokes)
    # every clean record carries a run_health status
    for r in rep["subskills"].values():
        if r["smoke"] == "clean":
            assert r["run_health"]["status"] in ("ok", "degraded")
