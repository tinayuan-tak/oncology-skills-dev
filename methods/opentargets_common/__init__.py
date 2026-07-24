"""opentargets_common — shared read layer for the P5 human-genetics safety leg.

Every OT 26.06 safety reader (target_prioritisation, gene_burden, clingen,
mouse_phenotype) imports from here so the S3 cache-latch discipline and the
ENSG<->symbol resolver-sidecar join live in exactly ONE place.

Two capabilities:
  - `ensure_entity_cached(entity)` — disk-latch an OT entity's parquet directory to
    ~/.cache/framework-opentargets-26-06/ ONCE per machine. Definitive-vs-transient
    latch (mirrors cptac_protein_deg/read.py): only a true 404/NoSuchKey latches
    "absent"; 403/AccessDenied (expired STS creds) stays retryable so re-auth recovers.
  - `symbol_to_ensembl()` — the OT `target.target_resolution.parquet` sidecar as an
    UPPER(hgnc symbol) -> ensembl_gene_id map (42,165 symbols). OT safety entities are
    ENSG-keyed (targetId); cards query by symbol, so every lookup joins through this.

data_unavailable-safe: any read that cannot resolve returns empty structures, never raises.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

S3_BUCKET = "onc-compbio"
OT_PREFIX = "data-catalog/sources/opentargets/26.06"
DEFAULT_AWS_PROFILE = "cbg"

CACHE_DIR = Path.home() / ".cache" / "framework-opentargets-26-06"

# The target-entity resolver sidecar: native_row_key (ENSG) + hgnc_primary_symbol_at_resolution.
SIDECAR_KEY = f"{OT_PREFIX}/target/target.target_resolution.parquet"

# Per-entity definitive-absent latch (module-global; None=untried, True=cached, False=404).
_ENTITY_STATUS: dict[str, Optional[bool]] = {}


def _boto3_client():
    import boto3
    profile = os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)
    return boto3.Session(profile_name=profile).client("s3")


def _entity_prefix(entity: str) -> str:
    """S3 key prefix for an OT entity directory (parquet part-files live under it)."""
    return f"{OT_PREFIX}/{entity}"


def ensure_entity_cached(entity: str) -> Optional[Path]:
    """Disk-latch an OT entity's parquet part-files to the local cache; return the local dir.

    Downloads ALL part-*.parquet under the entity prefix ONCE per machine. Returns None when
    the entity is genuinely absent (definitive 404) OR on a transient failure (leaves the
    status untried so a later call retries). Mirrors the definitive-vs-transient discipline in
    cptac_protein_deg/read.py — 403/AccessDenied (expired creds) must NOT poison the process.
    """
    status = _ENTITY_STATUS.get(entity)
    if status is False:
        return None
    local_dir = CACHE_DIR / entity
    if local_dir.exists() and any(local_dir.glob("*.parquet")):
        _ENTITY_STATUS[entity] = True
        return local_dir

    prefix = _entity_prefix(entity)
    try:
        s3 = _boto3_client()
        keys = []
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix + "/"):
            for obj in page.get("Contents", []):
                if obj["Key"].endswith(".parquet"):
                    keys.append(obj["Key"])
        if not keys:
            # No parquet under the prefix — a definitive absence (entity not published).
            _ENTITY_STATUS[entity] = False
            return None
        local_dir.mkdir(parents=True, exist_ok=True)
        for key in keys:
            dest = local_dir / key.rsplit("/", 1)[-1]
            if not (dest.exists() and dest.stat().st_size > 0):
                tmp = dest.with_suffix(dest.suffix + ".tmp")
                s3.download_file(S3_BUCKET, key, str(tmp))
                tmp.rename(dest)
        _ENTITY_STATUS[entity] = True
        return local_dir
    except Exception as e:  # noqa: BLE001
        # Only a definitive missing-object latches False; transient (403/creds/network) stays None.
        resp = getattr(e, "response", None)
        code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
        if code in ("404", "NoSuchKey") or e.__class__.__name__ in ("NoSuchKey", "404"):
            _ENTITY_STATUS[entity] = False
        return None


def read_entity(entity: str, columns: Optional[list] = None):
    """Read an OT entity's cached parquet part-files as one DataFrame (empty on unavailable).

    Column-projected when `columns` is given (the parts are wide — project to what the card needs).
    """
    import pandas as pd
    local_dir = ensure_entity_cached(entity)
    if local_dir is None:
        return pd.DataFrame(columns=columns or [])
    try:
        import pyarrow.parquet as pq
        import pyarrow.dataset as ds
        dataset = ds.dataset(str(local_dir), format="parquet")
        table = dataset.to_table(columns=columns) if columns else dataset.to_table()
        return table.to_pandas()
    except Exception:  # noqa: BLE001
        return pd.DataFrame(columns=columns or [])


@lru_cache(maxsize=1)
def _sidecar_maps():
    """(symbol_to_ensembl, ensembl_to_symbol) from the OT target resolver sidecar.

    symbol_to_ensembl : UPPER(hgnc primary symbol) -> ensembl_gene_id (native_row_key).
    ensembl_to_symbol : ensembl_gene_id -> hgnc primary symbol.
    Empty maps if the sidecar is unavailable (lookups then fall back to raw-ENSG only).
    """
    import pandas as pd
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local = CACHE_DIR / "target.target_resolution.parquet"
    if not (local.exists() and local.stat().st_size > 0):
        try:
            _boto3_client().download_file(S3_BUCKET, SIDECAR_KEY, str(local))
        except Exception:  # noqa: BLE001
            return {}, {}
    try:
        sc = pd.read_parquet(local, columns=["native_row_key",
                                             "hgnc_primary_symbol_at_resolution"])
    except Exception:  # noqa: BLE001
        return {}, {}
    s2e, e2s = {}, {}
    for ensg, sym in zip(sc["native_row_key"].values,
                         sc["hgnc_primary_symbol_at_resolution"].values):
        if isinstance(sym, str) and isinstance(ensg, str) and sym and ensg:
            s2e[sym.strip().upper()] = ensg.strip()
            e2s[ensg.strip()] = sym.strip()
    return s2e, e2s


def symbol_to_ensembl(target: str) -> Optional[str]:
    """Resolve an HGNC symbol (or a pass-through ENSG) to its OT ensembl_gene_id.

    Accepts either a symbol (joined via the resolver sidecar) or an ENSG (returned as-is if it
    looks like one). Returns None when unresolvable.
    """
    if not target:
        return None
    t = target.strip()
    if t.upper().startswith("ENSG"):
        return t
    s2e, _ = _sidecar_maps()
    return s2e.get(t.upper())


def ensembl_to_symbol(ensembl_gene_id: str) -> Optional[str]:
    """Reverse lookup: ensembl_gene_id -> HGNC primary symbol (None if unresolvable)."""
    if not ensembl_gene_id:
        return None
    _, e2s = _sidecar_maps()
    return e2s.get(ensembl_gene_id.strip())
