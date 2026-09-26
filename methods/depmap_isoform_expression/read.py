"""depmap_isoform_expression.read — per-gene model-side isoform-expression summary + builder.

Product-first reader (gene-sorted pushdown) + a builder that streams the ~4.6 GB DepMap
transcript-TPM once (the file is too big to live-read per query). ENST→gene via the GENCODE v26 GTF.
"""

from __future__ import annotations

import io
import os
import re
from functools import lru_cache
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"
DEPMAP_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q3"
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
_SINGLE_DOMINANT = 0.80  # median dominant-isoform fraction >= 0.80 → one isoform carries expression
_DIVERSE = 0.50  # < 0.50 → isoform-diverse (no single isoform dominates)


from methods.target_id_sidecar import ensure_aws_profile


def _boto3():
    import boto3

    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


@lru_cache(maxsize=1)
def _enst_to_gene() -> dict:
    """{base-ENST: gene_symbol} from the GENCODE v26 GTF transcript lines. Version-stripped keys
    (DepMap transcript ids are versioned ENST; join on the base). Empty on failure."""
    import gzip

    ensure_aws_profile()
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
        import pyarrow.fs as fs
        import pyarrow.parquet as pq

        from methods.catalog_query.read import bucket_key_for

        bucket, key = bucket_key_for(PRODUCT_MANIFEST_ID)
        tbl = pq.read_table(
            f"{bucket}/{key}",
            filesystem=fs.S3FileSystem(),
            filters=[("gene_symbol", "=", (target or "").strip().upper())],
        )
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


