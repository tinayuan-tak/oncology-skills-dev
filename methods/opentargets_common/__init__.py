"""opentargets_common — shared read layer for the human-genetics safety leg.

All five OT 26.06 safety readers (gene_burden, clingen, clinvar, mouse_phenotype,
target_prioritisation) import from here so the S3 cache-latch discipline, the
ENSG<->symbol resolver-sidecar join, and the CLI entrypoint live in exactly ONE place.

Capabilities:
  - `read_entity(entity, columns, filter_col, filter_val)` — STREAM an OT entity's parquet
    part-files directly from S3 via a process-wide pyarrow S3FileSystem, column-projected and
    (when a target key is supplied) row-pushed-down to that one target. NO whole-directory
    download: a per-target read pulls only that target's row-groups over the wire. Definitive-vs-
    transient discipline (methods.target_id_sidecar.is_definitively_absent): only a true
    404/NoSuchKey/absent-object latches "absent" (-> empty); 403/AccessDenied (expired STS creds),
    throttling, and broken-env ImportError propagate so a live target never reports a false gap.
  - `symbol_to_ensembl()` — the OT `target.target_resolution.parquet` sidecar as an
    UPPER(hgnc symbol) -> ensembl_gene_id map (42,165 symbols). OT safety entities are
    ENSG-keyed (targetId); cards query by symbol, so every lookup joins through this.

Absence-safe (NOT failure-safe): a genuinely-absent entity/target reads as empty; a transient/
creds/broken-env failure PROPAGATES (surfaces as an honest _live_read_error, never a silent gap).
"""
from __future__ import annotations

import threading
from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for

# bucket + source-dir prefix resolved from the manifest (single source of truth);
# every OT entity key + the resolver sidecar ride off this one prefix.
OT_SOURCE_MANIFEST_ID = "opentargets-26-06"
S3_BUCKET, OT_PREFIX = bucket_prefix_for(OT_SOURCE_MANIFEST_ID)
OT_PREFIX = OT_PREFIX.rstrip("/")   # keep the existing f"{OT_PREFIX}/..." idiom byte-identical
DEFAULT_AWS_PROFILE = "cbg"

# The target-entity resolver sidecar: native_row_key (ENSG) + hgnc_primary_symbol_at_resolution.
SIDECAR_KEY = f"{OT_PREFIX}/target/target.target_resolution.parquet"

# Per-entity definitive-absent latch (module-global; None=untried, True=present, False=404).
_ENTITY_STATUS: dict[str, Optional[bool]] = {}

# Process-wide pyarrow S3FileSystem singleton (double-checked lock; region pinned to us-east-1 to
# skip the region-probe round-trip). Building one costs ~0.4s; the five OT safety cards each fire a
# read per dossier run, so we build it ONCE. Mirrors dge_deseq2._get_s3fs / depmap_common.parquet.
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as fs
                _S3FS = fs.S3FileSystem(region="us-east-1")
    return _S3FS


def _entity_prefix(entity: str) -> str:
    """S3 key prefix (bucket-relative) for an OT entity directory (parquet part-files live under it)."""
    return f"{OT_PREFIX}/{entity}"


def read_entity(entity: str, columns: Optional[list] = None,
                filter_col: Optional[str] = None, filter_val=None):
    """STREAM an OT entity's parquet part-files from S3 as one DataFrame (empty on genuine absence).

    Column-projected when `columns` is given (the parts are wide — project to what the card needs).
    When `filter_col`/`filter_val` are given, the read is ROW-pushed-down to that one key
    (e.g. targetId == ENSG...), so a per-target card pulls only that target's row-groups over the
    wire instead of the whole entity directory. No whole-file download — reads directly over the
    process-wide pyarrow S3FileSystem.

    Absence discipline (methods.target_id_sidecar.is_definitively_absent): a genuinely-absent
    entity object (NoSuchKey/404 or a pyarrow FileNotFoundError for a missing prefix) latches the
    entity absent and returns an empty frame; a transient / creds / broken-env failure PROPAGATES
    (an honest _live_read_error at the card's live-read seam, never a silent data_unavailable).
    """
    import pandas as pd
    empty = pd.DataFrame(columns=columns or [])
    if _ENTITY_STATUS.get(entity) is False:
        return empty
    try:
        import pyarrow.dataset as ds
        dataset = ds.dataset(f"{S3_BUCKET}/{_entity_prefix(entity)}",
                             filesystem=_get_s3fs(), format="parquet")
        filt = (ds.field(filter_col) == filter_val
                if (filter_col and filter_val is not None) else None)
        table = dataset.to_table(columns=columns, filter=filt)
        _ENTITY_STATUS[entity] = True
        return table.to_pandas()
    except ImportError:
        raise  # broken env (pyarrow missing) — never mask as an empty read (silent data_unavailable)
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent
        # ONLY a genuinely-absent entity (404/NoSuchKey, or pyarrow's FileNotFoundError for a
        # missing prefix) latches absent -> empty; transient/creds/env re-raise (honest gap, not silent).
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            _ENTITY_STATUS[entity] = False
            return empty
        raise


@lru_cache(maxsize=1)
def _sidecar_maps():
    """(symbol_to_ensembl, ensembl_to_symbol) from the OT target resolver sidecar.

    symbol_to_ensembl : UPPER(hgnc primary symbol) -> ensembl_gene_id (native_row_key).
    ensembl_to_symbol : ensembl_gene_id -> hgnc primary symbol.

    RAISES on read failure (broken env / transient S3 / schema drift) rather than silently returning
    empty maps: this crosswalk backs resolution for ALL FIVE OT safety-genetics cards, so an empty
    crosswalk = every target `data_unavailable` at once — the bare-`except: return {}` dead-axis bug.
    The retry-backed client absorbs transient throttling first; a genuine failure surfaces as an honest
    per-card _live_read_error via the live-read seam (never a fake honest-negative).
    """
    import pyarrow.parquet as pq  # ImportError == broken env -> propagates
    # STREAM the two resolver columns straight from S3 (column pushdown) — no whole-file download.
    # No broad except: any read failure PROPAGATES (see docstring — an empty crosswalk = dead axis).
    sc = pq.read_table(f"{S3_BUCKET}/{SIDECAR_KEY}", filesystem=_get_s3fs(),
                       columns=["native_row_key",
                                "hgnc_primary_symbol_at_resolution"]).to_pandas()
    s2e, e2s = {}, {}
    for ensg, sym in zip(sc["native_row_key"].values,
                         sc["hgnc_primary_symbol_at_resolution"].values):
        if isinstance(sym, str) and isinstance(ensg, str) and sym and ensg:
            s2e[sym.strip().upper()] = ensg.strip()
            e2s[ensg.strip()] = sym.strip()
    if not s2e:
        raise ValueError(f"OT resolver sidecar s3://{S3_BUCKET}/{SIDECAR_KEY} produced an EMPTY crosswalk")
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


def ot_cli_main(read_fn, description: str, argv=None) -> None:
    """Shared `--target [--indication] -> JSON` CLI entrypoint for the OT safety readers.

    Each reader's `_main` was byte-identical except this description string; they now delegate here.
    `read_fn` is the module's `read_*(target, indication)`; its dict is printed as indent-2 JSON.
    """
    import argparse
    import json
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--target", required=True)
    ap.add_argument("--indication", default=None)
    args = ap.parse_args(argv)
    print(json.dumps(read_fn(args.target, args.indication), indent=2, default=str))
