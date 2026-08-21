"""Shared pytest fixtures for the _skills_common test suite."""
from __future__ import annotations

import pytest


def _scrub_volatile(pkg: dict) -> dict:
    """Return a copy of a decision-package dict with the legitimately-NONDETERMINISTIC fields removed,
    for two-slot byte-stability comparisons.

    The two-slot invariant is that attaching the verdict-inert LLM narration slot (`llm_synthesis`)
    must not change the deterministic spine. But two fields legitimately vary run-to-run and are NOT
    part of that spine:
      - `generated_at`         — a wall-clock timestamp;
      - `run_health` timings   — read_secs / compute_secs / total_secs jitter at the sub-millisecond
                                 level (e.g. 0.0 vs 0.0001) purely from scheduling noise.
    Scrubbing ONLY the timing sub-fields (not the whole run_health block) keeps the rest of run_health
    — n_cards_fired, cards_missing, status, … — under the byte-stability assertion, which is exactly
    the kind of observability field the invariant should protect. Same discipline as generated_at /
    _prompt_hash elsewhere: the spine is the claim, not the clock.
    """
    pkg = dict(pkg)
    pkg.pop("generated_at", None)
    rh = pkg.get("run_health")
    if isinstance(rh, dict):
        pkg["run_health"] = {k: v for k, v in rh.items()
                             if k not in ("read_secs", "compute_secs", "total_secs")}
    return pkg


@pytest.fixture
def scrub_volatile():
    """The volatile-field scrubber for two-slot byte-stability tests (see _scrub_volatile)."""
    return _scrub_volatile


# --- live-data skip helper (ported from compose-dashboard/tests/conftest on the 2026-08-21 retire;
#     the live-reader chain/dispatch tests moved here with the _live_readers engine). ---------------
# Credential PRESENCE and even head_bucket can succeed in environments that STILL cannot read the
# specific object key, so a pre-probe is unreliable. Instead, wrap the live read: if it EITHER raises
# an S3 access/credential failure OR degrades to a structured no-data dict, skip — that's an
# environment limitation, not a regression. A dict with real populated fields returns normally.
_S3_ACCESS_MARKERS = (
    "access_denied", "accessdenied",
    "nocredentials", "unable to locate credentials",
    "forbidden", "403",
    "expiredtoken", "invalidaccesskeyid",
    "profilenotfound",
)


def skip_if_no_data(thunk):
    """Call `thunk()` and return its result; skip the test if the live read could not access data
    (S3 access error raised, OR a structured no-data dict returned). Non-S3 exceptions propagate."""
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
        note = result.get("_data_note")
        if note and all(v is None for k, v in result.items() if not k.startswith("_")):
            pytest.skip(f"live read returned no data ({note})")
    return result
