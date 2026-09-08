#!/usr/bin/env python3
"""build_by_lineage — per-gene × per-lineage organoid CRISPR dependency (DepMap 26Q1).

Companion to build.py (the pan-organoid per-gene summary). Joins OrganoidGeneEffect.csv to
Model.csv's OncotreeLineage and rolls each gene up WITHIN each organoid lineage, so the
organoid-crispr-dependency card can answer the indication-conditioned question "is {target} a
dependency in the ORGANOID lineage that matches this indication?" (e.g. COADREAD→Bowel,
PAAD→Pancreas, STAD/ESCA→Esophagus/Stomach, BRCA→Breast, PRAD→Prostate).

Only lineages with a cohort of at least MIN_LINEAGE_COHORT organoids are emitted — below that the
per-lineage fraction is uninterpretable. In 26Q1 that admits the GI-heavy + breast + prostate
lineages (Esophagus/Stomach 28, Pancreas 23, Bowel 22, Breast 16, Prostate 9); the tiny lineages
(Uterus/Ampulla/Ovary/Biliary/HNSC/Lung, each <10, several ≤4) are dropped and LOGGED so the
coverage gap is explicit, never silent.

Output: organoid-crispr-dependency-by-lineage-26q1-v1/organoid_dependency_by_lineage.parquet
(sorted by gene_symbol so the card reader pushes down per-gene, then filters lineage in-frame).

Usage:
  python -m methods.organoid_dependency_precompute.build_by_lineage \\
      --out <dir>/organoid_dependency_by_lineage.parquet [--no-upload]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path

S3_BUCKET = "onc-compbio"
OUTPUT_S3_PREFIX = "data-catalog/derived/organoid-crispr-dependency-by-lineage-26q1-v1"
_SRC_PREFIX = "data-catalog/sources/depmap-consortium/dmc-26q1"
_S3_MATRIX = f"s3://{S3_BUCKET}/{_SRC_PREFIX}/OrganoidGeneEffect.csv"
_S3_MODEL = f"s3://{S3_BUCKET}/{_SRC_PREFIX}/Model.csv"

DEPENDENT_CUTOFF = -0.5
STRONG_CUTOFF = -1.0
# Below this many organoids in a lineage, the per-lineage dependency fraction is uninterpretable.
MIN_LINEAGE_COHORT = 5

_COL_RE = re.compile(r"^(?P<sym>.+?)\s+\((?P<entrez>\d+)\)$")

# Spot-checks (verified live at build; logged, non-fatal): KRAS is a strong dependency in the
# GI-driver lineages (Bowel/Pancreas), a ribosomal gene is pan-essential in every lineage.
CORRECTNESS_CHECKS = [  # (symbol, lineage, field, comparator, threshold)
    ("KRAS", "Pancreas", "frac_dependent", ">=", 0.60),
    ("KRAS", "Bowel", "frac_dependent", ">=", 0.60),
    ("RPL9", "Bowel", "frac_dependent", ">=", 0.90),
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
    import pandas as pd

    if uri.startswith("s3://"):
        from io import BytesIO

        import boto3

        bucket, _, key = uri[len("s3://") :].partition("/")
        body = boto3.Session(profile_name="cbg").client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        return pd.read_csv(BytesIO(body), **kw)
    return pd.read_csv(uri, **kw)


def build(matrix_uri: str = _S3_MATRIX, model_uri: str = _S3_MODEL):
    import numpy as np
    import pandas as pd

    t0 = time.time()
    df = _read_csv(matrix_uri, index_col=0)  # organoid ModelID × 'SYMBOL (ENTREZ)'
    _log(f"[read] {df.shape[0]} organoid models × {df.shape[1]} genes in {time.time() - t0:.1f}s")

    model = _read_csv(model_uri, usecols=["ModelID", "OncotreeLineage"])
    lin_by_model = dict(zip(model["ModelID"], model["OncotreeLineage"]))
    lineages = pd.Series({m: lin_by_model.get(m) for m in df.index})

    # Which lineages clear the cohort floor?
    counts = lineages.value_counts()
    admitted = sorted([lin for lin, n in counts.items() if lin and n >= MIN_LINEAGE_COHORT])
    _log(f"[lineage] admitted (n>={MIN_LINEAGE_COHORT}): " + ", ".join(f"{l}={int(counts[l])}" for l in admitted))
    dropped = [(lin, int(n)) for lin, n in counts.items() if lin and n < MIN_LINEAGE_COHORT]
    if dropped:
        _log("[lineage] DROPPED (below floor, not emitted): " + ", ".join(f"{l}={n}" for l, n in sorted(dropped)))

    # Parse gene column headers once.
    col_meta = []
    for col in df.columns:
        mo = _COL_RE.match(col)
        col_meta.append((col, mo.group("sym") if mo else col, mo.group("entrez") if mo else None))

    rows = []
    for lin in admitted:
        sub = df.loc[lineages[lineages == lin].index]  # organoids in this lineage × genes
        n_cohort = int(sub.shape[0])
        vals = sub.to_numpy(dtype="float64")  # models × genes
        obs_mask = ~np.isnan(vals)
        n_screened = obs_mask.sum(axis=0)  # per gene
        n_dep = np.nansum(vals < DEPENDENT_CUTOFF, axis=0)
        n_strong = np.nansum(vals < STRONG_CUTOFF, axis=0)
        median = np.nanmedian(np.where(obs_mask, vals, np.nan), axis=0)
        for j, (_col, sym, entrez) in enumerate(col_meta):
            ns = int(n_screened[j])
            if ns == 0:
                continue  # gene not screened in any organoid of this lineage
            rows.append(
                (
                    sym,
                    entrez,
                    lin,
                    n_cohort,
                    ns,
                    int(n_dep[j]),
                    float(n_dep[j]) / ns,
                    int(n_strong[j]),
                    float(median[j]),
                )
            )

    out = pd.DataFrame(
        rows,
        columns=[
            "gene_symbol",
            "entrez_gene_id",
            "lineage",
            "n_lineage_cohort",
            "n_models_screened",
            "n_dependent",
            "frac_dependent",
            "n_strongly_dependent",
            "median_gene_effect",
        ],
    )
    out["frac_dependent"] = out["frac_dependent"].astype("float32")
    out["median_gene_effect"] = out["median_gene_effect"].astype("float32")
    for c in ["n_lineage_cohort", "n_models_screened", "n_dependent", "n_strongly_dependent"]:
        out[c] = out[c].astype("int32")
    # gene_symbol primary sort (pushdown key); lineage secondary for stable in-frame ordering.
    out = out.sort_values(["gene_symbol", "lineage"]).reset_index(drop=True)
    return out


def write(df, out: Path, row_group_size: int = 16384) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    out.parent.mkdir(parents=True, exist_ok=True)
    schema = pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("entrez_gene_id", pa.string()),
            pa.field("lineage", pa.string()),
            pa.field("n_lineage_cohort", pa.int32()),
            pa.field("n_models_screened", pa.int32()),
            pa.field("n_dependent", pa.int32()),
            pa.field("frac_dependent", pa.float32()),
            pa.field("n_strongly_dependent", pa.int32()),
            pa.field("median_gene_effect", pa.float32()),
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
    p = argparse.ArgumentParser(description="Build the per-lineage organoid CRISPR dependency product.")
    p.add_argument("--matrix", default=_S3_MATRIX)
    p.add_argument("--model", default=_S3_MODEL)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--row-group-size", type=int, default=16384)
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args(argv)

    df = build(args.matrix, args.model)
    meta = write(df, args.out, args.row_group_size)
    _log(f"[write] {args.out.name}: {meta['n_rows']} (gene,lineage) rows / {meta['size_bytes']} B / md5={meta['md5']}")

    for sym, lin, field, cmp_, thresh in CORRECTNESS_CHECKS:
        sub = df[(df["gene_symbol"] == sym) & (df["lineage"] == lin)]
        if len(sub):
            val = float(sub[field].iloc[0])
            ok = val >= thresh if cmp_ == ">=" else val <= thresh
            _log(f"  check {sym}@{lin}.{field}={val:.3f} {cmp_} {thresh} {'OK' if ok else 'UNEXPECTED'}")
        else:
            _log(f"  check {sym}@{lin}: absent (skipped)")

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
