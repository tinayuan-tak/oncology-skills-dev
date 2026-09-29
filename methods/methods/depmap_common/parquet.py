"""depmap_common.parquet — column-projection loaders for the parquet derived product.

Reads from s3://onc-compbio/data-catalog/derived/depmap-26q3-parquet-v1/ via
pyarrow. Column projection means a per-target read pulls 1-2 MB from the parquet
column chunks instead of parsing the 500 MB source CSV.

Read policy (2026-08-21 data-layer hardening — parquet-storage-standard):
  - PER-TARGET reads STREAM via a pyarrow S3FileSystem with column/row-group pushdown
    (`_stream_table`): a per-gene read pulls only that column's chunks (1-2 MB) over HTTP
    range requests — NO whole-file download. This optimises the cold single-shot (a fresh
    process reading one target skips the 250-740 MB matrix download entirely). The parquet
    footer/schema is read once per (file, release) and lru-cached (`_remote_schema_names`),
    so a batch of per-target calls reuses it.
  - WHOLE-MATRIX consumers (batch precompute jobs iterating over thousands of genes) use
    `get_full_matrix_path`, which downloads once to the release-scoped local cache under
    ~/.cache/framework-depmap-<pin>-parquet/ and returns the path — the right amortisation
    when you WILL touch most of the matrix. This is the deliberate split: stream for the
    single-target read path; download-and-cache for the full-scan batch path.
  - In-process @lru_cache on target-symbol reads (same target twice in one session = instant).
  - Cache-invalidation rides the version suffix baked into the S3 prefix (parquet-v2 release).

Public API (all return pandas objects, or None when target is absent):
    get_chronos_column(target)   -> DataFrame with {ModelID, <target_col>}
    get_tpm_column(target)       -> DataFrame with {ModelID, IsDefaultEntryForModel, <target_col>}
    get_cn_column_wes(target)    -> DataFrame with {ModelConditionID, IsDefaultEntryForMC, <target_col>}
    get_cn_column_wgs(target)    -> DataFrame with same shape as WES
    get_demeter_row(target)      -> dict {ccle_id: score}
    get_maf_gene_rows(target)    -> DataFrame filtered to HugoSymbol == target

Consumers still call their method's `load_*` helpers which map these outputs into
the {ModelID -> score} dict shape the existing figure/summary code expects. The
migration to parquet is transparent to summary_stats + emit_* functions.
"""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

DEPMAP_S3_BUCKET = "onc-compbio"
# Release-scoped local cache root. Per-release subdir (framework-depmap-<pin>-parquet) so a
# multi-release caller never gets a 26q1 file back for a 26q2 request (M4). The bare 26q1 path is
# preserved as the default subdir name for backward-compat with already-cached files.
_PARQUET_CACHE_ROOT = Path.home() / ".cache"
PARQUET_CACHE_DIR = _PARQUET_CACHE_ROOT / "framework-depmap-26q1-parquet"  # legacy pre-scoping default (26q1)

# 2026-08-11 REVIEW FIX (M4 — full multi-release). Every loader accepts a `release_pin`; the S3
# prefix is now resolved PER RELEASE from the catalog manifest `depmap-{release_pin}-parquet-v1`
# via catalog_query.bucket_prefix_for (the same resolver seam sibling loaders.py already uses),
# instead of a hardcoded 26q1 constant. So a caller-supplied pin actually selects the release, and
# an UNREGISTERED release raises FileNotFoundError from the resolver — a loud failure that preserves
# the #283 guard's intent (never silently serve the wrong release) while removing its 26q1-only cap.
# Predecessor: #283 shipped _assert_release_served as a stopgap when no catalog manifest existed;
# data-catalog #331 landed depmap-26q1-parquet-v1, so resolution replaces the guard.


@lru_cache(maxsize=8)
def _release_prefix(release_pin: str = "26q3") -> str:
    """(bucket-relative) S3 key prefix for a DepMap parquet release, resolved from the catalog
    manifest depmap-{release_pin}-parquet-v1. Cached per release_pin. Raises FileNotFoundError
    (from bucket_prefix_for) if the release is not registered in the catalog — the loud,
    auditable failure that replaces #283's ValueError guard."""
    from methods.catalog_query.read import bucket_prefix_for

    _bucket, prefix = bucket_prefix_for(f"depmap-{release_pin}-parquet-v1")
    return prefix.rstrip("/")  # sibling loaders.py idiom: strip trailing slash, join with "/"


# ── Streamed pushdown read path (per-target reads; no whole-file download) ───────────────────
# Mirrors dge_deseq2/read.py + tcga_gtex_expression_distribution/read.py _get_s3fs: a process-wide
# S3FileSystem singleton (construction costs a region-probe + client init, so build it once and
# share it — pyarrow's S3FileSystem is safe for concurrent reads, which the parallel card-read pool
# relies on). Region pinned to us-east-1 (the onc-compbio bucket) to skip the region round-trip.
from methods._common.s3 import get_s3fs


