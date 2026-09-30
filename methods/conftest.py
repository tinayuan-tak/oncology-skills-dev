"""Root pytest conftest for analysis-methods.

CI RUNS CREDENTIAL-LESS: the GitHub runner has no AWS credentials, so any test that reaches live
S3 (real product reads, figure emitters over real data) would fail with a botocore error that is
NOT a code defect. When the env flag ``SKILLS_SKIP_LIVE_DATA`` is set (CI sets it), we convert
*only* those infrastructure/credential failures into SKIPS — by exception type, not by a hand-maintained
test list — so the gate reports exactly the OFFLINE-deterministic result.

Deliberately narrow: we skip on botocore / credential / endpoint errors ONLY. An AssertionError,
AttributeError, ValueError, etc. stays a real failure and turns the check red — the whole point is
to surface genuine breakage, never to hide it behind "no data". (This mirrors the credential-less
`skip_if_no_data` discipline used by the skills repo's CI.)

Locally: unset SKILLS_SKIP_LIVE_DATA (default) to run everything, including live-S3 tests, against
real credentials.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# ── worktree binding guard (skills#2266) ─────────────────────────────────────────────────────────
# `oncology-analysis-methods` is installed EDITABLE, and depending on how the active env was built
# its finder can resolve `onc_methods` to a DIFFERENT checkout than the tree this conftest lives in —
# classically the PRIMARY checkout a /tmp worktree was branched from. Because this conftest imports
# `onc_methods` at COLLECTION time (below), that binding is frozen into sys.modules before any test
# module runs; from then on a `sys.path.insert(0, <worktree>/methods)` is INERT — `import onc_methods`
# is served straight out of sys.modules. Net effect: a `methods/` suite run from a worktree silently
# exercises the OTHER tree, and a green branch proves nothing about the branch (measured in skills#2266:
# six planted mutations of production constants ALL survived at 42/42 green). Neither cwd nor the
# invocation form is a reliable guard — the `pytest` console script puts its bin/ dir (not cwd) on
# sys.path[0], so even `cd $WT/methods` does not shadow the editable finder; only `python -m pytest`
# happened to, by luck. So: BEFORE the import, purge any stale `onc_methods` binding and put THIS
# tree first, making worktree gates correct by construction rather than by per-module workaround or
# invocation discipline. Then assert loudly — a blind suite must never be able to report green.
_METHODS_DIR = Path(__file__).resolve().parent  # the dir that holds onc_methods/
for _stale in [_m for _m in sys.modules if _m == "onc_methods" or _m.startswith("onc_methods.")]:
    del sys.modules[_stale]
if not sys.path or Path(sys.path[0]).resolve() != _METHODS_DIR:
    sys.path.insert(0, str(_METHODS_DIR))

import onc_methods as _onc_methods  # noqa: E402
from onc_methods._common.live_data_skip import is_live_data_exception  # noqa: E402

_resolved_methods_dir = Path(_onc_methods.__file__).resolve().parent.parent
if _resolved_methods_dir != _METHODS_DIR:
    raise RuntimeError(
        "methods/ gate is BLIND (skills#2266): the onc_methods package under test resolved to\n"
        f"    {_onc_methods.__file__}\n"
        f"which is NOT the tree this conftest lives in ({_METHODS_DIR}/onc_methods). A suite run this\n"
        "way would exercise the wrong checkout and could report GREEN while testing other code.\n"
        "Run the methods gate from inside the worktree; if this persists, the editable install's\n"
        "finder is bound to another tree — re-run `pixi install` in this worktree."
    )

# Exploratory method-development scripts (methods/<pkg>/method_development/<YYYY-MM>_<slug>/...) are
# NOT unit tests: they invoke R and read live S3, and run on demand (see a package's method_development
# README). Never let pytest collect anything beneath a method_development/ tree — a helper that happens
# to match a test name pattern, or a module-level S3 call at import, would otherwise break collection.
# fnmatch semantics: '*' expands to '.*' and crosses '/', so this ignores the whole subtree.
collect_ignore_glob = ["*/method_development/*"]


def _is_live_data_failure(excinfo) -> bool:
    """True iff the raised exception is an S3/credential/endpoint error (chain-aware).

    The TYPE-based classification itself is shared with skills/_skills_common/tests/conftest.py's
    skip_if_no_data via methods._common.live_data_skip (skills#2142) — this wrapper just adapts the
    pytest ExceptionInfo shape this hook receives.
    """
    if excinfo is None:
        return False
    return is_live_data_exception(excinfo.value)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if not os.environ.get("SKILLS_SKIP_LIVE_DATA"):
        return
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed and _is_live_data_failure(call.excinfo):
        rep.outcome = "skipped"
        rep.wasxfail = "live data unavailable on credential-less runner"


# requires_data is now registered declaratively in pyproject.toml's [tool.pytest.ini_options]
# markers list (SK#2093) rather than programmatically here.


def pytest_runtest_setup(item):
    if os.environ.get("SKILLS_SKIP_LIVE_DATA") and item.get_closest_marker("requires_data"):
        pytest.skip("requires live S3 data (SKILLS_SKIP_LIVE_DATA set)")
