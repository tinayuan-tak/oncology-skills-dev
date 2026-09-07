"""depmap_protein_abundance.read — live-mode dispatcher entry.

The compose-dashboard dispatcher calls read_target_summary(target=..., indication=...).
Returns the cellline-protein-abundance card summary (cell-line TMT MS protein
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

from pathlib import Path
from typing import Optional

from . import cli as _cli


def read_target_summary(target: str, indication: Optional[str] = None, plot_data_out: Optional[Path] = None) -> dict:
    """Cell-line protein-abundance distribution for a target. Protein-intrinsic —
    indication accepted for the CARD_DISPATCHERS contract but NOT consumed.

    plot_data_out (figure Stage 1): OPT-IN dir forwarded to load_and_classify so card resolution
    persists plot_data_protein_abundance.parquet. Default None => byte-identical no-op."""
    try:
        # Panel size (detection denominator) comes from the same matrix read inside
        # load_and_classify — fraction_detected = detected / total-MS-lines.
        summary = _cli.load_and_classify(target, plot_data_out=plot_data_out)
        # All-gene percentile null: where this protein's median abundance ranks among
        # ALL proteins' medians in the DepMap MS panel (context = pan-panel, protein-
        # intrinsic; indication not consumed). Additive — display + companion categorical.
        # Rank against the null of the assay that PRODUCED the call (Gygi TMT vs Olink NPX — different
        # scales; the Olink fallback sets protein_abundance_source=olink_npx). Default gygi_ms.
        _source = summary.get("protein_abundance_source", "gygi_ms")
        pct, pct_class = _cli.target_allgene_percentile(summary.get("median_log2_abundance_panel"), source=_source)
        summary["allgene_percentile"] = pct
        summary["allgene_percentile_class"] = pct_class
        summary["allgene_percentile_context"] = (
            f"depmap-proteomics-26q1 panel-wide metric=median_log2_abundance source={_source}"
        )
        return summary
    except Exception as e:  # noqa: BLE001 — any load failure → graceful data_unavailable
        return {
            "_live_read_error": "depmap_protein_abundance_read_failed",
            "_remediation": (
                f"Could not read DepMap proteomics Gygi TMT MS "
                f"(s3://{_cli.S3_BUCKET}/{_cli.MATRIX_KEY}) for {target}: {e}"
            ),
            "protein_expression_class": "data_unavailable",
            "protein_abundance_source": "data_unavailable",
            "n_cell_lines_evaluated": 0,
            "fraction_detected": 0.0,
            "median_log2_abundance_panel": None,
            "protein_effect_size": None,
            "per_lineage_stats": [],
            "method_version": _cli.METHOD_VERSION,
        }
