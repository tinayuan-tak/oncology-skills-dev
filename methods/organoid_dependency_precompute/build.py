#!/usr/bin/env python3
"""build — DepMap 26Q1 organoid-native CRISPR dependency summary (per-gene).

Reads OrganoidGeneEffect.csv (organoid ModelID × gene Chronos gene-effect; column headers
are 'SYMBOL (ENTREZ)') and emits a gene-sorted per-gene dependency summary: how many organoid
models were screened for each gene, in what fraction the gene is a dependency (Chronos
gene-effect below the standard -0.5 / strong -1.0 cutoffs), the central-tendency effect, and a
0-100 organoid-cohort dependency percentile (rank of -median across all genes; higher = more
dependent). Reads Model.csv only to LOG cohort composition (the per-gene product is pan-organoid).

Output: organoid-crispr-dependency-26q1-v1/organoid_dependency_summary.parquet (gene-sorted).

Usage:
  python -m methods.organoid_dependency_precompute.build \\
      --out <dir>/organoid_dependency_summary.parquet [--no-upload]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path

S3_BUCKET = "onc-compbio"
OUTPUT_S3_PREFIX = "data-catalog/derived/organoid-crispr-dependency-26q1-v1"
# Source release files (DepMap Consortium 26Q1). The organoid-only Chronos matrix + Model.csv.
_SRC_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1"
_S3_MATRIX = f"s3://{S3_BUCKET}/{_SRC_PREFIX}/OrganoidGeneEffect.csv"
_S3_MODEL = f"s3://{S3_BUCKET}/{_SRC_PREFIX}/Model.csv"

# Chronos dependency cutoffs (DepMap-standard). gene-effect < -0.5 = dependent; < -1.0 = strong.
DEPENDENT_CUTOFF = -0.5
STRONG_CUTOFF = -1.0

# DepMap wide columns are 'SYMBOL (ENTREZ)'; split to (symbol, entrez).
_COL_RE = re.compile(r"^(?P<sym>.+?)\s+\((?P<entrez>\d+)\)$")

# Correctness spot-checks (verified live at build): pan-essential genes must be near-ubiquitous
# organoid dependencies; a lineage-restricted non-essential must not be.
CORRECTNESS_CHECKS = [  # (symbol, field, comparator, threshold)
    ("RPL9", "frac_dependent", ">=", 0.90),  # core ribosomal → pan-organoid essential
    ("POLR2B", "frac_dependent", ">=", 0.90),  # RNA Pol II → pan-organoid essential
    ("KRT5", "frac_dependent", "<=", 0.20),  # basal-keratin marker → not broadly essential
]


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324 — content digest, not security
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_csv(uri: str, **kw):
    """Read a DepMap source CSV from s3:// (cbg profile — the bucket denies the default role)
    or a local path."""
    import pandas as pd

    if uri.startswith("s3://"):
        from io import BytesIO

        import boto3

        bucket, _, key = uri[len("s3://") :].partition("/")
        body = boto3.Session(profile_name="cbg").client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        return pd.read_csv(BytesIO(body), **kw)
    return pd.read_csv(uri, **kw)


def _log_cohort_composition(model_uri: str, model_ids) -> None:
    """LOG-only cohort characterization (lineage/disease breakdown). Not emitted into the per-gene
    product — recorded so the data-catalog manifest + card context can cite the exact composition."""
    try:
        m = _read_csv(model_uri, usecols=["ModelID", "OncotreeLineage", "ModelType"])
    except Exception as e:  # noqa: BLE001 — cohort log is advisory
        _log(f"[cohort] Model.csv unavailable ({type(e).__name__}); skipping composition log")
        return
    m = m[m["ModelID"].isin(set(model_ids))]
    _log(f"[cohort] {len(m)} organoid models; ModelType={sorted(m['ModelType'].dropna().unique())}")
    for lineage, n in m["OncotreeLineage"].value_counts().items():
        _log(f"  {n:3d}  {lineage}")


def build(matrix_uri: str = _S3_MATRIX, model_uri: str = _S3_MODEL):
    import pandas as pd

    t0 = time.time()
    df = _read_csv(matrix_uri, index_col=0)  # rows = organoid ModelIDs, cols = 'SYMBOL (ENTREZ)'
    _log(f"[read] {df.shape[0]} organoid models × {df.shape[1]} genes in {time.time() - t0:.1f}s")
    n_models_total = int(df.shape[0])
    _log_cohort_composition(model_uri, df.index.tolist())

    # Per-gene (column) statistics over the organoid cohort. NaN = gene not screened in that model.
    n_screened = df.notna().sum(axis=0)
    n_dependent = (df < DEPENDENT_CUTOFF).sum(axis=0)
    n_strong = (df < STRONG_CUTOFF).sum(axis=0)
    mean_eff = df.mean(axis=0)
    median_eff = df.median(axis=0)
    min_eff = df.min(axis=0)

    rows = []
    for col in df.columns:
        mo = _COL_RE.match(col)
        sym = mo.group("sym") if mo else col
        entrez = mo.group("entrez") if mo else None
        ns = int(n_screened[col])
        rows.append(
            (
                sym,
                entrez,
                ns,
                int(n_dependent[col]),
                int(n_strong[col]),
                (float(n_dependent[col]) / ns) if ns else 0.0,
                (float(n_strong[col]) / ns) if ns else 0.0,
                float(mean_eff[col]),
                float(median_eff[col]),
                float(min_eff[col]),
            )
        )
    out = pd.DataFrame(
        rows,
        columns=[
            "gene_symbol",
            "entrez_gene_id",
            "n_models_screened",
            "n_dependent",
            "n_strongly_dependent",
            "frac_dependent",
            "frac_strongly_dependent",
            "mean_gene_effect",
            "median_gene_effect",
            "min_gene_effect",
        ],
    )

    # Organoid-cohort dependency percentile: rank of the gene's MEDIAN gene-effect, ascending on
    # -median so a MORE-negative (more dependent) median → HIGHER percentile. 100 = most dependent.
    out["organoid_dependency_percentile"] = ((-out["median_gene_effect"]).rank(pct=True) * 100.0).astype("float32")
    out["n_models_total"] = n_models_total
    out["n_genes"] = len(out)

    for c in ["frac_dependent", "frac_strongly_dependent", "mean_gene_effect", "median_gene_effect", "min_gene_effect"]:
        out[c] = out[c].astype("float32")
    out = out.sort_values("gene_symbol").reset_index(drop=True)
    return out


def write(df, out: Path, row_group_size: int = 8192) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    out.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("entrez_gene_id", pa.string()),
            pa.field("n_models_screened", pa.int32()),
            pa.field("n_dependent", pa.int32()),
            pa.field("n_strongly_dependent", pa.int32()),
            pa.field("frac_dependent", pa.float32()),
            pa.field("frac_strongly_dependent", pa.float32()),
            pa.field("mean_gene_effect", pa.float32()),
            pa.field("median_gene_effect", pa.float32()),
            pa.field("min_gene_effect", pa.float32()),
            pa.field("organoid_dependency_percentile", pa.float32()),
            pa.field("n_models_total", pa.int32()),
            pa.field("n_genes", pa.int32()),
        ]
    )
    pq.write_table(
        pa.Table.from_pandas(df[[f.name for f in schema]], schema=schema, preserve_index=False),
        str(out),
        compression="snappy",
        row_group_size=row_group_size,
    )
    return {"md5": _md5_hex(out), "size_bytes": out.stat().st_size, "n_rows": len(df)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Build the DepMap 26Q1 organoid CRISPR dependency summary.")
    p.add_argument("--matrix", default=_S3_MATRIX)
    p.add_argument("--model", default=_S3_MODEL)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--row-group-size", type=int, default=8192)
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args(argv)

    df = build(args.matrix, args.model)
    meta = write(df, args.out, args.row_group_size)
    _log(f"[write] {args.out.name}: {meta['n_rows']} genes / {meta['size_bytes']} B / md5={meta['md5']}")

    for sym, field, cmp_, thresh in CORRECTNESS_CHECKS:
        sub = df[df["gene_symbol"] == sym]
        if len(sub):
            val = float(sub[field].iloc[0])
            ok = val >= thresh if cmp_ == ">=" else val <= thresh
            _log(f"  check {sym}.{field}={val:.3f} {cmp_} {thresh} {'OK' if ok else 'UNEXPECTED'}")
        else:
            _log(f"  check {sym}: absent from matrix (skipped)")

    if not args.no_upload:
        import boto3

        key = f"{OUTPUT_S3_PREFIX}/{args.out.name}"
        boto3.Session(profile_name="cbg").client("s3").upload_file(
            str(args.out), S3_BUCKET, key, ExtraArgs={"Metadata": {"md5": meta["md5"]}}
        )
        _log(f"[upload] s3://{S3_BUCKET}/{key}")
    else:
        _log("[upload] skipped (--no-upload)")
    print(f"md5={meta['md5']} size_bytes={meta['size_bytes']} n_rows={meta['n_rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
