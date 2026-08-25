"""gdsc_drug_activity.read — live-mode dispatcher entry.

The GENERIC skills dispatcher (skills/_skills_common/_live_readers.py:_generic_dispatch) resolves
`module: gdsc_drug_activity` + `entrypoint: read_target_summary` from the gdsc-drug-activity card_spec
and calls read_target_summary(target=, indication=). GDSC drug-activity is a per-gene (pan-cancer)
property — `indication` is accepted for the dispatcher contract but NOT consumed (there is no
indication/lineage axis; cell lines are Sanger SIDM ids with no OncoTree crosswalk).

Graceful-degradation contract (same as the ProCan/PRISM readers): on any load failure, returns
_live_read_error + gdsc_activity_class=data_unavailable, so the card degrades honestly instead of
crashing the compose path. `no_compounds_found` from load_and_classify (the symbol matches no GDSC
putative-target token) is a REAL measured weak-negative — DISTINCT from `data_unavailable` (the SOURCE
couldn't be read, an infra failure); both surface a class, the key disambiguates for provenance.
"""
from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """GDSC (Sanger GDSC1+GDSC2) per-gene drug-activity summary for a target. Pan-cancer; `indication`
    accepted for the generic-dispatch contract but NOT consumed."""
    try:
        return _cli.load_and_classify(target)
    except Exception as e:  # noqa: BLE001 — any load failure -> graceful data_unavailable
        try:
            bucket, key = _cli._derived_bucket_key()
            src = f"s3://{bucket}/{key}"
        except Exception:  # noqa: BLE001
            src = _cli.DERIVED_PRODUCT_MANIFEST_ID
        return {
            "_live_read_error": "gdsc_drug_activity_read_failed",
            "_remediation": (
                f"Could not read GDSC per-gene drug-activity ({src}) for {target}: {e}"),
            "gdsc_activity_class": _cli.CLASS_DATA_UNAVAILABLE,
            "n_drugs": 0,
            "n_cell_lines_tested": 0,
            "median_ln_ic50": None,
            "median_auc": None,
            "min_median_ln_ic50": None,
            "most_sensitive_drug_name": None,
            "datasets": None,
            "looks_like_gene_symbol": None,
            "gdsc_target_token": None,
            "resolved_via": None,
            "method_version": _cli.METHOD_VERSION,
        }
