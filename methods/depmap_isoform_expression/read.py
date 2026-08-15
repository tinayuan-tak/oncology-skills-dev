"""depmap_isoform_expression.read — per-gene model-side isoform-expression summary + builder.

Product-first reader (gene-sorted pushdown) + a builder that streams the 4.3 GB DepMap
transcript-TPM once (the file is too big to live-read per query). ENST→gene via the GENCODE v26 GTF.
"""
from __future__ import annotations

import io
import math
import os
import re
from functools import lru_cache
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DEPMAP_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1"
# The non-stranded human transcript-TPM (log1p). models-in-rows × ENST-in-columns.
TRANSCRIPT_TPM_KEY = f"{DEPMAP_PREFIX}/OmicsExpressionTranscriptTPMLogp1HumanAllGenes.csv"
GENCODE_PREFIX = "data-catalog/sources/gencode/gencode-v26-primary-assembly"
GENCODE_GTF_KEY = f"{GENCODE_PREFIX}/gencode.v26.primary_assembly.annotation.gtf.gz"
PRODUCT_MANIFEST_ID = "depmap-isoform-expression-per-gene-v1"

# A transcript counts as "expressed" in a model if its linear TPM >= this (filters noise before the
# dominant-fraction + isoform-count; below this a transcript is effectively off).
_MIN_EXPRESSED_TPM = 1.0
# A gene needs >= this many models expressing it (gene-total TPM > 0) for a trustworthy summary.
_MIN_MODELS = 20
# isoform_expression_class cutoffs on the cohort-median dominant-isoform fraction.
_SINGLE_DOMINANT = 0.80   # median dominant-isoform fraction >= 0.80 → one isoform carries expression
_DIVERSE = 0.50           # < 0.50 → isoform-diverse (no single isoform dominates)


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def _boto3():
    import boto3
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


@lru_cache(maxsize=1)
def _enst_to_gene() -> dict:
    """{base-ENST: gene_symbol} from the GENCODE v26 GTF transcript lines. Version-stripped keys
    (DepMap transcript ids are versioned ENST; join on the base). Empty on failure."""
    import gzip
    _ensure_aws_profile()
    try:
        raw = _boto3().get_object(Bucket=S3_BUCKET, Key=GENCODE_GTF_KEY)["Body"].read()
    except Exception as e:  # noqa: BLE001
        # build-time GENCODE crosswalk: broken-env/transient/creds must surface (an empty crosswalk
        # silently mis-materializes every gene) — re-raise; only genuine object-absence → {}.
        from methods.target_id_sidecar import is_definitively_absent
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return {}
    out: dict = {}
    with gzip.open(io.BytesIO(raw), "rt") as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            f = line.split("\t")
            if len(f) < 9 or f[2] != "transcript":
                continue
            t = re.search(r'transcript_id "([^"]+)"', f[8])
            g = re.search(r'gene_name "([^"]+)"', f[8])
            if t and g:
                out[t.group(1).split(".")[0]] = g.group(1)
    return out


def _classify(dominant_fraction: Optional[float]) -> str:
    if dominant_fraction is None:
        return "data_unavailable"
    if dominant_fraction >= _SINGLE_DOMINANT:
        return "single_isoform_dominant"
    if dominant_fraction < _DIVERSE:
        return "isoform_diverse"
    return "balanced"


def _read_from_product(target: str) -> Optional[dict]:
    """Fast path: per-gene pushdown read of the materialized gene-sorted product. None if unresolvable."""
    try:
        import sys as _sys
        from pathlib import Path as _P
        _sys.path.insert(0, str(_P(__file__).resolve().parent.parent))
        from methods.catalog_query.read import bucket_key_for
        import pyarrow.parquet as pq
        import pyarrow.fs as fs
        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=fs.S3FileSystem(),
                            filters=[("gene_symbol", "=", (target or "").strip().upper())])
    except Exception as e:  # noqa: BLE001
        # genuine object-absence → None (data_unavailable; no live fallback). Broken-env/transient/
        # creds must NOT be masked as a coverage gap — re-raise → honest _live_read_error.
        from methods.target_id_sidecar import is_definitively_absent
        if not (is_definitively_absent(e) or isinstance(e, FileNotFoundError)):
            raise
        return None
    if tbl.num_rows == 0:
        return None
    return tbl.to_pylist()[0]


def isoform_summary_for_gene(target: str) -> dict:
    """Per-gene MODEL-side isoform-expression summary. Product-first (gene-sorted pushdown); returns
    data_unavailable when the gene isn't in the product (no product live-fallback — the 4.3 GB source
    is build-only). DISPLAY facet, verdict-inert.

    Returns isoform_expression_class {single_isoform_dominant / isoform_diverse / balanced /
    data_unavailable}, dominant_isoform_fraction (cohort median), n_expressed_isoforms (median),
    dominant_isoform (the modal top ENST), n_models, isoform_context."""
    sym = (target or "").strip()
    r = _read_from_product(sym)
    if r is None:
        return _unavailable(f"{sym} not in depmap-isoform-expression product")
    return {
        "isoform_expression_class": r.get("isoform_expression_class"),
        "dominant_isoform_fraction": r.get("dominant_isoform_fraction"),
        "n_expressed_isoforms": r.get("n_expressed_isoforms"),
        "dominant_isoform": r.get("dominant_isoform"),
        "n_models": r.get("n_models"),
        "isoform_context": (
            f"{sym}: median dominant-isoform fraction {r.get('dominant_isoform_fraction'):.2f} across "
            f"{r.get('n_models')} DepMap cell lines ({r.get('n_expressed_isoforms')} expressed isoforms "
            f"median; top {r.get('dominant_isoform')}) — MODEL isoform-expression, verdict-inert."
            if r.get("dominant_isoform_fraction") is not None else f"{sym}: isoform summary present"),
        "method_version": "0.1.0",
        "_data_source": "depmap-consortium-26q1",
    }


