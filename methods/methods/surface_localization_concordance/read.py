"""surface_localization_concordance.read — live-mode dispatcher entry.

The GENERIC skills dispatcher (skills/_skills_common/_live_readers.py:_generic_dispatch) resolves
`module: surface_localization_concordance` + `entrypoint: read_target_summary` from the
surface-localization-concordance card_spec and calls read_target_summary(target=, indication=).
Returns the verdict-INERT surface-localization concordance summary (see cli.py).

Both arms are target-grain — `indication` is accepted for the dispatcher contract but NOT consumed.

Graceful-degradation contract: neither child reader raises on a genuine coverage gap (each returns
data_unavailable / a measured negative), which flow into classification normally. A transient/infra
fault propagates out of load_and_classify and is caught here, degrading to `_live_read_error` +
surface_context_concordance_class=insufficient — an honest infra breadcrumb, never a silent dead axis.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """Cell-line ↔ orthogonal surface-localization concordance for a target.
    Target-grain — `indication` accepted for the generic-dispatch contract but NOT consumed."""
    try:
        return _cli.load_and_classify(target)
    except Exception as e:  # noqa: BLE001  # absence-discipline: exempt -- benign: the card is verdict-INERT (interpretation=rules_pending, drives no nomination gate), and this handler is the generic-dispatch graceful-degradation seam, NOT an S3-read masker (the try body performs NO direct object read — it joins two child readers that each already practice absence discipline: a genuine coverage gap returns data_unavailable WITHOUT raising, and a transient/creds/broken-env fault PROPAGATES here). It emits the disambiguating `_live_read_error` breadcrumb so an infra fault is an honest _live_read_error, never a dead axis. Mirrors the depmap_surfaceome_protein_abundance sibling.
        summ = _cli._empty("surface_localization_concordance_read_failed")
        summ["_live_read_error"] = "surface_localization_concordance_read_failed"
        summ["_remediation"] = (
            f"Could not join the DepMap Surfaceome 26Q3 enrichment read and the CSPA/HPA "
            f"surface-confirmation read for {target}: {e}"
        )
        return summ
