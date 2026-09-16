#!/usr/bin/env python3
"""json_io — the emission serialization boundary (Track C, Stage 2).

`dump_json(obj)` is `json.dumps(obj, allow_nan=False)`, but when a non-finite value is present it raises a
NAMED, LOCATED error (`NonFiniteEmissionError` with the dotted path + the value) instead of the bare
"Out of range float values are not JSON compliant". This is the writer that makes invalid data
*unserialisable*: a NaN / ±Inf becomes a fatal, findable error rather than the token `NaN` silently
shipped into a package — the exact failure the emission-invariant arc exists to catch.

★ THIS IS THE HELPER ONLY — routing is deliberately a LATER step. Sending the persisted-artifact write
paths (`dispatcher.py` package writer, `write_package.py`) through `dump_json` must land as a ratchet that
keeps a clean corpus clean, and ONLY AFTER the producer fixes are in and a regenerated corpus confirms the
non-finite is gone. Flipping the writer to fatal today would break the 501/504 packages that still carry
the pre-#644 label leak. The plan's sequencing: write the helper first (this PR), route it last.
"""

from __future__ import annotations

import json
import math
from typing import Any, Optional


class NonFiniteEmissionError(ValueError):
    """A non-finite float (NaN / ±Inf) reached the JSON emission boundary. Subclasses ValueError so an
    existing `except ValueError` around a write still catches it — but carries the located `path`+`value`."""

    def __init__(self, path: str, value: float):
        self.path = path
        self.value = value
        super().__init__(f"non-finite value {value!r} at {path} — invalid for JSON emission")


def _find_nonfinite(obj: Any, path: str = "") -> Optional[tuple]:
    """The (dotted-path, value) of the FIRST non-finite float in `obj`, or None. Depth-first, mirroring
    the emission_invariants traversal so the reported location matches what the invariant reports."""
    if isinstance(obj, float) and not math.isfinite(obj):
        return (path or "<root>", obj)
    if isinstance(obj, dict):
        for k, v in obj.items():
            hit = _find_nonfinite(v, f"{path}.{k}" if path else str(k))
            if hit:
                return hit
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            hit = _find_nonfinite(v, f"{path}[{i}]")
            if hit:
                return hit
    return None


def dump_json(obj: Any, **kwargs) -> str:
    """`json.dumps(obj, allow_nan=False, **kwargs)` — a non-finite value raises `NonFiniteEmissionError`
    naming its path + value. `allow_nan` cannot be overridden (that would defeat the guard)."""
    kwargs.pop("allow_nan", None)
    try:
        return json.dumps(obj, allow_nan=False, **kwargs)
    except ValueError:
        loc = _find_nonfinite(obj)
        if loc is not None:
            raise NonFiniteEmissionError(loc[0], loc[1]) from None
        raise  # a different ValueError (e.g. a circular reference) — surface unchanged


__all__ = ["dump_json", "NonFiniteEmissionError"]