def _get_s3fs():
    return get_s3fs()


def _remote_uri(filename: str, release_pin: str = "26q3") -> str:
    """`bucket/key` URI for a DepMap parquet, resolved PER release_pin from the catalog manifest.
    Calls _release_prefix, so an UNREGISTERED release raises FileNotFoundError HERE — before any S3
    op — preserving the release-pin guard (tests/methods/depmap_common/test_release_pin_guard.py)."""
    prefix = _release_prefix(release_pin)
    return f"{DEPMAP_S3_BUCKET}/{prefix}/{filename}"


@lru_cache(maxsize=32)
def _remote_schema_names(uri: str) -> tuple:
    """Column names of a remote parquet, read from the FOOTER once per (file, release) and cached.
    A wide DepMap matrix has ~19k columns; caching the footer means a batch of per-target reads
    resolves the gene column without re-fetching the footer each call."""
    import pyarrow.parquet as pq

    return tuple(pq.read_schema(uri, filesystem=_get_s3fs()).names)


def _stream_table(uri: str, columns=None, filters=None):
    """Streamed pushdown read of a remote parquet — only the requested columns' chunks (and, with
    filters, only the matching row groups) transit the wire. No whole-file download. Errors
    propagate (a missing product surfaces as pyarrow FileNotFoundError = definitive absence; a
    transient/creds error propagates so the caller's live-read seam records the real cause — we do
    NOT wrap in a broad except that would mask the two, per the reader-absence-discipline guard)."""
    import pyarrow.parquet as pq

    return pq.read_table(uri, filesystem=_get_s3fs(), columns=columns, filters=filters)


_GENE_LABEL_RE = re.compile(r'^"?([A-Za-z0-9._-]+)\s*\(\d+\)"?$')


def _log(msg: str) -> None:
    try:
        import click

        click.echo(msg, err=True)
    except ImportError:
        print(msg, file=sys.stderr)


def _local_cached(filename: str, release_pin: str = "26q3") -> Path:
    # 26q1 keeps the legacy pre-scoping cache dir (backward-compat with already-downloaded files);
    # other releases (incl. the 26q3 default) get their own subdir so files never collide (M4).
    cache_dir = (
        PARQUET_CACHE_DIR if release_pin == "26q1" else _PARQUET_CACHE_ROOT / f"framework-depmap-{release_pin}-parquet"
    )
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / filename


def _fetch_parquet(filename: str, release_pin: str = "26q3") -> Path:
    """Ensure a parquet file is available locally; download from S3 if not.
    Returns the local path. On second-session runs, this is a no-op (cache hit).
    The S3 prefix is resolved per release_pin from the catalog manifest (M4)."""
    local_path = _local_cached(filename, release_pin)
    if local_path.exists():
        return local_path

    prefix = _release_prefix(release_pin)  # catalog-resolved; raises if release unregistered
    _log(f"  Downloading parquet: s3://{DEPMAP_S3_BUCKET}/{prefix}/{filename}")
    import boto3

    s3 = boto3.client("s3")
    key = f"{prefix}/{filename}"
    try:
        s3.download_file(DEPMAP_S3_BUCKET, key, str(local_path))
    except Exception as e:
        raise FileNotFoundError(
            f"Failed to download parquet {filename} from s3://{DEPMAP_S3_BUCKET}/{key}: "
            f"{type(e).__name__}: {e}. This derived product is produced by the "
            f"depmap_parquet_precompute method, which lives in the general analysis-methods "
            f"repo (carved out of this repo under skills#2100) — run its CLI there, then "
            f"re-run this read."
        )
    _log(f"    cached to {local_path} ({local_path.stat().st_size / 1e6:.1f} MB)")
    return local_path


def _find_gene_column(schema_names, target_symbol: str) -> Optional[str]:
    """Search parquet column names for the target gene (format 'SYMBOL (entrez_id)')."""
    for col in schema_names:
        m = _GENE_LABEL_RE.match(col)
        if m and m.group(1) == target_symbol:
            return col
        if col == target_symbol:
            return col
    return None


