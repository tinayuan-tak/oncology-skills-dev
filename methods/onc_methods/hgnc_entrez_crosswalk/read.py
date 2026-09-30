"""hgnc_entrez_crosswalk.read — {entrez_id: HGNC approved symbol} from the HGNC complete set.

Some cBioPortal exports (notably MSK-CHORD mutations.jsonl) carry `entrezGeneId` but NOT a Hugo
symbol; this maps NCBI entrez id → the current HGNC approved symbol so those variants join the
framework's symbol-keyed products. Reads the hgnc source (data-catalog). Small, cached module.
"""

from __future__ import annotations

import io
import os
from functools import lru_cache

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
# hgnc-2026-q2 source (data-catalog). columns: hgnc_id, symbol, ..., entrez_id, ...
HGNC_KEY = "data-catalog/sources/hgnc/2026-Q2/hgnc_complete_set_2026-04-01.txt"

from onc_methods.target_id_sidecar import ensure_aws_profile


@lru_cache(maxsize=1)
def load_entrez_to_symbol() -> dict:
    """{int entrez_id: approved HGNC symbol}. Rows without a usable entrez_id or symbol are skipped.

    Raises on a broken/empty read rather than returning {} — an empty crosswalk would silently DROP
    every entrez-only variant (the null-strata failure class), so a well-formed-but-empty read is a
    broken product, not a data gap. Only a genuine object-absence returns {}.
    """
    import pandas as pd

    from onc_methods.target_id_sidecar import is_definitively_absent

    ensure_aws_profile()
    import boto3

    s3 = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")
    try:
        body = s3.get_object(Bucket=S3_BUCKET, Key=HGNC_KEY)["Body"].read()
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e) or isinstance(e, FileNotFoundError):
            return {}
        raise
    df = pd.read_csv(io.BytesIO(body), sep="\t", usecols=["symbol", "entrez_id"], dtype=str, low_memory=False).dropna(
        subset=["symbol", "entrez_id"]
    )
    out: dict[int, str] = {}
    for sym, ez in zip(df["symbol"], df["entrez_id"]):
        try:
            out[int(float(ez))] = sym
        except (ValueError, TypeError):
            continue
    if not out:
        raise ValueError(
            f"HGNC entrez→symbol crosswalk s3://{S3_BUCKET}/{HGNC_KEY} produced an EMPTY map "
            "(well-formed read, no usable entrez_id→symbol pairs) — a broken/empty product, NOT a "
            "data gap; returning {} here would silently drop every entrez-only variant."
        )
    return out
