"""depmap_common.loaders — cached loaders for DepMap metadata tables.

Every method that needs Model.csv / ModelCondition.csv / sample_info.csv should
import from here rather than fetching independently. In-process @lru_cache means
compose_dashboard's 8-card run drops from 8× Model.csv fetches to 1×.

Design decisions:
  - Small metadata tables (~1 MB each) stay as CSV (converting to Parquet buys
    nothing when the file needs to be fully in memory anyway).
  - Cache key is (release_pin,) — same file across all methods in a session.
  - Local-cache fallback checked first, then S3, then structured error.
  - Clearing the cache is exposed via clear_all_caches() for test scenarios.
"""

from __future__ import annotations

import sys
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from methods.catalog_query.read import bucket_prefix_for

# bucket + source-dir prefixes resolved from the data-catalog manifests (single
# source of truth). rstrip('/') keeps the existing `f"{PREFIX}/File.csv"` concat
# idiom byte-identical (bucket_prefix_for returns the dir WITH its trailing slash).
DEPMAP_CRISPR_MANIFEST_ID = "depmap-consortium-26q1"
DEPMAP_RNAI_MANIFEST_ID = "depmap-consortium-26q1-rnai"
DEPMAP_S3_BUCKET, _CRISPR_PREFIX = bucket_prefix_for(DEPMAP_CRISPR_MANIFEST_ID)
DEPMAP_S3_PREFIX_CRISPR = _CRISPR_PREFIX.rstrip("/")
DEPMAP_S3_PREFIX_RNAI = bucket_prefix_for(DEPMAP_RNAI_MANIFEST_ID)[1].rstrip("/")

# Local-cache fallback paths (checked in order)
DEPMAP_LOCAL_FALLBACK_DIRS = [
    Path("/data/depmap/26q1"),
    Path.home() / "depmap-26q1",
]

# Session-persistent disk-cache location — populated on first fetch; subsequent
# session runs read locally without hitting S3. Auto-created if absent.
SESSION_CACHE_DIR = Path.home() / ".cache" / "framework-depmap-26q1"


def _log(msg: str) -> None:
    """Emit a fetch-progress line to stderr. Uses click if available, plain print otherwise."""
    try:
        import click

        click.echo(msg, err=True)
    except ImportError:
        print(msg, file=sys.stderr)


def _fetch_csv(
    key: str,
    local_filename: str,
    release_pin: str = "26q1",
    bucket: str = DEPMAP_S3_BUCKET,
):
    """Core fetcher: local cache → session cache → S3. Returns pandas DataFrame.

    Order of resolution:
      1. Session cache at ~/.cache/framework-depmap-26q1/{local_filename}
         (created on first fetch; cheap disk read on subsequent).
      2. Legacy local-cache directories (DEPMAP_LOCAL_FALLBACK_DIRS).
      3. S3 fetch → parse → write to session cache for next time.

    Raises: FileNotFoundError with structured message if S3 fetch fails.
    """
    import pandas as pd

    # 1. Session cache (fastest)
    session_path = SESSION_CACHE_DIR / release_pin / local_filename
    if session_path.exists():
        _log(f"  Loading cached {session_path}")
        return pd.read_csv(session_path)

    # 2. Legacy local caches
    for fallback_dir in DEPMAP_LOCAL_FALLBACK_DIRS:
        candidate = fallback_dir / local_filename
        if candidate.exists():
            _log(f"  Using local DepMap cache: {candidate}")
            return pd.read_csv(candidate)

    # 3. S3 fetch
    try:
        import boto3
    except ImportError as e:
        raise FileNotFoundError(f"Cannot fetch {local_filename}: boto3 not installed and no local cache. Detail: {e}")

    _log(f"  Fetching s3://{bucket}/{key}")
    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read()
    except Exception as e:
        raise FileNotFoundError(
            f"S3 fetch failed for s3://{bucket}/{key}: {type(e).__name__}: {e}. "
            f"Check AWS credentials + bucket accessibility."
        )

    # Populate session cache for next time (idempotent; ignore write failures)
    try:
        session_path.parent.mkdir(parents=True, exist_ok=True)
        session_path.write_bytes(body)
        _log(f"  Cached to {session_path}")
    except OSError as e:
        _log(f"  Warning: could not write session cache ({e}); continuing")

    return pd.read_csv(BytesIO(body))


@lru_cache(maxsize=8)
def load_model_csv(release_pin: str = "26q1"):
    """Load DepMap Model.csv (cell-line metadata: ModelID, OncotreeLineage, CCLEName, etc.).

    Small file (~922 KB); process-lifetime cached. Compose_dashboard's 8-card run
    calls this 8 times, but only the first triggers S3 (or local disk) — subsequent
    calls return the same DataFrame in <1ms.

    Returns: pandas DataFrame with columns including ModelID, OncotreeLineage,
    CCLEName, OncotreePrimaryDisease, OncotreeSubtype.

    Raises: FileNotFoundError if not fetchable.
    """
    key = f"{DEPMAP_S3_PREFIX_CRISPR}/Model.csv"
    return _fetch_csv(key, "Model.csv", release_pin)


