"""depmap_protein_abundance.read — live-mode dispatcher entry.

The compose-dashboard dispatcher calls read_target_summary(target=..., indication=...).
Returns the protein-abundance-celline card summary (cell-line TMT MS protein
distribution). Protein abundance is a per-ModelID property — `indication` is
accepted for the dispatcher contract but NOT consumed (lineage stratification is a
separate read-side axis, not indication-scoped).

Graceful-degradation contract (same as gnomad_constraint / topology / shed readers):
on any load failure, returns _live_read_error + protein_expression_class=data_unavailable.
Distinction the card cares about: `data_unavailable` from classify (protein genuinely
absent from the MS matrix) is a real coverage-gap signal; `_live_read_error` means the
SOURCE couldn't be read (infra failure). Both surface as data_unavailable class so the
degradation path holds, but the _live_read_error key disambiguates for provenance.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """Cell-line protein-abundance distribution for a target. Protein-intrinsic —
    indication accepted for the CARD_DISPATCHERS contract but NOT consumed."""
    try:
        # Panel size (detection denominator) comes from the same matrix read inside
        # load_and_classify — fraction_detected = detected / total-MS-lines.
        return _cli.load_and_classify(target)
    except Exception as e:  # noqa: BLE001 — any load failure → graceful data_unavailable
        return {
            "_live_read_error": "depmap_protein_abundance_read_failed",
            "_remediation": (
                f"Could not read DepMap proteomics Gygi TMT MS "
                f"(s3://{_cli.S3_BUCKET}/{_cli.MATRIX_KEY}) for {target}: {e}"),
            "protein_expression_class": "data_unavailable",
            "n_cell_lines_evaluated": 0,
            "fraction_detected": 0.0,
            "median_log2_abundance_panel": None,
            "protein_effect_size": None,
            "per_lineage_stats": [],
            "method_version": _cli.METHOD_VERSION,
        }
