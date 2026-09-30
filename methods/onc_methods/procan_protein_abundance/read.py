"""procan_protein_abundance.read — live-mode dispatcher entry.

The GENERIC skills dispatcher (skills/_skills_common/_live_readers.py:_generic_dispatch) resolves
`module: procan_protein_abundance` + `entrypoint: read_target_summary` from the
cellline-protein-abundance-procan card_spec and calls read_target_summary(target=, indication=).
Returns the SAME cellline-protein-abundance card summary shape as the Gygi sibling (this is its
second, orthogonal DIA/SWATH platform). Protein abundance is a per-cell-line property — `indication`
is accepted for the dispatcher contract but NOT consumed.

Graceful-degradation contract (same as the Gygi reader): on any load failure, returns
_live_read_error + protein_expression_class=data_unavailable, so the card degrades honestly instead of
crashing the compose path. `data_unavailable` from load_and_classify (protein genuinely absent from the
ProCan panel, or symbol unresolvable) is a real coverage-gap signal; `_live_read_error` means the
SOURCE couldn't be read (infra failure) — both surface as data_unavailable class, the key disambiguates
for provenance.
"""

from __future__ import annotations

from typing import Optional

from onc_methods.target_id_sidecar import is_definitively_absent

from . import cli as _cli


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """ProCan cell-line protein-abundance distribution for a target. Protein-intrinsic — `indication`
    accepted for the generic-dispatch contract but NOT consumed."""
    try:
        return _cli.load_and_classify(target)
    except Exception as e:  # noqa: BLE001
        # Absence discipline: swallow ONLY genuine absence (missing product / 404 / NoSuchKey or
        # FileNotFoundError) as honest data_unavailable; re-raise transient / creds / broken-env so it
        # surfaces as an honest _live_read_error at the compose seam.
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        try:
            bucket, key = _cli._derived_bucket_key()
            src = f"s3://{bucket}/{key}"
        except Exception:  # noqa: BLE001
            src = _cli.DERIVED_PRODUCT_MANIFEST_ID
        return {
            "_live_read_error": "procan_protein_abundance_read_failed",
            "_remediation": (f"Could not read ProCan DIA/SWATH cell-line proteome ({src}) for {target}: {e}"),
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
