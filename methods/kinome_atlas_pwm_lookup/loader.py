"""Load the kinome-atlas PWM lookup parquet from the data-catalog.

Mirrors methods.dge_deseq2.gene_lengths.load_gene_lengths shape:
  1. Local cache (~/.cache/framework-kinome-atlas/pwm_lookup_v1.parquet)
     if md5 matches manifest pin
  2. S3-catalogued derived product with md5 verification
  3. No local fallback — the two source xlsx workbooks must be re-parsed
     via methods.kinome_atlas_pwm_lookup.build if S3 is unreachable.

The md5 pin below MUST be kept in sync with the manifest at
    manifests/derived/kinome-atlas-pwm-lookup-v1.yaml
in the data-catalog repo. If they drift, the loader fails fast rather
than returning drifted data.
"""

from __future__ import annotations

import os
from pathlib import Path

from methods.catalog_query.read import bucket_key_for


DERIVED_MANIFEST_ID = "kinome-atlas-pwm-lookup-v1"
# bucket + key resolved from the data-catalog manifest (single source of truth).
S3_BUCKET, S3_KEY_PARQUET = bucket_key_for(DERIVED_MANIFEST_ID)

CACHE_DIR = Path(
    os.environ.get("FRAMEWORK_KINOME_ATLAS_CACHE_DIR", str(Path.home() / ".cache" / "framework-kinome-atlas"))
)
CACHE_FILE = CACHE_DIR / "pwm_lookup_v1.parquet"

# md5 pin filled in at manifest-authoring time
S3_MD5_PARQUET = "666351dbc792135c93452632883c6458"


def _md5_of_file(path: Path) -> str:
    import hashlib

    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _try_s3_fetch(s3_key: str, local_path: Path, expected_md5: str) -> bool:
    """S3 -> local with md5 verification. Silent failure on any error."""
    try:
        import boto3

        os.environ.setdefault("AWS_PROFILE", "cbg")
        s3 = boto3.client("s3")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(S3_BUCKET, s3_key, str(local_path))
    except Exception as e:
        print(f"[pwm_lookup] S3 fetch of {s3_key} failed: {e}")
        return False
    actual = _md5_of_file(local_path)
    if actual != expected_md5:
        print(f"[pwm_lookup] md5 mismatch for {s3_key}: expected {expected_md5}, got {actual}. Removing local copy.")
        try:
            local_path.unlink()
        except Exception:
            pass
        return False
    return True


def load_pwm_lookup(refresh: bool = False):
    """Return the kinome-atlas PWM lookup as a pandas DataFrame.

    Columns: family (ser_thr|tyrosine), kinase, position (int32 in -5..+5,
    excluding 0), amino_acid (single letter, 20 std + s/t/y phospho),
    norm_scaled_value (float32), matrix_type ('norm_scaled'), source_paper
    ('johnson_2023'|'yaron_barir_2024').

    Fetch order:
      1. Local parquet cache (with md5 verification)
      2. S3-catalogued derived product
      3. Failure — no automatic local fallback (call
         methods.kinome_atlas_pwm_lookup.build.build_pwm_lookup manually
         with the two source xlsx paths if needed).
    """
    import pandas as pd

    if CACHE_FILE.exists() and not refresh:
        actual = _md5_of_file(CACHE_FILE)
        if actual == S3_MD5_PARQUET:
            return pd.read_parquet(CACHE_FILE)
        print(f"[pwm_lookup] local parquet md5 mismatch ({actual} vs {S3_MD5_PARQUET}); refetching.")
        CACHE_FILE.unlink()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if _try_s3_fetch(S3_KEY_PARQUET, CACHE_FILE, S3_MD5_PARQUET):
        print(f"[pwm_lookup] fetched from S3 -> {CACHE_FILE}")
        return pd.read_parquet(CACHE_FILE)

    raise RuntimeError(
        f"Cannot load kinome-atlas PWM lookup: S3 unreachable and no local "
        f"cache at {CACHE_FILE}. To rebuild locally from source xlsx workbooks, "
        f"call methods.kinome_atlas_pwm_lookup.build.build_pwm_lookup()."
    )