def isoform_summary_for_gene(target: str, indication: str | None = None) -> dict:
    """Per-gene MODEL-side isoform-expression summary. Product-first (gene-sorted pushdown); returns
    data_unavailable when the gene isn't in the product (no product live-fallback — the ~4.6 GB source
    is build-only). DISPLAY facet, verdict-inert.

    `indication` is accepted for the generic compose-dashboard dispatcher contract (it always calls
    fn(target=, indication=)) but is NOT consumed — isoform expression is a pan-cancer cell-line
    (target-only) property. Without this param the generic dispatch raised TypeError → the card read
    _missing (the routability gap this fix closes).

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
            if r.get("dominant_isoform_fraction") is not None
            else f"{sym}: isoform summary present"
        ),
        "method_version": "0.1.0",
        "_data_source": "depmap-consortium-26q3",
    }


def _unavailable(note: str) -> dict:
    return {
        "isoform_expression_class": "data_unavailable",
        "dominant_isoform_fraction": None,
        "n_expressed_isoforms": None,
        "dominant_isoform": None,
        "n_models": 0,
        "isoform_context": None,
        "method_version": "0.1.0",
        "_data_note": note,
    }


def build_isoform_table(local_csv: Optional[str] = None):
    """Materialize the gene-sorted per-gene isoform-expression product from the DepMap transcript-TPM
    matrix (models × ENST, log1p). VECTORIZED: load the matrix once (float32), map ENST columns→gene,
    and for each gene take its column block and compute per-model dominant-isoform fraction +
    expressed-isoform count with numpy (no per-row Python), then cohort medians + modal dominant ENST.

    local_csv: path to the pre-downloaded CSV (production + tests). If None, downloads from S3 first."""
    import csv as _csv
    import os as _os
    import tempfile

    import numpy as np
    import pyarrow as pa
    import pyarrow.csv as pac

    enst2gene = _enst_to_gene()

    # The 26q-era transcript-TPM matrix is ~4.6 GB, ~237k ENST columns × ~2.9k model-sequencing rows.
    # pandas.read_csv builds a per-column BlockManager that balloons past host RAM at that width
    # (~60+ GB observed on 26q3, risking an OOM on a swap-less host); pyarrow.csv reads ONLY the mapped
    # columns straight to columnar float32 (peak ~matrix size, ~30× faster). It needs a file PATH, so an
    # S3 source is staged to a temp file first (the old in-place seek() rewind was fragile on a stream).
    tmp = None
    path = local_csv
    if path is None:
        ensure_aws_profile()
        body = _boto3().get_object(Bucket=S3_BUCKET, Key=TRANSCRIPT_TPM_KEY)["Body"]
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        for chunk in iter(lambda: body.read(1 << 24), b""):
            tmp.write(chunk)
        tmp.close()
        path = tmp.name
    try:
        # Plan the read from the header FIRST (column identity is data-dependent), then read ONLY the
        # mapped ENST columns as float32.
        with open(path) as _fh:
            header = next(_csv.reader(_fh))
        enst_cols = [c for c in header if c.startswith("ENST")]
        # column → gene (version-stripped); keep only mapped columns.
        col_to_gene = {c: enst2gene[c.split(".")[0]] for c in enst_cols if c.split(".")[0] in enst2gene}
        mapped = list(col_to_gene)
        # block_size must exceed the longest line; the ~237k-column header line alone is multi-MB.
        conv = pac.ConvertOptions(include_columns=mapped, column_types={c: pa.float32() for c in mapped})
        read_opts = pac.ReadOptions(use_threads=True, block_size=256 * 1024 * 1024)
        tbl = pac.read_csv(path, read_options=read_opts, convert_options=conv).select(mapped)
    finally:
        if tmp is not None:
            _os.unlink(tmp.name)
    # reorder to `mapped` order (genes[]/enst_ids[] align to this)
    mat = np.column_stack([tbl.column(i).to_numpy(zero_copy_only=False) for i in range(tbl.num_columns)]).astype(
        "float32"
    )
    del tbl
    mat = np.expm1(mat)  # log1p → linear TPM
    mat[~np.isfinite(mat)] = 0.0
    mat[mat < _MIN_EXPRESSED_TPM] = 0.0  # apply expressed floor (below-floor → 0 = not expressed)
    genes = np.array([col_to_gene[c] for c in mapped])
    enst_ids = np.array(mapped)

    rows = []
    # iterate over the DISTINCT source-case gene labels, but rows are sorted at the end by the EMITTED
    # uppercase gene_symbol (the read key) so the product is physically sorted per the gene-keyed invariant.
    for g in sorted(set(genes.tolist())):
        gcols = np.where(genes == g)[0]
        block = mat[:, gcols]  # models × isoforms(of g)
        tot = block.sum(axis=1)  # per-model gene-total TPM
        expressed = tot > 0  # models where the gene is expressed at all
        n_models = int(expressed.sum())
        if n_models < _MIN_MODELS:
            continue
        b = block[expressed]
        t = tot[expressed]
        top = b.max(axis=1)
        frac = top / t  # per-model dominant-isoform fraction
        n_iso = (b > 0).sum(axis=1)  # per-model expressed-isoform count
        med_frac = float(np.median(frac))
        # modal dominant ENST across models (which isoform is the per-model argmax most often)
        dom_idx = b.argmax(axis=1)
        vals, counts = np.unique(dom_idx, return_counts=True)
        modal_local = int(vals[counts.argmax()])
        rows.append(
            {
                "gene_symbol": g.upper(),
                "isoform_expression_class": _classify(med_frac),
                "dominant_isoform_fraction": med_frac,
                "n_expressed_isoforms": int(np.median(n_iso)),
                "dominant_isoform": str(enst_ids[gcols][modal_local]),
                "n_models": n_models,
            }
        )
    rows.sort(key=lambda r: r["gene_symbol"])  # physical sort on the emitted uppercase read key
    return pa.Table.from_pylist(rows, schema=_schema())


def _schema():
    import pyarrow as pa

    return pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("isoform_expression_class", pa.string()),
            pa.field("dominant_isoform_fraction", pa.float64()),
            pa.field("n_expressed_isoforms", pa.int64()),
            pa.field("dominant_isoform", pa.string()),
            pa.field("n_models", pa.int64()),
        ]
    )


_PRODUCT_FILENAME = "depmap_isoform_expression.parquet"


def build_and_upload(local_csv: Optional[str] = None, upload: bool = False, out_dir: Optional[str] = None) -> dict:
    """Build the gene-sorted isoform-expression product; write parquet locally; optionally upload to S3.
    Returns {n_genes, class_distribution, md5, size_bytes, s3_uri, local_path}. S3 key resolution is
    kept lazy (in-function) so importing this module never touches the catalog."""
    import hashlib

    import pyarrow.parquet as pq

    tbl = build_isoform_table(local_csv=local_csv)
    out_dir = out_dir or os.path.join(os.path.expanduser("~"), ".cache", "framework-isoform")
    os.makedirs(out_dir, exist_ok=True)
    local_path = os.path.join(out_dir, _PRODUCT_FILENAME)
    pq.write_table(tbl, local_path, row_group_size=8192, compression="snappy")
    with open(local_path, "rb") as fh:
        data = fh.read()
    md5 = hashlib.md5(data).hexdigest()
    classes = tbl.column("isoform_expression_class").to_pylist()
    from collections import Counter

    class_distribution = dict(Counter(classes))
    s3_uri = f"s3://{S3_BUCKET}/data-catalog/derived/{PRODUCT_MANIFEST_ID}/{_PRODUCT_FILENAME}"
    if upload:
        key = f"data-catalog/derived/{PRODUCT_MANIFEST_ID}/{_PRODUCT_FILENAME}"
        ensure_aws_profile()
        _boto3().put_object(Bucket=S3_BUCKET, Key=key, Body=data)
    return {
        "n_genes": tbl.num_rows,
        "class_distribution": class_distribution,
        "md5": md5,
        "size_bytes": len(data),
        "s3_uri": s3_uri,
        "local_path": local_path,
    }


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description="Build depmap-isoform-expression-per-gene-v1")
    ap.add_argument("--local-csv", default=None, help="pre-downloaded transcript-TPM CSV (else stream from S3)")
    ap.add_argument("--upload", action="store_true", help="upload the parquet to S3")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    print(json.dumps(build_and_upload(local_csv=args.local_csv, upload=args.upload, out_dir=args.out_dir), indent=1))
