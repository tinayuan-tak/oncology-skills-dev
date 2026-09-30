"""onc_methods._common.s3 -- canonical process-wide pyarrow S3FileSystem singleton.

Consolidates ~21 copy-pasted double-checked-locking ``_get_s3fs()`` implementations
scattered across ``methods/onc_methods/*/read.py`` and ``cli.py`` (surveyed 2026-09-29,
skills#2141) -- every one of them building a ``pyarrow.fs.S3FileSystem(region="us-east-1")``
(the onc-compbio bucket's region, pinned to skip the region-probe round-trip) exactly once
per process and sharing it across the parallel card-read pool. A handful of callers first ran
a credential side-effect (``ensure_aws_profile()``) before constructing; that is preserved via
the optional ``pre_hook`` parameter rather than silently dropped, so the two families of caller
are not collapsed into one that ignores the difference. Instances are cached per
``(region, pre_hook)`` so two callers with an identical signature share one instance -- the
intent every migrated docstring already stated ("Mirrors <sibling>._get_s3fs").

NOT migrated (each left as its own local singleton -- a materially different contract, not a
copy-paste twin):
  - ``hpa_pathology_cancer_ihc.read._get_s3fs`` and ``sc_normal_expression.read._get_s3fs``
    both resolve explicit frozen boto3 credentials for the ``cbg`` SSO profile (with a fallback
    dance to the ambient chain when that profile is absent) and inject
    ``access_key``/``secret_key``/``session_token`` into the constructor -- collapsing those
    into the ambient-chain-only helper here would silently change their credential resolution.
  - ``depmap_surfaceome_protein_abundance.cli._get_s3fs`` and
    ``procan_protein_abundance.cli._get_s3fs`` construct with NO region kwarg at all (a real
    divergence from the us-east-1-pinned majority, itself pinned by each module's own
    ``test_s3fs_singleton_is_shared`` fixture asserting object identity + a build-count of
    exactly one against a module-local ``_S3FS`` global that the test resets directly) --
    left with their own local singleton rather than folded in here.
"""

from __future__ import annotations

import threading
from typing import Callable, Optional

_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def get_s3fs(region: str = "us-east-1", pre_hook: Optional[Callable[[], None]] = None):
    """Process-wide pyarrow S3FileSystem singleton, one instance per ``(region, pre_hook)``.

    Double-checked locking so concurrent first-callers build exactly one instance. ``pre_hook``,
    when given, runs once, immediately before construction (e.g. ``ensure_aws_profile``) --
    preserved per-caller so a reader that needs the side effect still gets it, exactly once,
    the same as its own local implementation did.
    """
    key = (region, pre_hook)
    if key not in _CACHE:
        with _CACHE_LOCK:
            if key not in _CACHE:
                if pre_hook is not None:
                    pre_hook()
                import pyarrow.fs as pafs

                _CACHE[key] = pafs.S3FileSystem(region=region)
    return _CACHE[key]
