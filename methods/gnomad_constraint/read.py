"""gnomad_constraint.read — v2 library entry for live-mode reads.

The compose-dashboard dispatcher (`_dispatch_gnomad_lof_constraint`) calls
`read_target_summary(target=..., indication=...)`. Reads the gnomAD v4.1 constraint
TSV (S3 read-through cache), picks the per-gene canonical/MANE row, and returns the
`gnomad-lof-constraint` card summary.

Graceful-degradation contract (same as the other readers, e.g. depmap_predictability):
on unreachable source or any load failure, returns `_live_read_error` +
`constraint_class=data_unavailable` so the framework's degradation path holds. NOTE the
distinction the card cares about: `indeterminate` = we READ the table and the gene is
genuinely absent (a real negative-ish signal); `data_unavailable` = we COULDN'T read
(coverage gap). The skill's `_verdict` maps the former to a real constraint call and the
latter to `constraint-data-unavailable-insufficient`.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """gnomAD LoF-constraint for a target. Germline/pan-population — indication is
    accepted for the CARD_DISPATCHERS contract but NOT consumed (constraint is a
    gene-level property, not indication-specific)."""
    try:
        row = _cli.load_constraint_row(target)
    except Exception as e:  # noqa: BLE001 — any load failure → graceful data_unavailable
        return {
            "_live_read_error": "gnomad_constraint_read_failed",
            "_remediation": (
                f"Could not read gnomAD constraint source "
                f"(s3://{_cli.S3_BUCKET}/{_cli.S3_KEY}) for {target}: {e}"),
            "constraint_class": "data_unavailable",
            "pli_score": None, "loeuf_score": None,
            "method_version": _cli.METHOD_VERSION,
        }
    return _cli.compute_summary(row, target)
