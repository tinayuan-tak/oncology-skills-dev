"""Shared fixtures/helpers for compose-dashboard tests.

T10 (2026-08-11 engineering review): a point-of-use skip helper for live-data tests that read
real parquet from s3://onc-compbio. Credential PRESENCE and even head_bucket succeed in some
environments that STILL cannot read the specific object key, so a pre-probe is unreliable.
Instead, wrap the live read: if it EITHER raises the specific S3 access-denied / no-credentials
failure, OR degrades to a structured no-data dict (`_live_read_error`, or a `_data_note` with all
metric fields None), skip — that's an environment limitation, not a regression. A dict with real
populated fields (a genuine wiring/logic result) is returned normally so the test's assertions run.
"""
from __future__ import annotations

import pytest

# Substrings that unambiguously indicate an S3 access/credential problem (env, not a code bug).
_S3_ACCESS_MARKERS = (
    "access_denied", "accessdenied",
    "nocredentials", "unable to locate credentials",
    "forbidden", "403",
    "expiredtoken", "invalidaccesskeyid",
)


def skip_if_no_data(thunk):
    """Call `thunk()` and return its result; skip the test if the live read could not access
    data (S3 access error raised, OR a structured no-data dict returned). Non-S3 exceptions
    (wiring/logic bugs) propagate unchanged."""
    try:
        result = thunk()
    except Exception as e:  # noqa: BLE001 — classify, then re-raise if not an S3 access issue
        msg = f"{type(e).__name__}: {e}".lower()
        if any(marker in msg for marker in _S3_ACCESS_MARKERS):
            pytest.skip(f"live S3 object read not permitted in this environment ({type(e).__name__})")
        raise

    if isinstance(result, dict):
        if "_live_read_error" in result:
            pytest.skip(f"live read returned _live_read_error: {result['_live_read_error']}")
        # Degraded no-data dict: a _data_note present AND no populated metric field.
        note = result.get("_data_note")
        if note and all(v is None for k, v in result.items() if not k.startswith("_")):
            pytest.skip(f"live read returned no data ({note})")
    return result
