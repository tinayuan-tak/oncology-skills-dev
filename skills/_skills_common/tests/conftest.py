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
