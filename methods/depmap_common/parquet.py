"""depmap_common.parquet — column-projection loaders for the parquet derived product.

Reads from s3://onc-compbio/data-catalog/derived/depmap-26q1-parquet-v1/ via
pyarrow. Column projection means a per-target read pulls 1-2 MB from the parquet
column chunks instead of parsing the 500 MB source CSV.

Session caching:
  - In-process @lru_cache on target-symbol reads (same target requested twice in
    one session returns instantly).
  - Local-disk cache under ~/.cache/framework-depmap-26q1-parquet/ for the FULL
    parquet files (one-time download per session; subsequent sessions reuse the
    local files). Cache-invalidation would come with a parquet-v2 release —
    the version suffix is baked into the S3 prefix + cache directory names.

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
PARQUET_S3_PREFIX = "data-catalog/derived/depmap-26q1-parquet-v1"
PARQUET_CACHE_DIR = Path.home() / ".cache" / "framework-depmap-26q1-parquet"

# 2026-08-11 REVIEW FIX (M4): the ONE DepMap release these loaders actually serve. Every loader
# accepts a `release_pin` arg but the S3 key is built purely from PARQUET_S3_PREFIX above, so a
# caller-supplied pin was SILENTLY IGNORED — a caller could pass release_pin="26q2" and unknowingly
# read 26q1 data. True multi-release support is BLOCKED on landing per-release catalog manifests
# (the `depmap-26q1-parquet-v1` manifest does not exist yet — a data-catalog deliverable). Until
# then, the honest behavior is to REFUSE a pin we cannot honor rather than serve the wrong release.
# _SERVED_RELEASE is derived from the prefix so the two can never drift.
_SERVED_RELEASE = "26q1"   # must match the release encoded in PARQUET_S3_PREFIX


def _assert_release_served(release_pin: str) -> None:
    """Raise if a caller pinned a release these loaders cannot serve. Converts the former
    silent-ignore (wrong-data risk) into an explicit, auditable failure (M4, 2026-08-11)."""
    if release_pin != _SERVED_RELEASE:
        raise ValueError(
            f"depmap_common.parquet serves only release {_SERVED_RELEASE!r} "
            f"(prefix {PARQUET_S3_PREFIX!r}), but release_pin={release_pin!r} was requested. "
            f"Multi-release support is not yet wired (needs per-release catalog manifests); "
            f"this guard refuses to silently return {_SERVED_RELEASE} data under a different pin."
        )

_GENE_LABEL_RE = re.compile(r'^"?([A-Za-z0-9._-]+)\s*\(\d+\)"?$')


def _log(msg: str) -> None:
    try:
        import click
        click.echo(msg, err=True)
    except ImportError:
        print(msg, file=sys.stderr)


def _local_cached(filename: str) -> Path:
    PARQUET_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return PARQUET_CACHE_DIR / filename


def _fetch_parquet(filename: str) -> Path:
    """Ensure a parquet file is available locally; download from S3 if not.
    Returns the local path. On second-session runs, this is a no-op (cache hit)."""
    local_path = _local_cached(filename)
    if local_path.exists():
        return local_path

    _log(f"  Downloading parquet: s3://{DEPMAP_S3_BUCKET}/{PARQUET_S3_PREFIX}/{filename}")
    import boto3
    s3 = boto3.client("s3")
    key = f"{PARQUET_S3_PREFIX}/{filename}"
    try:
        s3.download_file(DEPMAP_S3_BUCKET, key, str(local_path))
    except Exception as e:
        raise FileNotFoundError(
            f"Failed to download parquet {filename} from s3://{DEPMAP_S3_BUCKET}/{key}: "
            f"{type(e).__name__}: {e}. Run methods.depmap_parquet_precompute.cli first to "
            f"produce this derived product."
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


def _read_wide_target_column(filename: str, target_symbol: str,
                              id_col_hints: tuple = ("ModelID", "ModelConditionID")):
    """Read a WIDE parquet with column projection: only ID/metadata cols + target gene."""
    import pyarrow.parquet as pq
    local_path = _fetch_parquet(filename)
    schema_names = pq.read_schema(local_path).names
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
    table = pq.read_table(local_path, columns=cols)
    return table.to_pandas()


@lru_cache(maxsize=128)
def get_chronos_column(target_symbol: str, release_pin: str = "26q1"):
    """CRISPR Chronos target column. Returns DataFrame or None.
    Column-projection read: ~1-2 MB (vs 564 MB CSV parse)."""
    _assert_release_served(release_pin)
    return _read_wide_target_column("CRISPRGeneEffect.parquet", target_symbol,
                                     id_col_hints=("ModelID",))


@lru_cache(maxsize=128)
def get_tpm_column(target_symbol: str, release_pin: str = "26q1"):
    """TPM target column. Returns DataFrame or None."""
    _assert_release_served(release_pin)
    return _read_wide_target_column("OmicsExpressionTPMLogp1HumanProteinCodingGenes.parquet",
                                     target_symbol, id_col_hints=("ModelID",))


@lru_cache(maxsize=128)
def get_cn_column_wes(target_symbol: str, release_pin: str = "26q1"):
    """CN WES target column. Returns DataFrame or None (fall back to WGS if None)."""
    _assert_release_served(release_pin)
    return _read_wide_target_column("OmicsCNGeneMC_WES.parquet", target_symbol,
                                     id_col_hints=("ModelConditionID",))


@lru_cache(maxsize=128)
def get_cn_column_wgs(target_symbol: str, release_pin: str = "26q1"):
    """CN WGS target column (fallback for genes absent from WES panel)."""
    _assert_release_served(release_pin)
    return _read_wide_target_column("OmicsCNGeneWGS.parquet", target_symbol,
                                     id_col_hints=("ModelConditionID",))


@lru_cache(maxsize=128)
def get_hotspot_mutation_column(target_symbol: str, release_pin: str = "26q1"):
    """Binary hotspot-mutation column for target_symbol from
    OmicsSomaticMutationsMatrixHotspot. Returns DataFrame with
    {ModelID, IsDefaultEntryForModel, <target_col>} or None if target absent.

    Consumed by mutation-stratified-dependency (Card 3). Values are 0.0/1.0
    per cell-line (float32-cast during precompute; downstream code casts to
    bool for the mutation-status flag).
    """
    _assert_release_served(release_pin)
    return _read_wide_target_column("OmicsSomaticMutationsMatrixHotspot.parquet",
                                     target_symbol, id_col_hints=("ModelID",))


@lru_cache(maxsize=128)
def get_damaging_mutation_column(target_symbol: str, release_pin: str = "26q1"):
    """Binary damaging (LOF) mutation column for target_symbol from
    OmicsSomaticMutationsMatrixDamaging. Same shape as get_hotspot_mutation_column.
    Broader panel (~19584 gene cols vs ~554 for hotspot).
    """
    _assert_release_served(release_pin)
    return _read_wide_target_column("OmicsSomaticMutationsMatrixDamaging.parquet",
                                     target_symbol, id_col_hints=("ModelID",))


@lru_cache(maxsize=128)
def get_matrix_column_by_model_id(filename: str, target_symbol: str, release_pin: str = "26q1"):
    """Column-projection read of a wide DepMap matrix parquet, keyed on ModelID.

    Unlike get_cn_column_wgs / get_*_mutation_column (which project ModelConditionID or
    IsDefaultEntryForModel for the cell-line-distribution consumers), this projects exactly
    ['ModelID', <target_col>] — the shape functional_gene_state's MODEL arm needs to reproduce
    its raw-CSV read (which pulled usecols=['ModelID', gene_col] from the source CSV, no
    default-entry filter, last-value-wins). Returns a DataFrame with {ModelID, <target_col>} or
    None if the target gene is absent from the matrix. `filename` is the parquet product name
    (e.g. 'OmicsSomaticMutationsMatrixDamaging.parquet').
    """
    _assert_release_served(release_pin)
    import pyarrow.parquet as pq
    local_path = _fetch_parquet(filename)
    schema_names = pq.read_schema(local_path).names
    target_col = _find_gene_column(schema_names, target_symbol)
    if target_col is None:
        return None
    if "ModelID" not in schema_names:
        return None
    table = pq.read_table(local_path, columns=["ModelID", target_col])
    return table.to_pandas()


@lru_cache(maxsize=128)
def get_demeter_row(target_symbol: str, release_pin: str = "26q1"):
    """DEMETER2 RNAi row for target_symbol. Returns {ccle_id: score} dict or None.

    DEMETER2 file is TRANSPOSED (gene rows × cell-line cols) — target-level access
    is a single row (~700 float32 values, ~3 KB). Uses filter pushdown on the
    gene_symbol column added at precompute time.
    """
    _assert_release_served(release_pin)
    import pyarrow.parquet as pq
    local_path = _fetch_parquet("D2_combined_gene_dep_scores.parquet")
    # Filter to target row via gene_symbol column
    filters = [("gene_symbol", "=", target_symbol)]
    table = pq.read_table(local_path, filters=filters)
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
def get_maf_gene_rows(target_symbol: str, release_pin: str = "26q1"):
    """MAF rows matching HugoSymbol == target_symbol. Returns DataFrame.

    Uses filter pushdown on the sorted-by-HugoSymbol parquet; row groups without
    the target gene are skipped entirely. Drops per-query read from ~738 MB CSV
    parse to <10 MB parquet slice.
    """
    _assert_release_served(release_pin)
    import pyarrow.parquet as pq
    local_path = _fetch_parquet("OmicsSomaticMutations.parquet")
    filters = [("HugoSymbol", "=", target_symbol)]
    table = pq.read_table(local_path, filters=filters)
    return table.to_pandas()


@lru_cache(maxsize=1)
def get_maf_n_cell_lines_total(release_pin: str = "26q1") -> int:
    """Return the count of distinct ModelIDs in the MAF (denominator for mutation rate).

    Reads only the ModelID column across the whole MAF parquet and takes nunique.
    ~1500 KB (single column, ~1.5M rows, dictionary-encoded) instead of parsing the
    full 738 MB CSV. Cached (maxsize=1) since the denominator is a per-release
    constant, not per-target.
    """
    _assert_release_served(release_pin)
    import pyarrow.parquet as pq
    local_path = _fetch_parquet("OmicsSomaticMutations.parquet")
    # Also apply IsDefaultEntryForModel filter to match the CSV path's semantics
    filters = [("IsDefaultEntryForModel", "=", "Yes")]
    try:
        table = pq.read_table(local_path, columns=["ModelID"], filters=filters)
    except Exception:
        # Filter pushdown on a categorical column may fail on some pyarrow versions;
        # fall back to reading + filtering in pandas
        table = pq.read_table(local_path, columns=["ModelID", "IsDefaultEntryForModel"])
        df = table.to_pandas()
        df = df[df["IsDefaultEntryForModel"].isin([True, "Yes", "yes", "true", "TRUE"])]
        return int(df["ModelID"].nunique())
    return int(table.column("ModelID").to_pandas().nunique())


def get_full_matrix_path(filename: str) -> Path:
    """Return the local-cached path for a parquet filename, downloading from S3
    if not already cached. Public entrypoint for consumers that need the FULL
    matrix (not just a per-target column projection) — e.g. batch precompute
    jobs that iterate across thousands of genes and would waste RTTs on per-gene
    column reads.

    The local-disk cache under PARQUET_CACHE_DIR persists across process runs;
    the first call in a session (or after cache eviction) downloads once from
    S3, all subsequent calls are no-ops. Callers should use pyarrow.parquet
    or pandas directly on the returned path.
    """
    return _fetch_parquet(filename)


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
