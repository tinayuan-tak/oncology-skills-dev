"""depmap_surfaceome_protein_abundance.read — live-mode dispatcher entry.

The GENERIC skills dispatcher (skills/_skills_common/_live_readers.py:_generic_dispatch) resolves
`module: depmap_surfaceome_protein_abundance` + `entrypoint: read_target_summary` from the
cellline-surfaceome-abundance card_spec and calls read_target_summary(target=, indication=).
Returns the SAME cellline-protein-abundance card summary shape as the Gygi / ProCan siblings (this is
its third, orthogonal platform — the DepMap Consortium Surfaceome 26Q3 PAIRED DIA-MS assay), computed
on the SURFACE-enriched abundance layer, PLUS the surface-vs-wholecell enrichment rollup. Protein
abundance is a per-cell-line property — `indication` is accepted for the dispatcher contract but NOT
consumed (the 64-line panel is gastric/esophageal by release scope, carried in the source manifest).

Graceful-degradation contract (same as the Gygi / ProCan readers): on any load failure, returns
_live_read_error + protein_expression_class=data_unavailable, so the card degrades honestly instead of
crashing the compose path. `data_unavailable` from load_and_classify (protein genuinely absent from the
surfaceome panel, or symbol unresolvable) is a real coverage-gap signal; `_live_read_error` means the
SOURCE couldn't be read (infra failure) — both surface as data_unavailable class, the key disambiguates
for provenance.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """DepMap Surfaceome 26Q3 cell-line surface protein-abundance + enrichment rollup for a target.
    Protein-intrinsic — `indication` accepted for the generic-dispatch contract but NOT consumed."""
    try:
        return _cli.load_and_classify(target)
    except Exception as e:  # noqa: BLE001  # absence-discipline: exempt -- benign: the card is verdict-INERT (interpretation=rules_pending, drives no nomination gate), and this handler sets the disambiguating `_live_read_error` breadcrumb (infra fault, NOT a measured absence) alongside protein_expression_class=data_unavailable. Genuine coverage gaps (accession absent / symbol unresolvable) already return data_unavailable WITHOUT raising from load_and_classify, whose primary pushdown (_load_pushdown_live, no broad except) PROPAGATES transient/creds/broken-env faults honestly to here. Mirrors the baselined procan_protein_abundance sibling. The graceful-degradation contract is mandated by issue #874.
        try:
            bucket, key = _cli._derived_bucket_key()
            src = f"s3://{bucket}/{key}"
        except Exception:  # noqa: BLE001
            src = _cli.DERIVED_PRODUCT_MANIFEST_ID
        summ = {
            "_live_read_error": "depmap_surfaceome_protein_abundance_read_failed",
            "_remediation": (f"Could not read DepMap Surfaceome 26Q3 paired DIA-MS product ({src}) for {target}: {e}"),
            "protein_expression_class": "data_unavailable",
            "protein_abundance_source": "data_unavailable",
            "n_cell_lines_evaluated": 0,
            "n_cell_lines_in_panel": None,
            "fraction_detected": 0.0,
            "median_log2_abundance_panel": None,
            "per_lineage_stats": [],
            "allgene_percentile": None,
            "allgene_percentile_class": "data_unavailable",
            "allgene_percentile_context": _cli._pct_context(),
            "method_version": _cli.METHOD_VERSION,
        }
        summ.update(_cli._empty_enrichment_rollup())
        return summ
