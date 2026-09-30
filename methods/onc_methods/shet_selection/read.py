"""shet_selection.read — GeneBayes s_het for a target gene (dominant-LoF selection coefficient).

read_target_summary(target, indication=None) → the shet-lof-intolerance card's summary_fields.
`indication` accepted for the dispatcher signature but NOT consumed (s_het is a gene-level property).
data_unavailable-safe: a genuine gene-absence/404 → shet_class=indeterminate; transient/creds fault
PROPAGATES as an honest _live_read_error (never a silent dead axis).
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    try:
        row = _cli.load_shet_row(target)
    except Exception as e:  # noqa: BLE001 — populated dict (not empty); honest _live_read_error
        return {
            "shet_class": "indeterminate",
            "shet_score": None,
            "method_version": METHOD_VERSION,
            "_live_read_error": (
                f"shet_selection read failed for {target} "
                f"(s3://{_cli.S3_BUCKET}/{_cli.S3_KEY}): {type(e).__name__}: {e}"
            ),
        }
    return _cli.compute_summary(row, target)
