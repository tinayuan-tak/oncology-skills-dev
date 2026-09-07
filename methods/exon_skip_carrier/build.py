"""exon_skip_carrier.build — materialize the position-bearing DepMap splice-variant product.

Produces `depmap-somatic-splice-variants-v1`: every splice-classified somatic variant across
the DepMap panel, WITH genomic coordinates, gene-sorted. This exists because the standard
derived DepMap somatic parquet (methods.depmap_common.parquet) drops Chromosome/Start_Position,
so exon-skip events (METex14) cannot be isolated from it — a coordinate-less table can only
say "MET has a splice variant", not "MET has a splice variant inside the exon-14 window".

The product is small (splice variants are a fraction of the MAF), so downstream consumers
(exon_skip_carrier.read) do a cheap gene-sorted pushdown instead of streaming the ~738 MB raw
MAF per query. Event-AGNOSTIC: it retains raw coordinates + classification; the window/event
logic stays in events.py + classify.py.

CLI:  python -m methods.exon_skip_carrier.build --upload    # build from raw MAF, upload, pin md5
"""
from __future__ import annotations

import hashlib
import os
from typing import Iterable, Optional

METHOD_VERSION = "0.1.0"

DEFAULT_AWS_PROFILE = "cbg"
DEPMAP_SOURCE_MANIFEST_ID = "depmap-consortium-26q1"
PRODUCT_MANIFEST_ID = "depmap-somatic-splice-variants-v1"
_PRODUCT_FILENAME = "depmap_somatic_splice_variants.parquet"
_MAF_FILENAME = "OmicsSomaticMutationsMAF.maf"

# A variant is retained iff its Variant_Classification contains this token (case-insensitive).
# Covers MAF title-case Splice_Site / Splice_Region (the only splice classes DepMap emits).
_SPLICE_TOKEN = "splice"


def _norm_chrom(c: str) -> str:
    c = (c or "").strip()
    return c if c.lower().startswith("chr") else (f"chr{c}" if c else c)


def splice_rows_from_maf(rows: Iterable[list]) -> list:
    """Adapt raw-MAF rows (first row = header) into gene-sorted splice-variant dict rows.

    Retains every variant whose Variant_Classification contains 'splice'. Deterministic;
    unit-testable with synthetic rows. Returns rows sorted by (gene_symbol, chrom, start).
    """
    it = iter(rows)
    header = next(it)
    ix = {name: i for i, name in enumerate(header)}
    gi, ci, si, ei, vi = (ix.get("Hugo_Symbol"), ix.get("Chromosome"), ix.get("Start_Position"),
                          ix.get("End_Position"), ix.get("Variant_Classification"))
    mi = ix.get("ModelID")
    vti = ix.get("VariantType", ix.get("Variant_Type"))
    required = {"Hugo_Symbol": gi, "Chromosome": ci, "Start_Position": si,
                "Variant_Classification": vi, "ModelID": mi}
    missing = [n for n, i in required.items() if i is None]
    if missing:
        raise ValueError(f"raw MAF missing required columns: {missing}")
    out = []
    for r in it:
        top = max(gi, ci, si, vi, mi, ei or 0, vti or 0)
        if len(r) <= top:
            continue
        vc = r[vi]
        if _SPLICE_TOKEN not in (vc or "").lower():
            continue
        try:
            start = int(r[si])
        except (ValueError, TypeError):
            continue  # a splice variant with no parseable position is useless here
        try:
            end = int(r[ei]) if ei is not None and r[ei] not in ("", None) else start
        except (ValueError, TypeError):
            end = start
        out.append({
            "gene_symbol": (r[gi] or "").strip().upper(),
            "model_id": r[mi],
            "chrom": _norm_chrom(r[ci]),
            "start_position": start,
            "end_position": end,
            "variant_classification": vc,
            "variant_type": (r[vti] if vti is not None and len(r) > vti else None),
        })
    out.sort(key=lambda d: (d["gene_symbol"], d["chrom"], d["start_position"], d["model_id"]))
    return out


def _schema():
    import pyarrow as pa
    return pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("model_id", pa.string()),
        pa.field("chrom", pa.string()),
        pa.field("start_position", pa.int64()),
        pa.field("end_position", pa.int64()),
        pa.field("variant_classification", pa.string()),
        pa.field("variant_type", pa.string()),
    ])


def build_table(rows: Iterable[list]):
    import pyarrow as pa
    return pa.Table.from_pylist(splice_rows_from_maf(rows), schema=_schema())


def _boto3():
    import boto3
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", DEFAULT_AWS_PROFILE)).client("s3")


def _stream_raw_maf() -> Iterable[list]:
    from methods.catalog_query.read import bucket_prefix_for
    bucket, prefix = bucket_prefix_for(DEPMAP_SOURCE_MANIFEST_ID)
    key = f"{prefix.rstrip('/')}/{_MAF_FILENAME}"
    body = _boto3().get_object(Bucket=bucket, Key=key)["Body"]
    header_sent = False
    for raw in body.iter_lines():
        line = raw.decode("utf-8", "replace")
        if not header_sent:
            if line.startswith("#") or not line.strip():
                continue
            header_sent = True
        yield line.split("\t")


def build_and_upload(upload: bool = False, out_dir: Optional[str] = None) -> dict:
    """Build the product from the live raw MAF; write parquet locally; optionally upload to S3.
    Returns {rows, n_genes, md5, size_bytes, s3_uri, local_path}."""
    import pyarrow.parquet as pq
    tbl = build_table(_stream_raw_maf())
    out_dir = out_dir or os.path.join(os.path.expanduser("~"), ".cache", "framework-exon-skip")
    os.makedirs(out_dir, exist_ok=True)
    local_path = os.path.join(out_dir, _PRODUCT_FILENAME)
    pq.write_table(tbl, local_path, row_group_size=8192, compression="snappy")
    with open(local_path, "rb") as fh:
        data = fh.read()
    md5 = hashlib.md5(data).hexdigest()
    s3_uri = f"s3://onc-compbio/data-catalog/derived/{PRODUCT_MANIFEST_ID}/{_PRODUCT_FILENAME}"
    if upload:
        bucket = "onc-compbio"
        key = f"data-catalog/derived/{PRODUCT_MANIFEST_ID}/{_PRODUCT_FILENAME}"
        _boto3().put_object(Bucket=bucket, Key=key, Body=data)
    genes = tbl.column("gene_symbol").to_pylist()
    return {
        "rows": tbl.num_rows,
        "n_genes": len(set(genes)),
        "md5": md5,
        "size_bytes": len(data),
        "s3_uri": s3_uri,
        "local_path": local_path,
    }


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser(description="Build depmap-somatic-splice-variants-v1")
    ap.add_argument("--upload", action="store_true", help="upload the parquet to S3")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()
    print(json.dumps(build_and_upload(upload=args.upload, out_dir=args.out_dir), indent=1))