def _unavailable(note: str) -> dict:
    return {
        "isoform_expression_class": "data_unavailable",
        "dominant_isoform_fraction": None, "n_expressed_isoforms": None,
        "dominant_isoform": None, "n_models": 0, "isoform_context": None,
        "method_version": "0.1.0", "_data_note": note,
    }


def build_isoform_table(local_csv: Optional[str] = None):
    """Materialize the gene-sorted per-gene isoform-expression product from the DepMap transcript-TPM
    matrix (models × ENST, log1p). VECTORIZED: load the matrix once (float32), map ENST columns→gene,
    and for each gene take its column block and compute per-model dominant-isoform fraction +
    expressed-isoform count with numpy (no per-row Python), then cohort medians + modal dominant ENST.

    local_csv: path to the pre-downloaded CSV (production + tests). If None, streams from S3 (slower)."""
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    enst2gene = _enst_to_gene()

    src = local_csv
    if src is None:
        _ensure_aws_profile()
        src = _boto3().get_object(Bucket=S3_BUCKET, Key=TRANSCRIPT_TPM_KEY)["Body"]
    # Plan the read from the header FIRST (column identity is data-dependent), then read ONLY the
    # mapped ENST columns directly as float32. Reading dtype=str over all 237k columns would balloon
    # to tens of GB of Python str objects; usecols+float32 keeps the peak ~1400×~197k×4 ≈ 1.1 GB.
    header = list(pd.read_csv(src, nrows=0).columns)
    if hasattr(src, "seek"):                  # rewind an S3 stream / file object consumed by the header read
        try:
            src.seek(0)
        except Exception:  # noqa: BLE001
            pass
    enst_cols = [c for c in header if c.startswith("ENST")]
    # column → gene (version-stripped); keep only mapped columns.
    col_to_gene = {c: enst2gene[c.split(".")[0]] for c in enst_cols if c.split(".")[0] in enst2gene}
    mapped = list(col_to_gene)
    df = pd.read_csv(src, usecols=mapped, dtype={c: "float32" for c in mapped})
    mat = df[mapped].to_numpy(dtype="float32")  # reorder to `mapped` order; genes[] aligns to this
    del df
    mat = np.expm1(mat)                       # log1p → linear TPM
    mat[~np.isfinite(mat)] = 0.0
    mat[mat < _MIN_EXPRESSED_TPM] = 0.0       # apply expressed floor (below-floor → 0 = not expressed)
    genes = np.array([col_to_gene[c] for c in mapped])
    enst_ids = np.array(mapped)

    rows = []
    # iterate over the DISTINCT source-case gene labels, but rows are sorted at the end by the EMITTED
    # uppercase gene_symbol (the read key) so the product is physically sorted per the gene-keyed invariant.
    for g in sorted(set(genes.tolist())):
        gcols = np.where(genes == g)[0]
        block = mat[:, gcols]                 # models × isoforms(of g)
        tot = block.sum(axis=1)               # per-model gene-total TPM
        expressed = tot > 0                   # models where the gene is expressed at all
        n_models = int(expressed.sum())
        if n_models < _MIN_MODELS:
            continue
        b = block[expressed]; t = tot[expressed]
        top = b.max(axis=1)
        frac = top / t                        # per-model dominant-isoform fraction
        n_iso = (b > 0).sum(axis=1)           # per-model expressed-isoform count
        med_frac = float(np.median(frac))
        # modal dominant ENST across models (which isoform is the per-model argmax most often)
        dom_idx = b.argmax(axis=1)
        vals, counts = np.unique(dom_idx, return_counts=True)
        modal_local = int(vals[counts.argmax()])
        rows.append({
            "gene_symbol": g.upper(),
            "isoform_expression_class": _classify(med_frac),
            "dominant_isoform_fraction": med_frac,
            "n_expressed_isoforms": int(np.median(n_iso)),
            "dominant_isoform": str(enst_ids[gcols][modal_local]),
            "n_models": n_models,
        })
    rows.sort(key=lambda r: r["gene_symbol"])   # physical sort on the emitted uppercase read key
    return pa.Table.from_pylist(rows, schema=_schema())


def _schema():
    import pyarrow as pa
    return pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("isoform_expression_class", pa.string()),
        pa.field("dominant_isoform_fraction", pa.float64()),
        pa.field("n_expressed_isoforms", pa.int64()),
        pa.field("dominant_isoform", pa.string()),
        pa.field("n_models", pa.int64()),
    ])
