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
from typing import Optional

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
    Path("/home/sagemaker-user/depmap-26q1"),
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
        raise FileNotFoundError(
            f"Cannot fetch {local_filename}: boto3 not installed and no local cache. "
            f"Detail: {e}"
        )

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
