"""hpa_subcellular_location.read — per-target HPA immunofluorescence surface-residency confirmation.

An ORTHOGONAL cell-surface confirmation leg for surface-modality-fit: the framework already confirms
surface residency from CSPA mass-spec (cspa_surface_confirmation); this reads HPA IMMUNOFLUORESCENCE
subcellular location (a different wet-lab modality — microscopy vs MS). MS + IF agreeing raises
ADC/TCE antigen-reality confidence; disagreeing is a flag. Reads the per-gene rollup
hpa-subcellular-location-per-gene-v1 (gene-symbol keyed).

surface_if_location_class (from the product; graded — plasma membrane in MAIN > only in the union):
  plasma_membrane_main        'Plasma membrane' is a MAIN IF location — strong IF surface confirmation
  plasma_membrane_additional  present only as a secondary/additional location
  intracellular_only          IF location(s) present, none plasma-membrane — a MEASURED non-surface call
  location_unavailable        no HPA IF subcellular location (coverage gap, NOT non-surface)

Measured-vs-null: intracellular_only is a MEASURED non-surface call (a weak opposing prior for a
biologics modality); location_unavailable is a coverage gap that NEVER opposes. NB distinct from the
HPA IHC normal-tissue BREADTH consumed by normal-tissue-liability (a different HPA column).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

PRODUCT_MANIFEST_ID = "hpa-subcellular-location-per-gene-v1"
METHOD_VERSION = "0.1.0"


def _read_hpa_row(target: str) -> Optional[dict]:
    """Pushdown-read the per-gene HPA subcellular-location rollup for one gene symbol. None if absent."""
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs

        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=fs.S3FileSystem(),
            filters=[("gene_symbol", "=", (target or "").strip().upper())],
        )
    except Exception as e:  # noqa: BLE001
        # Genuine product-absence (FileNotFoundError / NoSuchKey / 404) → None (location_unavailable).
        # A transient/creds/broken-env error must NOT be masked as "gene absent" — re-raise it.
        from methods.target_id_sidecar import is_definitively_absent

        if not (isinstance(e, FileNotFoundError) or is_definitively_absent(e)):
            raise
        return None
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def read_surface_if_location(target: str, hpa_row: Optional[dict] = None) -> dict:
    """Per-target HPA IF surface-residency confirmation. hpa_row may be injected for tests.

    A target absent from HPA's IF subcellular-location data returns location_unavailable
    (coverage gap) — NOT a non-surface call."""
    sym = (target or "").strip().upper()
    row = hpa_row if hpa_row is not None else _read_hpa_row(sym)
    if row is None:
        return {
            "surface_if_location_class": "location_unavailable",
            "is_plasma_membrane": False,
            "plasma_membrane_is_main": False,
            "subcellular_main_location": None,
            "subcellular_all_location": None,
            "if_reliability": None,
            "n_locations": 0,
            "method_version": METHOD_VERSION,
            "_data_source": PRODUCT_MANIFEST_ID,
            "_data_note": f"{target!r} has no HPA IF subcellular location (coverage gap, not non-surface)",
        }
    return {
        "surface_if_location_class": row.get("surface_if_location_class", "location_unavailable"),
        "is_plasma_membrane": bool(row.get("is_plasma_membrane", False)),
        "plasma_membrane_is_main": bool(row.get("plasma_membrane_is_main", False)),
        "subcellular_main_location": row.get("subcellular_main_location"),
        "subcellular_all_location": row.get("subcellular_all_location"),
        "if_reliability": row.get("if_reliability"),
        "n_locations": int(row.get("n_locations") or 0),
        "method_version": METHOD_VERSION,
        "_data_source": PRODUCT_MANIFEST_ID,
    }
