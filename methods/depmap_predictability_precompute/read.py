"""depmap_predictability_precompute.read — minimal library surface.

This method has NO live-read role; the precompute pipeline writes a frozen
derived parquet that the sibling `depmap_predictability` method reads at
framework run-time. The read entrypoint here is a placeholder that signals
the absence-of-live-read intentionally, so the compose-dashboard live-reader
chain doesn't blindly try to invoke it.
"""

from __future__ import annotations

from typing import Optional


def read_predictability_precompute(target: str, indication: Optional[str] = None) -> dict:
    return {
        "_live_read_error": "no_live_mode",
        "_remediation": "This is a precompute method. Read the derived product "
        "via the depmap-predictability card / "
        "methods/depmap_predictability/read.py.",
        "predictability_class": "data_unavailable",
    }
