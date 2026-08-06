"""immune_context.read — S3 boundary + assembler for the per-indication immune-context signal.

Reads the CIBERSORT LM22 per-sample leukocyte-composition table from gdc-pancanatlas-immune-2018
(Thorsson 2018), filters to the indication's TCGA study/studies (CancerType column — already TCGA
study codes, so no crosswalk), and reduces to the immune-context summary. Cache-once-per-machine
(the table is ~11k rows; download once, filter in memory).

Credential discipline: AWS_PROFILE=cbg. Manifest ID → S3 prefix via catalog_query.
Reuses the canonical dge_deseq2 INDICATION_TO_TCGA_STUDIES map (no new indication map).
"""
from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Optional

from methods.catalog_query.read import bucket_prefix_for
from . import classify as _classify

DEFAULT_AWS_PROFILE = "cbg"
MANIFEST_ID = "gdc-pancanatlas-immune-2018"
CIBERSORT_FILE = "TCGA.Kallisto.fullIDs.cibersort.relative.tsv"

CACHE_DIR = Path.home() / ".cache" / "framework-immune-context"
CACHE_TSV = CACHE_DIR / CIBERSORT_FILE

try:
    from methods.dge_deseq2.read import INDICATION_TO_TCGA_STUDIES as _DGE_MAP
except Exception:  # noqa: BLE001
    _DGE_MAP = {"COADREAD": ["COAD", "READ"]}

# The canonical dge_deseq2 map is the source of truth, but it omits some UMBRELLA codes (e.g. NSCLC)
# even when their constituent studies (LUAD/LUSC) exist. Layer those umbrellas ON TOP (never override
# an existing key) so a first-class framework indication like NSCLC resolves rather than silently
# returning data_unavailable — the indication-vocabulary-fragmentation trap. Constituent studies must
# be present in the CIBERSORT CancerType vocabulary.
_UMBRELLA_SUPPLEMENT = {"NSCLC": ["LUAD", "LUSC"]}
INDICATION_TO_TCGA_STUDIES = {**_UMBRELLA_SUPPLEMENT, **_DGE_MAP}  # _DGE_MAP wins on any shared key

_STATUS: Optional[bool] = None


def _ensure_cached() -> Optional[Path]:
    global _STATUS
    if _STATUS is False:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if CACHE_TSV.exists() and CACHE_TSV.stat().st_size > 0:
        _STATUS = True
        return CACHE_TSV
    try:
        import boto3
        bucket, prefix = bucket_prefix_for(MANIFEST_ID)
        boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3").download_file(
            bucket, f"{prefix}{CIBERSORT_FILE}", str(CACHE_TSV))
        _STATUS = True
        return CACHE_TSV
    except Exception as e:  # noqa: BLE001
        resp = getattr(e, "response", None)
        code = resp.get("Error", {}).get("Code") if isinstance(resp, dict) else None
        if code in ("404", "NoSuchKey") or e.__class__.__name__ in ("NoSuchKey", "404"):
            _STATUS = False   # definitive-absent latches; transient (403/creds) retries next call
        print(f"[immune_context] CIBERSORT read failed ({type(e).__name__}: {e})", file=sys.stderr)
        return None


@lru_cache(maxsize=1)
def _cibersort_frame():
    """The full CIBERSORT table (cached in-process). None if unreadable."""
    path = _ensure_cached()
    if path is None:
        return None
    import pandas as pd
    return pd.read_csv(path, sep="\t")


def read_immune_context(indication: str) -> dict:
    """Per-indication immune-context summary (T-cell infiltration → immune-hot/cold class).

    target-INDEPENDENT (tier: indication). data_unavailable when the CIBERSORT table is unreadable
    or the indication has no TCGA study mapping (honest gap, never a false 'cold')."""
    ind = str(indication).upper().strip()
    studies = INDICATION_TO_TCGA_STUDIES.get(ind)
    if not studies:
        return {**_classify.summarize_immune_context([]),
                "indication": ind, "tumor_studies": None,
                "_data_note": f"indication {ind} has no TCGA study mapping (immune context is TCGA-based)"}
    df = _cibersort_frame()
    if df is None:
        return {**_classify.summarize_immune_context([]),
                "indication": ind, "tumor_studies": studies,
                "_data_note": "CIBERSORT table unreadable (gdc-pancanatlas-immune-2018)"}
    sub = df[df["CancerType"].isin(studies)]
    out = _classify.summarize_immune_context(sub)
    out["indication"] = ind
    out["tumor_studies"] = studies
    return out
