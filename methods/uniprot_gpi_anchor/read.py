"""uniprot_gpi_anchor.read — per-target GPI-anchor lookup from UniProt curated LIPID features.

The live provider that lets the surface-accessibility gate RESCUE GPI-anchored antigens (MSLN/FOLR1/
CD59/ALPP) that TMbed predicted topology calls `no_transmembrane` (a GPI anchor has no membrane-
spanning segment, so 1D topology cannot see it). GPI-anchored proteins ARE displayed on the outer
leaflet and ARE biologics targets — this reader supplies the curated fact the prediction lacks.

CONSUMES the DERIVED product uniprot-gpi-anchored-v1 (payload + resolver sidecar), NOT the DAT (methods
read derived manifests; the DAT parse is the derive step). The payload is POSITIVE-ONLY: it lists only
GPI-anchored ACs. A target ABSENT from it is a real measured negative (reviewed-human UniProt is
complete for curated GPI annotation), NOT a coverage gap — is_gpi_anchored=False. data_unavailable is
reserved for "derived product could not be loaded."

Runtime: S3 get → lru_cache index → single lookup per call. Symbol→AC via the sidecar (never a source
symbol column — deprecated-symbol risk), same discipline as the CSPA + topology readers.
"""
from __future__ import annotations

import io
import os
from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for, sidecar_bucket_key_for

METHOD_VERSION = "0.1.0"
DERIVED_MANIFEST_ID = "uniprot-gpi-anchored-v1"
# payload + resolver-sidecar keys resolved from the data-catalog manifest (single
# source of truth): s3_uri is the payload; target_resolution.sidecar_s3_uri the sidecar.
S3_BUCKET, PAYLOAD_KEY = bucket_key_for(DERIVED_MANIFEST_ID)
_, SIDECAR_KEY = sidecar_bucket_key_for(DERIVED_MANIFEST_ID)
DEFAULT_AWS_PROFILE = "cbg"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _read_parquet(path_or_none, bucket, key):
    import pandas as pd
    if path_or_none is not None:
        return pd.read_parquet(path_or_none)
    _ensure_aws_profile()
    # shared client: AWS_PROFILE=cbg + adaptive-retry Config (absorbs transient S3 throttling on
    # batch reads), mirroring uniprot_protein_features — a bare boto3.client had NO retry backoff.
    from methods.target_id_sidecar import s3_client
    body = s3_client().get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


@lru_cache(maxsize=1)
def _load_indexed(payload_path: Optional[str] = None, sidecar_path: Optional[str] = None):
    """Build (gpi_acs:set, gpi_note_by_ac:dict, symbol_to_ac:dict). None if payload GENUINELY absent."""
    try:
        payload = _read_parquet(payload_path, S3_BUCKET, PAYLOAD_KEY)
    except Exception as e:  # noqa: BLE001
        # Genuine 404/NoSuchKey → None (honest data_unavailable). A transient-S3 / creds / broken-env
        # error must NOT be masked as "product unavailable" (would silently flip every GPI target to
        # is_gpi_anchored=None) — re-raise (lru_cache never memoizes the raise, so it is retried).
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
        return None
    gpi_acs = set()
    gpi_note_by_ac = {}
    for rec in payload.to_dict("records"):
        ac = str(rec.get("uniprot_ac", "")).strip()
        if ac:
            gpi_acs.add(ac)
            gpi_note_by_ac[ac] = rec.get("gpi_lipid_note")
    symbol_to_ac = {}
    try:
        sc = _read_parquet(sidecar_path, S3_BUCKET, SIDECAR_KEY)
        sym_col = "hgnc_primary_symbol_at_resolution"
        if sym_col in sc.columns and "native_row_key" in sc.columns:
            for sym, ac in zip(sc[sym_col].values, sc["native_row_key"].values):
                if isinstance(sym, str) and sym.strip() and isinstance(ac, str):
                    symbol_to_ac[sym.strip().upper()] = ac.strip()
    except Exception as e:  # noqa: BLE001 — sidecar genuinely-absent: AC lookups still work.
        # A transient/creds/broken-env failure must NOT be masked (would drop symbol→AC for the whole
        # batch AND poison the lru_cache with a partial index) — re-raise it.
        from methods.target_id_sidecar import is_definitively_absent
        if not is_definitively_absent(e):
            raise
    return gpi_acs, gpi_note_by_ac, symbol_to_ac


def read_gpi_anchor(target: str, indication: Optional[str] = None,
                    payload_path: Optional[str] = None,
                    sidecar_path: Optional[str] = None) -> dict:
    """GPI-anchor status for `target` (HGNC symbol or UniProt AC).

    is_gpi_anchored True/False is a real measured call (positive-only payload over complete reviewed-
    human UniProt); is_gpi_anchored=None ONLY when the derived product couldn't load."""
    idx = _load_indexed(payload_path, sidecar_path)
    if idx is None:
        return {"is_gpi_anchored": None, "gpi_lipid_note": None, "uniprot_ac": None,
                "method_version": METHOD_VERSION, "_data_source": DERIVED_MANIFEST_ID,
                "_data_note": "uniprot_gpi_derived_product_unavailable"}
    gpi_acs, gpi_note_by_ac, symbol_to_ac = idx
    key = target.strip()
    ac = key if key in gpi_acs else symbol_to_ac.get(key.upper())
    # A symbol that resolves via the sidecar but isn't in gpi_acs is a real not-GPI; a symbol with no
    # sidecar hit at all also reads not-GPI (reviewed-human curated GPI set is complete).
    is_gpi = ac in gpi_acs if ac else False
    return {
        "is_gpi_anchored": is_gpi,
        "gpi_lipid_note": gpi_note_by_ac.get(ac) if is_gpi else None,
        "uniprot_ac": ac if is_gpi else None,
        "method_version": METHOD_VERSION,
        "_data_source": DERIVED_MANIFEST_ID,
    }
