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

import pytest

# Exception TYPE names that indicate "couldn't reach the data", not "the code is wrong".
_LIVE_DATA_EXC_NAMES = frozenset(
    {
        "NoCredentialsError",
        "PartialCredentialsError",
        "ClientError",
        "EndpointConnectionError",
        "ConnectTimeoutError",
        "ReadTimeoutError",
        "SSLError",
        "CredentialRetrievalError",
    }
)


def _is_live_data_failure(excinfo) -> bool:
    """True iff the raised exception is an S3/credential/endpoint error (chain-aware)."""
    if excinfo is None:
        return False
    exc = excinfo.value
    seen = 0
    while exc is not None and seen < 10:  # walk the __cause__/__context__ chain
        etype = type(exc)
        if getattr(etype, "__module__", "").split(".")[0] == "botocore":
            return True
        if etype.__name__ in _LIVE_DATA_EXC_NAMES:
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    if not os.environ.get("SKILLS_SKIP_LIVE_DATA"):
        return
    rep = outcome.get_result()
    if rep.when == "call" and rep.failed and _is_live_data_failure(call.excinfo):
        rep.outcome = "skipped"
        rep.wasxfail = "live data unavailable on credential-less runner"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_data: reads live S3 product data (e.g. drops its offline patches via "
        "monkeypatch.undo(), or reads a governed corpus). Skipped when SKILLS_SKIP_LIVE_DATA is set "
        "\u2014 the read degrades on a credential-less runner, so the assertion is then not a code "
        "defect. Use this ONLY for tests that genuinely need data, never to paper over a stale patch.",
    )


def pytest_runtest_setup(item):
    if os.environ.get("SKILLS_SKIP_LIVE_DATA") and item.get_closest_marker("requires_data"):
        pytest.skip("requires live S3 data (SKILLS_SKIP_LIVE_DATA set)")
