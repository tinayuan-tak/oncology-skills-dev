"""subgroup_common.paths — cache-root resolution with an env override.

The assigner CLIs read their source-data fallbacks from ~/.cache/framework-*.
Those paths were hardcoded as `Path.home() / ".cache"`, which meant an
end-to-end test that runs a CLI as a SUBPROCESS could only stage fixtures by
writing to the REAL cache — and if it didn't restore them (or crashed), it
permanently clobbered real cached data. (This is exactly what happened: a
pytest run overwrote the real 276-patient marker-paper + 208-sample MC3 caches
with 10-row / 8-row fixtures, forcing a re-pull before the S3 publish.)

`cache_root()` resolves the framework cache root, honoring the
FRAMEWORK_CACHE_ROOT env var. Tests set it to a tmp dir (and thread it into the
subprocess env), so real-execution tests never touch the real cache.
Production leaves it unset → the canonical ~/.cache.
"""

from __future__ import annotations

import os
from pathlib import Path

CACHE_ROOT_ENV = "FRAMEWORK_CACHE_ROOT"


def cache_root() -> Path:
    """Framework cache root. FRAMEWORK_CACHE_ROOT override, else ~/.cache."""
    override = os.environ.get(CACHE_ROOT_ENV)
    return Path(override) if override else Path.home() / ".cache"
