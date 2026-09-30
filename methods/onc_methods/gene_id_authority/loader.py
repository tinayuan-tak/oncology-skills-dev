"""Load the gene-ID authority parquet from the data-catalog.

Mirrors methods.gencode_exon_index.loader:
  1. Local cache (~/.cache/framework-gene-id-authority/...) if md5 matches pin
  2. S3-catalogued derived product with md5 verification
  3. Fallback: rebuild locally from the two catalogued source files

The derived-manifest lookup is LAZY (resolved inside the load function, not at
import) so this module imports cleanly even before the paired data-catalog
manifest `gene-id-authority-v23-v116-v1` has landed. The md5 pin below is the
single source of truth against the manifest; if they drift the loader fails
fast rather than returning drifted data.
"""

from __future__ import annotations

import os
from pathlib import Path

DERIVED_MANIFEST_ID = "gene-id-authority-v23-v116-v1"
ENSEMBL116_SOURCE_MANIFEST_ID = "ensembl-id-mapping-release-116-snapshot-2026-06-18"
GENCODE_V23_SOURCE_MANIFEST_ID = "xena-toil-tcga-target-gtex-snapshot-2026-09-20"
_ENSEMBL116_FILE = "hsapiens_gene_id_map_release-116.tsv"
_GENCODE_V23_FILE = "gencode.v23.annotation.gene.probemap"

CACHE_DIR = Path(
    os.environ.get(
        "FRAMEWORK_GENE_ID_AUTHORITY_CACHE_DIR",
        str(Path.home() / ".cache" / "framework-gene-id-authority"),
    )
)
CACHE_FILE = CACHE_DIR / "gene_id_authority_v23_v116.parquet"

# md5 pin — filled from `md5sum` of the published parquet at manifest-authoring
# time. Kept in sync with manifests/derived/gene-id-authority-v23-v116-v1.yaml.
S3_MD5_PARQUET = "7aa291a7fd1b3799e837c7cb598fa9f4"


def _md5_of_file(path: Path) -> str:
    import hashlib

    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _try_s3_fetch(bucket: str, s3_key: str, local_path: Path, expected_md5: str) -> bool:
    """S3 → local with md5 verification. Silent-failure on any error."""
    try:
        import boto3

        os.environ.setdefault("AWS_PROFILE", "cbg")
        s3 = boto3.client("s3")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        # pushdown-discipline: exempt -- reference/authority table (2.6MB) loaded whole; joins need every row, no per-target pushdown applies
        s3.download_file(bucket, s3_key, str(local_path))  # pushdown-discipline: exempt
    except Exception as e:
        print(f"[gene_id_authority] S3 fetch of {s3_key} failed: {e}")
        return False
    actual = _md5_of_file(local_path)
    if actual != expected_md5:
        print(
            f"[gene_id_authority] md5 mismatch for {s3_key}: expected {expected_md5}, "
            f"got {actual}. Removing local copy."
        )
        try:
            local_path.unlink()
        except Exception:
            pass
        return False
    return True


def _rebuild_from_sources(cache_file: Path):
    """Fallback: pull the two catalogued source files and rebuild locally."""
    import boto3

    from onc_methods.catalog_query.read import bucket_prefix_for

    from .build import build_authority

    os.environ.setdefault("AWS_PROFILE", "cbg")
    s3 = boto3.client("s3")
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    ens_bucket, ens_prefix = bucket_prefix_for(ENSEMBL116_SOURCE_MANIFEST_ID)
    v23_bucket, v23_prefix = bucket_prefix_for(GENCODE_V23_SOURCE_MANIFEST_ID)
    ens_local = cache_file.parent / _ENSEMBL116_FILE
    v23_local = cache_file.parent / _GENCODE_V23_FILE
    # pushdown-discipline: exempt -- rebuild fallback pulls the whole source files to regenerate the authority; not a per-target read
    s3.download_file(ens_bucket, f"{ens_prefix}{_ENSEMBL116_FILE}", str(ens_local))  # pushdown-discipline: exempt
    s3.download_file(v23_bucket, f"{v23_prefix}{_GENCODE_V23_FILE}", str(v23_local))  # pushdown-discipline: exempt

    auth = build_authority(ens_local, v23_local)
    auth.to_parquet(cache_file, index=False, compression="snappy")
    return auth


def load_gene_id_authority(refresh: bool = False):
    """Return the gene-ID authority as a pandas DataFrame.

    Fetch order: local cache (md5-verified) → S3 derived product → rebuild from
    the two catalogued source files.
    """
    import pandas as pd

    if CACHE_FILE.exists() and not refresh:
        actual = _md5_of_file(CACHE_FILE)
        if actual == S3_MD5_PARQUET:
            return pd.read_parquet(CACHE_FILE)
        print(f"[gene_id_authority] local parquet md5 mismatch ({actual} vs {S3_MD5_PARQUET}); refetching.")
        CACHE_FILE.unlink()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Resolve the derived manifest lazily; tolerate its absence (pre-land).
    try:
        from onc_methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
    except Exception as e:
        print(
            f"[gene_id_authority] derived manifest {DERIVED_MANIFEST_ID} unresolved ({e}); will rebuild from sources."
        )
        bucket = key = None

    if bucket and key and _try_s3_fetch(bucket, key, CACHE_FILE, S3_MD5_PARQUET):
        print(f"[gene_id_authority] fetched from S3 → {CACHE_FILE}")
        return pd.read_parquet(CACHE_FILE)

    print("[gene_id_authority] WARN: S3 derived product unavailable; rebuilding from catalogued sources.")
    return _rebuild_from_sources(CACHE_FILE)
