"""Load the GENCODE v26 exon-index parquet from the data-catalog.

Mirrors methods.dge_deseq2.gene_lengths.load_gene_lengths shape:
  1. Local cache (~/.cache/framework-gencode-v26/exon_index_v26.parquet)
     if md5 matches manifest pin
  2. S3-catalogued derived product with md5 verification
  3. Fallback: parse GTF locally via build.parse_gtf_to_exon_index

The md5 pin below MUST be kept in sync with the manifest at
    manifests/derived/gencode-v26-exon-index-v1.yaml
in the data-catalog repo. If they drift, the loader fails fast
rather than returning drifted data.
"""
from __future__ import annotations

import os
from pathlib import Path

from .build import parse_gtf_to_exon_index


S3_BUCKET = "onc-compbio"
S3_KEY_PARQUET = (
    "data-catalog/derived/gencode-v26-exon-index-v1/exon_index_v26.parquet"
)
S3_KEY_GTF = (
    "data-catalog/sources/gencode/gencode-v26-primary-assembly/"
    "gencode.v26.primary_assembly.annotation.gtf.gz"
)

CACHE_DIR = Path(
    os.environ.get("FRAMEWORK_GENCODE_CACHE_DIR",
                   str(Path.home() / ".cache" / "framework-gencode-v26"))
)
CACHE_FILE = CACHE_DIR / "exon_index_v26.parquet"

# md5 pin — filled in from `md5sum exon_index_v26.parquet` at manifest-authoring
# time. If S3 delivers a file with a different md5, the manifest was updated
# without a version bump — fail fast.
S3_MD5_PARQUET = "725e6337b0b643379523e1c4f60c7996"

S3_MD5_GTF = "2c4494f53b61a8f0ef8b36d1900fa49d"


def _md5_of_file(path: Path) -> str:
    import hashlib
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _try_s3_fetch(s3_key: str, local_path: Path, expected_md5: str) -> bool:
    """S3 → local with md5 verification. Silent-failure on any error."""
    try:
        import boto3
        os.environ.setdefault("AWS_PROFILE", "cbg")
        s3 = boto3.client("s3")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        s3.download_file(S3_BUCKET, s3_key, str(local_path))
    except Exception as e:
        print(f"[exon_index] S3 fetch of {s3_key} failed: {e}")
        return False
    actual = _md5_of_file(local_path)
    if actual != expected_md5:
        print(
            f"[exon_index] md5 mismatch for {s3_key}: "
            f"expected {expected_md5}, got {actual}. Removing local copy."
        )
        try:
            local_path.unlink()
        except Exception:
            pass
        return False
    return True


def load_exon_index(refresh: bool = False):
    """Return the GENCODE v26 exon-index as a pandas DataFrame.

    Fetch order:
      1. Local parquet cache (with md5 verification)
      2. S3-catalogued derived product
      3. Fallback: parse GTF locally (~30-60 sec first time)

    Args:
        refresh: force re-fetch even if cache exists.

    Returns:
        pandas.DataFrame — schema documented in build.py.
    """
    import pandas as pd

    if CACHE_FILE.exists() and not refresh:
        actual = _md5_of_file(CACHE_FILE)
        if actual == S3_MD5_PARQUET:
            return pd.read_parquet(CACHE_FILE)
        print(
            f"[exon_index] local parquet md5 mismatch ({actual} vs "
            f"{S3_MD5_PARQUET}); refetching."
        )
        CACHE_FILE.unlink()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if _try_s3_fetch(S3_KEY_PARQUET, CACHE_FILE, S3_MD5_PARQUET):
        print(f"[exon_index] fetched from S3 → {CACHE_FILE}")
        return pd.read_parquet(CACHE_FILE)

    print(
        "[exon_index] WARN: S3 mirror unavailable; falling back to local "
        "GTF parse. Ensure GTF is at "
        f"{CACHE_DIR / 'gencode.v26.primary_assembly.annotation.gtf.gz'}."
    )
    gtf_local = CACHE_DIR / "gencode.v26.primary_assembly.annotation.gtf.gz"
    if not gtf_local.exists():
        raise FileNotFoundError(
            f"Cannot fall back to GTF parse: {gtf_local} does not exist. "
            f"Run `aws s3 cp s3://{S3_BUCKET}/{S3_KEY_GTF} {gtf_local}` "
            f"to enable local fallback."
        )
    df = parse_gtf_to_exon_index(gtf_local)
    df.to_parquet(CACHE_FILE, index=False, compression="snappy")
    return df