def _read_wide_target_column(
    filename: str,
    target_symbol: str,
    id_col_hints: tuple = ("ModelID", "ModelConditionID"),
    release_pin: str = "26q3",
    *,
    source_path=None,
):
    """Read a WIDE parquet with column projection: only ID/metadata cols + the target gene.

    Streams over S3 (footer cached, only the target column's chunks transit the wire) — no
    whole-file download. `source_path` (offline test seam): a local parquet path bypasses S3."""
    import pyarrow.parquet as pq

    if source_path is not None:
        schema_names = tuple(pq.read_schema(source_path).names)
        read = lambda cols: pq.read_table(source_path, columns=cols)  # noqa: E731
    else:
        uri = _remote_uri(filename, release_pin)
        schema_names = _remote_schema_names(uri)
        read = lambda cols: _stream_table(uri, columns=cols)  # noqa: E731
    target_col = _find_gene_column(schema_names, target_symbol)
    if target_col is None:
        return None
    cols = [target_col]
    for hint in id_col_hints:
        if hint in schema_names:
            cols.append(hint)
    for extra in ("IsDefaultEntryForModel", "IsDefaultEntryForMC"):
        if extra in schema_names and extra not in cols:
            cols.append(extra)
    return read(cols).to_pandas()


@lru_cache(maxsize=128)
def get_chronos_column(target_symbol: str, release_pin: str = "26q3"):
    """CRISPR Chronos target column. Returns DataFrame or None.
    Column-projection read: ~1-2 MB (vs 564 MB CSV parse)."""
    return _read_wide_target_column(
        "CRISPRGeneEffect.parquet", target_symbol, id_col_hints=("ModelID",), release_pin=release_pin
    )


@lru_cache(maxsize=128)
def get_tpm_column(target_symbol: str, release_pin: str = "26q3"):
    """TPM target column. Returns DataFrame or None."""
    return _read_wide_target_column(
        "OmicsExpressionTPMLogp1HumanProteinCodingGenes.parquet",
        target_symbol,
        id_col_hints=("ModelID",),
        release_pin=release_pin,
    )


@lru_cache(maxsize=128)
def get_cn_column_wes(target_symbol: str, release_pin: str = "26q3"):
    """CN WES target column — LEGACY fallback (used only when the gene is absent from the
    canonical WGS matrix; see load_cn_files, #704 6a). Returns DataFrame or None."""
    return _read_wide_target_column(
        "OmicsCNGeneMC_WES.parquet", target_symbol, id_col_hints=("ModelConditionID",), release_pin=release_pin
    )


@lru_cache(maxsize=128)
def get_cn_column_wgs(target_symbol: str, release_pin: str = "26q3"):
    """CN WGS target column — the CANONICAL / primary CN read (26Q3 WES CN is legacy; see
    load_cn_files, #704 6a). Returns DataFrame or None (then falls back to legacy WES)."""
    return _read_wide_target_column(
        "OmicsCNGeneWGS.parquet", target_symbol, id_col_hints=("ModelConditionID",), release_pin=release_pin
    )


@lru_cache(maxsize=128)
def get_hotspot_mutation_column(target_symbol: str, release_pin: str = "26q3"):
    """Binary hotspot-mutation column for target_symbol from
    OmicsSomaticMutationsMatrixHotspot. Returns DataFrame with
    {ModelID, IsDefaultEntryForModel, <target_col>} or None if target absent.

    Consumed by mutation-stratified-dependency (Card 3). Values are 0.0/1.0
    per cell-line (float32-cast during precompute; downstream code casts to
    bool for the mutation-status flag).
    """
    return _read_wide_target_column(
        "OmicsSomaticMutationsMatrixHotspot.parquet", target_symbol, id_col_hints=("ModelID",), release_pin=release_pin
    )


@lru_cache(maxsize=128)
def get_damaging_mutation_column(target_symbol: str, release_pin: str = "26q3"):
    """Binary damaging (LOF) mutation column for target_symbol from
    OmicsSomaticMutationsMatrixDamaging. Same shape as get_hotspot_mutation_column.
    Broader panel (~19584 gene cols vs ~554 for hotspot).
    """
    return _read_wide_target_column(
        "OmicsSomaticMutationsMatrixDamaging.parquet", target_symbol, id_col_hints=("ModelID",), release_pin=release_pin
    )


@lru_cache(maxsize=128)
def get_matrix_column_by_model_id(filename: str, target_symbol: str, release_pin: str = "26q3", *, source_path=None):
    """Column-projection read of a wide DepMap matrix parquet, keyed on ModelID.

    Unlike get_cn_column_wgs / get_*_mutation_column (which project ModelConditionID or
    IsDefaultEntryForModel for the cell-line-distribution consumers), this projects exactly
    ['ModelID', <target_col>] — the shape functional_gene_state's MODEL arm needs to reproduce
    its raw-CSV read (which pulled usecols=['ModelID', gene_col] from the source CSV, no
    default-entry filter, last-value-wins). Returns a DataFrame with {ModelID, <target_col>} or
    None if the target gene is absent from the matrix. `filename` is the parquet product name
    (e.g. 'OmicsSomaticMutationsMatrixDamaging.parquet').
    """
    import pyarrow.parquet as pq

    if source_path is not None:
        schema_names = tuple(pq.read_schema(source_path).names)
        read = lambda cols: pq.read_table(source_path, columns=cols)  # noqa: E731
    else:
        uri = _remote_uri(filename, release_pin)
        schema_names = _remote_schema_names(uri)
        read = lambda cols: _stream_table(uri, columns=cols)  # noqa: E731
    target_col = _find_gene_column(schema_names, target_symbol)
    if target_col is None:
        return None
    if "ModelID" not in schema_names:
        return None
    return read(["ModelID", target_col]).to_pandas()


