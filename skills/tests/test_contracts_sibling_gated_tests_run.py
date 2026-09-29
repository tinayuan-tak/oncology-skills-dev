"""Sibling-wiring guard — methods/skills-dependent contracts tests must RUN, not silently skip.

The companion to ``test_ci_covers_all_test_files``. That guard proves every test FILE is
*collected* by a ``pytest`` step; this one proves the contracts tests that self-skip when a
sibling root is absent are collected by a job where the sibling is actually PRESENT — so a
methods- or skills-dependent contracts test cannot go green-by-skip.

Why this is a distinct failure family (#2090, and the skip-blindness backstop #2127): before
#2090 the contracts jobs pinned ``ANALYSIS_METHODS_ROOT`` / ``CLAUDE_ONCOLOGY_SKILLS_ROOT`` to
``/nonexistent`` to preserve the pre-consolidation checkout-only skip baseline. Under ``pytest -q``
a skip is INVISIBLE, so a validator whose live half only runs when a sibling is present
(``test_card_method_wiring``, the wiring/emission-ledger LIVE recomputes, ``validate_cards`` method
routability, the framework-health probes) read as PASS while never executing. #2090 retired that
shim and wired the roots in-tree. This guard pins that wiring so a future edit cannot silently
re-pin a root to ``/nonexistent`` and re-hide those tests: the workflow is the SINGLE SOURCE OF
TRUTH, parsed here, exactly as ``test_ci_covers_all_test_files`` parses it for file coverage.

Combined with ``test_ci_covers_all_test_files`` (every contracts test file IS collected by the
contracts jobs' whole-package net) the two guards close the loop: every methods-dependent contracts
test is collected AND collected by a job where methods is present, so it runs.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "skills-validate.yml"

# The contracts jobs collect the methods-/skills-dependent contracts tests. They must wire these
# roots to a REAL in-tree sibling so those tests execute rather than self-skip.
_SIBLING_ROOTS = ("ANALYSIS_METHODS_ROOT", "CLAUDE_ONCOLOGY_SKILLS_ROOT", "DATA_CATALOG_ROOT")
_CONTRACTS_JOBS = ("contracts-static", "contracts-pytest")


def _workflow() -> dict:
    assert WORKFLOW.is_file(), f"workflow not found at {WORKFLOW}"
    return yaml.safe_load(WORKFLOW.read_text())


def test_contracts_jobs_exist_and_are_gated_on_a_shared_run_flag():
    """Anti-vacuity + structure: the jobs this guard reasons about must exist, and both must gate on
    the SAME change-filter output — otherwise one leg could run with siblings while the other hides a
    dependent test behind a different (or missing) condition."""
    jobs = _workflow()["jobs"]
    for job in _CONTRACTS_JOBS:
        assert job in jobs, f"{job} job vanished — this guard (and the sibling wiring) is stale"
    conds = {jobs[job].get("if") for job in _CONTRACTS_JOBS}
    assert len(conds) == 1 and next(iter(conds)), (
        f"the contracts legs must share ONE gating condition so they run together; got {conds}"
    )


def test_contracts_jobs_wire_every_sibling_root_in_tree_never_nonexistent():
    """The load-bearing assertion. Each contracts job must set every sibling root to a concrete
    in-tree/pinned value — never ``/nonexistent`` and never unset — so a self-skipping,
    sibling-gated contracts test actually RUNS there instead of reading green-by-skip under ``-q``."""
    jobs = _workflow()["jobs"]
    for job in _CONTRACTS_JOBS:
        env = jobs[job].get("env") or {}
        for root in _SIBLING_ROOTS:
            val = env.get(root)
            assert val is not None, (
                f"{job} does not set {root}; a sibling-gated contracts test would self-skip there and "
                f"read green-by-absence under pytest -q (#2090/#2127)"
            )
            assert "/nonexistent" not in str(val), (
                f"{job} pins {root}={val!r} — the retired /nonexistent shim. This re-hides every "
                f"contracts test whose live half needs {root}; wire it to the in-tree sibling instead"
            )


def test_contracts_pytest_collects_the_whole_package_so_no_dependent_test_is_orphaned():
    """The other half of the loop: the job that wires the roots must collect the WHOLE contracts
    package (a bare ``python -m pytest`` under ``working-directory: …/contracts``, no path args that
    could scope a methods-dependent test out), so wiring the root actually reaches every such test."""
    job = _workflow()["jobs"]["contracts-pytest"]
    wd = (job.get("defaults") or {}).get("run", {}).get("working-directory", "")
    assert wd.endswith("/contracts") or wd == "contracts", (
        f"contracts-pytest working-directory must be the contracts package root; got {wd!r}"
    )
    run_steps = " ".join(str(s.get("run", "")) for s in job.get("steps") or [])
    assert "python -m pytest" in run_steps, "contracts-pytest must invoke the whole-package pytest gate"
    # -rs keeps any residual skip visible in the log (a skip is 'the check did not run').
    assert "-rs" in run_steps, (
        "contracts-pytest must pass -rs so a residual sibling skip is printed, never summed into green"
    )
