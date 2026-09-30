"""onc_methods._common.live_data_skip -- shared "can't reach live data, not a code defect"
exception classifier.

Consolidates the botocore/credential/endpoint exception-TYPE classifier that used to be
defined twice: once in ``methods/conftest.py`` (a ``pytest_runtest_makereport`` hookwrapper
reclassifying an entire failed call as SKIPPED) and, independently, informing the string-marker
based ``skip_if_no_data`` helper in ``skills/_skills_common/tests/conftest.py`` (which wraps one
live-read thunk and skips on an S3-access failure). Both exist to answer the same question --
"did this fail because the runner has no route to live S3, or because the code is actually
broken?" -- from two different call shapes (an intercepted pytest report vs. a directly-caught
exception), so this module carries the shared TYPE-based half of that answer; each caller still
owns how it turns "yes, that's a live-data failure" into a skip (report mutation vs. pytest.skip).

Deliberately narrow, by TYPE not by hand-maintained test list: an AssertionError, AttributeError,
ValueError etc. never matches, so genuine breakage stays a failure. (skills#2142)
"""

from __future__ import annotations

# Exception TYPE names that indicate "couldn't reach the data", not "the code is wrong".
LIVE_DATA_EXC_NAMES = frozenset(
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


def is_live_data_exception(exc: BaseException | None) -> bool:
    """True iff `exc` (or something in its __cause__/__context__ chain) is a botocore /
    credential / endpoint error -- i.e. an environment limitation, not a code defect."""
    seen = 0
    while exc is not None and seen < 10:  # walk the __cause__/__context__ chain
        etype = type(exc)
        if getattr(etype, "__module__", "").split(".")[0] == "botocore":
            return True
        if etype.__name__ in LIVE_DATA_EXC_NAMES:
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False