@lru_cache(maxsize=128)
def get_demeter_row(target_symbol: str, release_pin: str = "26q3"):
    """DEMETER2 RNAi row for target_symbol. Returns {ccle_id: score} dict or None.

    DEMETER2 file is TRANSPOSED (gene rows × cell-line cols) — target-level access
    is a single row (~700 float32 values, ~3 KB). Uses filter pushdown on the
    gene_symbol column added at precompute time.
    """
    # Streamed filter pushdown on the sorted-by-gene_symbol parquet — only the target row's
    # row group transits the wire (the D2 product is transposed: gene rows × cell-line cols).
    table = _stream_table(
        _remote_uri("D2_combined_gene_dep_scores.parquet", release_pin), filters=[("gene_symbol", "=", target_symbol)]
    )
    if table.num_rows == 0:
        return None
    df = table.to_pandas()
    row = df.iloc[0]
    result = {}
    for col in df.columns:
        if col in ("gene_label", "gene_symbol"):
            continue
        val = row[col]
        # Skip NaN
        if val is not None and not (isinstance(val, float) and val != val):
            result[col] = float(val)
    return result


@lru_cache(maxsize=128)
def get_maf_gene_rows(target_symbol: str, release_pin: str = "26q3"):
    """MAF rows matching HugoSymbol == target_symbol. Returns DataFrame.

    Uses filter pushdown on the sorted-by-HugoSymbol parquet; row groups without
    the target gene are skipped entirely. Drops per-query read from ~738 MB CSV
    parse to <10 MB parquet slice.
    """
    table = _stream_table(
        _remote_uri("OmicsSomaticMutations.parquet", release_pin), filters=[("HugoSymbol", "=", target_symbol)]
    )
    return table.to_pandas()


@lru_cache(maxsize=1)
def get_maf_n_cell_lines_total(release_pin: str = "26q3") -> int:
    """Return the count of distinct ModelIDs in the MAF (denominator for mutation rate).

    Reads only the ModelID column across the whole MAF parquet and takes nunique.
    ~1500 KB (single column, ~1.5M rows, dictionary-encoded) instead of parsing the
    full 738 MB CSV. Cached (maxsize=1) since the denominator is a per-release
    constant, not per-target.
    """
    uri = _remote_uri("OmicsSomaticMutations.parquet", release_pin)
    # Also apply IsDefaultEntryForModel filter to match the CSV path's semantics
    filters = [("IsDefaultEntryForModel", "=", "Yes")]
    try:
        table = _stream_table(uri, columns=["ModelID"], filters=filters)
    except Exception:  # absence-discipline: exempt -- pyarrow filter-pushdown version fallback, not S3-absence masking (a real read error re-raises on the retry below)
        # Filter pushdown on a categorical column may fail on some pyarrow versions;
        # fall back to reading the two columns + filtering in pandas.
        table = _stream_table(uri, columns=["ModelID", "IsDefaultEntryForModel"])
        df = table.to_pandas()
        df = df[df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])]
        return int(df["ModelID"].nunique())
    return int(table.column("ModelID").to_pandas().nunique())


def get_full_matrix_path(filename: str, release_pin: str = "26q3") -> Path:
    """Return the local-cached path for a parquet filename, downloading from S3
    if not already cached. Public entrypoint for consumers that need the FULL
    matrix (not just a per-target column projection) — e.g. batch precompute
    jobs that iterate across thousands of genes and would waste RTTs on per-gene
    column reads.

    The local-disk cache (release-scoped) persists across process runs; the first
    call in a session (or after cache eviction) downloads once from S3, all
    subsequent calls are no-ops. Callers should use pyarrow.parquet or pandas
    directly on the returned path.
    """
    return _fetch_parquet(filename, release_pin)


def clear_all_parquet_caches() -> None:
    """Clear in-process LRU caches. Local-disk cache persists."""
    get_chronos_column.cache_clear()
    get_tpm_column.cache_clear()
    get_cn_column_wes.cache_clear()
    get_cn_column_wgs.cache_clear()
    get_demeter_row.cache_clear()
    get_maf_gene_rows.cache_clear()
    get_maf_n_cell_lines_total.cache_clear()
    get_hotspot_mutation_column.cache_clear()
    get_damaging_mutation_column.cache_clear()
    get_matrix_column_by_model_id.cache_clear()
    _remote_schema_names.cache_clear()  # streamed-read footer/schema cache