def model_metadata_by_id(model_df, model_id_col: str | None = None) -> dict:
    """{model_id -> metadata dict} from a Model.csv frame, with every MISSING value as None.

    The frame boundary. Use this instead of `{row[id]: row.to_dict() for _, row in df.iterrows()}`,
    which is what every caller used to write and which ships `float('nan')` into JSON:

        a missing value in an OBJECT-dtype (string) column IS float('nan'), not None or "".

    So `row.to_dict()` puts a float NaN under a key like "CCLEName" — a cell-line *name* — and json.dumps
    emits the bare token `NaN`, which is not valid JSON. Measured over the 504-package corpus: 119,536
    leaves in 496 packages, 98.2% of every non-finite value emitted by the framework, all of it from
    `per_line_concordance[].ccle_name` + `.lineage` in the crispr-rnai concordance card.

    ★ The target is None, deliberately NOT "" or "unknown", because the consumers already declare their
    own fallbacks and None ACTIVATES them rather than pre-empting them:

        lineage = meta.get("OncotreeLineage") or meta.get("lineage") or ... or "unknown"

    That chain reads as a working guard and cannot fire, because **NaN is truthy in Python** — the first
    term wins and `lineage` becomes nan. Substituting a literal default here would fix the JSON while
    permanently hiding which card wanted "unknown" and which wanted null; substituting None lets each
    caller keep deciding. (Same family as the recorded `pd.isna(inf) is False` trap: the sentinel is a
    value with ordinary value semantics, so a guard written for absence never sees it.)

    ⚠️ The predicate here means MISSING, not non-finite, and that is the correct choice: a ±Inf in a
    numeric metadata column is a value, not a gap, and silently nulling it would destroy data. If one ever
    appears it must be refused at the writer (`allow_nan=False`), not laundered here. That distinction is
    now structural rather than a comment: `cell_absence` keeps `missing` and `non_finite` as separate
    states, and `plain_row()` normalises only the former, leaving ±Inf strictly alone.

    Assumes scalar columns, which Model.csv/ModelCondition.csv/sample_info.csv all are. This used to be a
    caveat — `pd.isna` on a list-valued cell returns an ARRAY, so `if pd.isna(v)` raises on the truth-value
    test — and it is now enforced: `plain_row()` rejects a non-scalar cell with a TypeError naming the
    column, rather than depending on `bool()` happening to raise. A length-1 container was the dangerous
    case, because its self-comparison bools cleanly and would have answered "present".

    ★ Rows whose KEY is missing are DROPPED, not kept under a None key. The key column is a primary key,
    and an entry under a missing key is unreachable by construction: callers only ever reach this dict via
    `metadata.get(model_id)` with an ID that came from a data matrix, so nothing can ever match it. Keeping
    it would carry a row that no lookup returns and that json.dumps would coerce to a *fabricated* string
    ID ("NaN" / "None"). Dropping an unreachable entry loses no information; keeping one invents an ID.

    Args:
        model_df: a DataFrame from load_model_csv() (or any flat metadata CSV).
        model_id_col: key column. Defaults to "ModelID" when present, else the first column —
            the same resolution every caller open-coded.
    """
    from methods import cell_absence as ca

    if model_id_col is None:
        model_id_col = "ModelID" if "ModelID" in model_df.columns else model_df.columns[0]
    return {
        row[model_id_col]: ca.plain_row(row.to_dict())
        for _, row in model_df.iterrows()
        if not ca.is_missing(row[model_id_col])
    }


@lru_cache(maxsize=8)
def load_model_condition_csv(release_pin: str = "26q1"):
    """Load DepMap ModelCondition.csv (ModelConditionID → ModelID bridge).

    Required for the CN-distribution card (E3.b) — CN matrix is indexed by
    ModelConditionID, but the framework's canonical cell-line ID is ModelID.
    Bridge lives HERE (in ModelCondition.csv), NOT in Model.csv (Model.csv
    doesn't carry ModelConditionID as of 26Q1).

    Small file (~324 KB); process-lifetime cached.
    """
    key = f"{DEPMAP_S3_PREFIX_CRISPR}/ModelCondition.csv"
    return _fetch_csv(key, "ModelCondition.csv", release_pin)


@lru_cache(maxsize=8)
def load_rnai_sample_info(release_pin: str = "26q1"):
    """Load DepMap RNAi sample_info.csv (CCLE_ID metadata for the DEMETER2 panel).

    Different namespace from Model.csv — RNAi data is keyed by CCLE_ID (legacy
    format like '127399_SOFT_TISSUE'), which needs bridging to ModelID via
    Model.csv's CCLEName column at consumer-method level.

    Small file (~76 KB); process-lifetime cached.
    """
    key = f"{DEPMAP_S3_PREFIX_RNAI}/sample_info.csv"
    return _fetch_csv(key, "rnai_sample_info.csv", release_pin)


def clear_all_caches() -> None:
    """Clear the in-process LRU caches for all loaders.

    Useful for tests that need a clean state. NOTE: this only clears process
    memory; the session cache on ~/.cache/framework-depmap-26q1/ persists.
    """
    load_model_csv.cache_clear()
    load_model_condition_csv.cache_clear()
    load_rnai_sample_info.cache_clear()
