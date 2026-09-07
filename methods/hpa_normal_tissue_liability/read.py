"""hpa_normal_tissue_liability.read — live-mode dispatcher entry.

The compose-dashboard dispatcher calls read_target_summary(target=..., indication=...).
Returns the normal-tissue-liability card summary (HPA IHC normal-tissue footprint —
the dominant biologics on-target-off-tumor safety signal). Normal-tissue footprint is
a gene-level property — `indication` is accepted for the dispatcher contract but NOT
consumed.

Graceful-degradation contract (same as the other readers): on any load failure,
returns _live_read_error + normal_tissue_breadth_class=data_unavailable. Distinction
the card cares about: data_unavailable from classify (gene genuinely absent from HPA /
no IHC call) is a real coverage gap; _live_read_error means the SOURCE couldn't be
read. Both surface as data_unavailable so the degradation path holds; the
_live_read_error key disambiguates for provenance.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """HPA normal-tissue liability for a target. Gene-level — indication accepted
    for the CARD_DISPATCHERS contract but NOT consumed."""
    try:
        return _cli.load_and_classify(target)
    except Exception as e:  # noqa: BLE001 — any load failure → graceful data_unavailable
        return {
            "_live_read_error": "hpa_normal_tissue_read_failed",
            "_remediation": (f"Could not read HPA master TSV (s3://{_cli.S3_BUCKET}/{_cli.HPA_KEY}) for {target}: {e}"),
            "normal_tissue_breadth_class": "data_unavailable",
            "essential_tissue_flag": "unknown",  # SOURCE unread → no data (NOT a measured `absent`); mirrors cli.py compute_summary(row=None)
            "hpa_tissue_distribution": None,
            "hpa_tissue_specificity": None,
            "n_essential_tissues_with_expression": 0,
            "essential_tissues_flagged": [],
            "n_specific_tissues": 0,
            "specific_tissues": [],
            "safety_tissue_flags": [],
            "method_version": _cli.METHOD_VERSION,
        }
