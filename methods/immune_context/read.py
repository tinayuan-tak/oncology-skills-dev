"""immune_context.read — S3 boundary + assembler for the per-indication immune-context signal.

Streamed pushdown (2026-08-22 data-layer hardening): reads the derived per-sample product
`pancanatlas-cibersort-lm22-per-sample-v1` via a pyarrow S3FileSystem, pushing down the indication's
TCGA study code(s) on `cancer_type` so only those samples transit the wire — no whole-TSV download.
The product carries the CIBERSORT LM22 fractions under their ORIGINAL column names, so the pooled
`summarize_immune_context` reduction runs UNCHANGED on the streamed slice.

Reads the CIBERSORT LM22 per-sample leukocyte-composition table (Thorsson 2018), filters to the
indication's TCGA study/studies (cancer_type — already TCGA study codes, no crosswalk), and reduces
to the immune-context summary (median CD8 T-cell fraction across POOLED samples → hot/intermediate/cold).

Credential discipline: AWS_PROFILE=cbg. Manifest ID → bucket/key via catalog_query.
Reuses the canonical dge_deseq2 INDICATION_TO_TCGA_STUDIES map (no new indication map).

NOTE for whoever extends INDICATION_TO_TCGA_STUDIES: adding a hematologic / lymphoid-organ study is
now SAFE — classify.has_lymphoid_denominator fails the read closed on LAML/DLBC/THYM instead of
publishing a confident nonsense class. Before that guard, this map's omissions were the only thing
preventing it, which is not a safety property.
"""

from __future__ import annotations

import threading

from methods.catalog_query.read import bucket_key_for

from . import classify as _classify

DERIVED_MANIFEST_ID = "pancanatlas-cibersort-lm22-per-sample-v1"

try:
    from methods.dge_deseq2.read import INDICATION_TO_TCGA_STUDIES as _DGE_MAP
except Exception:  # noqa: BLE001
    _DGE_MAP = {"COADREAD": ["COAD", "READ"]}

# The canonical dge_deseq2 map is the source of truth, but it omits some UMBRELLA codes (e.g. NSCLC)
# even when their constituent studies (LUAD/LUSC) exist. Layer those umbrellas ON TOP (never override
# an existing key) so a first-class framework indication like NSCLC resolves rather than silently
# returning data_unavailable — the indication-vocabulary-fragmentation trap. Constituent studies must
# be present in the CIBERSORT cancer_type vocabulary.
# UCEC/SARC are first-class TCGA studies the immune-context card advertises; the dge_deseq2 map omits
# them, but the CIBERSORT product covers all 33 TCGA studies, so add them here (self-mapped) so they
# resolve rather than silently returning data_unavailable.
_UMBRELLA_SUPPLEMENT = {"NSCLC": ["LUAD", "LUSC"], "UCEC": ["UCEC"], "SARC": ["SARC"]}
INDICATION_TO_TCGA_STUDIES = {**_UMBRELLA_SUPPLEMENT, **_DGE_MAP}  # _DGE_MAP wins on any shared key


# ── streamed pushdown read (pyarrow S3FileSystem; no whole-file download) ─────────────────────
_S3FS = None
_S3FS_LOCK = threading.Lock()


def _get_s3fs():
    """Process-wide pyarrow S3FileSystem singleton (region us-east-1, the onc-compbio bucket).
    Built once, shared across threads (the parallel card-read pool relies on that). Mirrors
    methods/dge_deseq2/read.py::_get_s3fs."""
    global _S3FS
    if _S3FS is None:
        with _S3FS_LOCK:
            if _S3FS is None:
                import pyarrow.fs as pafs

                _S3FS = pafs.S3FileSystem(region="us-east-1")
    return _S3FS


def _read_samples_for_studies(studies, product_path=None):
    """Streamed pushdown read of the CIBERSORT rows for the given TCGA study code(s). Returns a
    pandas DataFrame (LM22 fractions under original column names). `product_path` (offline test seam):
    a local parquet bypasses S3. Returns None on a GENUINE product-object absence (404); RAISES on a
    transient/creds/broken-env failure (never masked as a false immune-cold)."""
    import pyarrow.parquet as pq

    flt = [("cancer_type", "in", list(studies))]
    try:
        if product_path is not None:
            tbl = pq.read_table(str(product_path), filters=flt)
        else:
            bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
            tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=flt)
    except Exception as e:  # noqa: BLE001
        from methods.target_id_sidecar import is_definitively_absent

        if isinstance(e, FileNotFoundError) or is_definitively_absent(e):
            return None  # genuine no-object → honest data_unavailable at the caller
        raise  # transient/creds → propagate (live-read seam records the real cause)
    return tbl.to_pandas()


def read_immune_context(indication: str, product_path=None) -> dict:
    """Per-indication immune-context summary (T-cell infiltration → immune-hot/cold class).

    target-INDEPENDENT (tier: indication). data_unavailable when the CIBERSORT product is unreadable
    or the indication has no TCGA study mapping (honest gap, never a false 'cold')."""
    ind = str(indication).upper().strip()
    studies = INDICATION_TO_TCGA_STUDIES.get(ind)
    if not studies:
        return {
            **_classify.summarize_immune_context([]),
            "indication": ind,
            "tumor_studies": None,
            "_data_note": f"indication {ind} has no TCGA study mapping (immune context is TCGA-based)",
        }
    # The LYMPHOID-DENOMINATOR guard fires on the resolved STUDY codes, BEFORE the read. Not merely an
    # optimisation: it means no code path in this module can compute a median for one of those cohorts,
    # so the guard cannot be defeated by a future caller that reduces the frame itself.
    if _classify.has_lymphoid_denominator(studies):
        return {
            **_classify.summarize_immune_context([], studies=studies),
            "indication": ind,
            "tumor_studies": studies,
        }
    df = _read_samples_for_studies(studies, product_path=product_path)
    if df is None:
        return {
            **_classify.summarize_immune_context([]),
            "indication": ind,
            "tumor_studies": studies,
            "_data_note": "CIBERSORT product unreadable (pancanatlas-cibersort-lm22-per-sample-v1)",
        }
    out = _classify.summarize_immune_context(df, studies=studies)
    out["indication"] = ind
    out["tumor_studies"] = studies
    return out
