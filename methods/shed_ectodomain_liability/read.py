"""shed_ectodomain_liability.read — v2 library entry for live-mode reads.

The compose-dashboard dispatcher calls `read_target_summary(target=..., indication=...)`.
Resolves the curated shed-antigen serum-marker crosswalk (target-contracts vocab)
+ the HPA v25-1 secretome proxy, and returns the `shed-ectodomain-liability` card
summary.

Graceful-degradation contract (same as gnomad_constraint / topology readers): on
any load failure, returns `_live_read_error` + `shed_liability_class=data_unavailable`
so the framework's degradation path holds. NOTE the distinction the card cares about:
`indeterminate` = we READ the tiers and found no shedding evidence either way (a real
coverage-gap signal, NOT "not shed"); `data_unavailable` = we COULDN'T read the source
(infra failure). Shedding is a protein-intrinsic property — `indication` is accepted
for the dispatcher contract but NOT consumed.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """Shed-ectodomain liability for a target. Protein-intrinsic — `indication`
    accepted for the CARD_DISPATCHERS contract but NOT consumed."""
    try:
        return _cli.load_and_classify(target)
    except Exception as e:  # noqa: BLE001 — any load failure → graceful data_unavailable
        return {
            "_live_read_error": "shed_ectodomain_read_failed",
            "_remediation": (
                f"Could not read shed-antigen sources (curated vocab "
                f"{_cli.SHED_VOCAB_RELPATH} + HPA s3://{_cli.S3_BUCKET}/{_cli.HPA_KEY}) "
                f"for {target}: {e}"
            ),
            "shed_liability_class": "data_unavailable",
            "shed_evidence_tier": "none",
            "serum_marker": None,
            "shed_product": None,
            "shedding_protease": None,
            "hpa_secretome_location": None,
            "source_citation": None,
            "method_version": _cli.METHOD_VERSION,
            # measured Olink-media facet (E3) — data_unavailable on the same infra failure
            "measured_shed_class": "data_unavailable",
            "media_mean_npx": None,
            "media_n_lines_detected": None,
            "media_panel_high_npx": None,
            "media_uniprot": None,
        }
