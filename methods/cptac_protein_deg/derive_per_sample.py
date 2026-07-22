#!/usr/bin/env python3
"""derive_per_sample — persist the CPTAC per-sample protein log-ratio long-form product.

The per-sample analogue of the wide/long TCGA + GTEx TPM products. The existing
cptac-protein-tumor-vs-normal-per-cohort-v1 product aggregates per-sample abundances into per-cohort
MEDIANS + effect sizes (no per-sample values), so it cannot back true distribution boxplots. This
module persists the per-(gene, aliquot) log-ratios — the same values stage 01 reshapes on its way to
MSstatsTMT, but kept in clean long form instead of mangled into the MSstatsTMT dummy frame.

NO R / MSstatsTMT: this is a direct reshape of the CPTAC tmt10.tsv gene-level log-ratio matrices
(gene × TMT-channel) + the sample.txt channel→aliquot map + the stage-00 PDC tumor/normal
annotations. Reuses the proven stage-01 helpers (parse_sample_txt, list_proteome_keys, canonical_
aliquot, CPTAC_STUDIES, the Condition map) — same join, different (honest) output.

Output long/tidy parquet, columns:
    gene_symbol            string   CPTAC gene symbol (tmt10.tsv "Gene" column)
    cohort                 string   CPTAC cohort (BRCA, COAD, GBM, ...)
    aliquot_submitter_id   string   per-sample aliquot (the distribution unit)
    sample_type            string   PDC sample_type (Primary Tumor / Solid Tissue Normal / ...)
    condition              string   Tumor | Normal (the plot grouping)
    log2_ratio             float32  gene-level log2 tumor-vs-reference ratio (tmt10 "Log Ratio")
Sorted by (gene_symbol, cohort) with row-group pushdown so a per-gene distribution read is fast.

Usage:
    python -m methods.cptac_protein_deg.derive_per_sample \\
        --work-dir ~/dev/framework-runs/cptac-per-sample-v1 \\
        --out      ~/dev/framework-runs/cptac-per-sample-v1/cptac_protein_per_sample.parquet \\
        --no-upload   # omit to upload to
                      # s3://onc-compbio/data-catalog/derived/cptac-protein-tumor-vs-normal-per-sample-v1/
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import sys
import time
from pathlib import Path

DEPMAP_S3_BUCKET = "onc-compbio"
OUTPUT_S3_PREFIX = "data-catalog/derived/cptac-protein-tumor-vs-normal-per-sample-v1"

_STEPS = Path(__file__).resolve().parent / "steps"


def _load_stage01():
    """Import the stage-01 module (filename starts with '01_', not a normal import name)."""
    spec = importlib.util.spec_from_file_location(
        "cptac_stage01", _STEPS / "01_prepare_msstats_input.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _load_stage00():
    spec = importlib.util.spec_from_file_location(
        "cptac_stage00", _STEPS / "00_pull_annotations.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324 — integrity, not security
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def per_sample_cohort(s01, cohort: str, work_dir: Path, annotations_dir: Path):
    """Return the clean per-sample long DataFrame for one cohort:
    (gene_symbol, cohort, aliquot_submitter_id, sample_type, condition, log2_ratio).
    Mirrors stage-01 prep_cohort's reshape UP TO the clean `long` frame — but keeps the raw log-ratio
    per (gene, aliquot) instead of exponentiating into the MSstatsTMT Intensity dummy."""
    import pandas as pd

    pdc_id, _stem = s01.CPTAC_STUDIES[cohort]
    keys = s01.list_proteome_keys(pdc_id)
    tmt10_key = (s01.find_key(keys, ".tmt10.tsv") or s01.find_key(keys, ".tmt11.tsv")
                 or s01.find_key(keys, ".itraq.tsv"))
    sample_key = s01.find_key(keys, ".sample.txt")
    if not tmt10_key or not sample_key:
        raise FileNotFoundError(f"[{cohort}] missing tmt10.tsv or sample.txt")

    scratch = work_dir / cohort
    scratch.mkdir(parents=True, exist_ok=True)
    tmt10_local = scratch / Path(tmt10_key).name
    sample_local = scratch / Path(sample_key).name
    s01.download(tmt10_key, tmt10_local)
    s01.download(sample_key, sample_local)

    ann_path = annotations_dir / f"{cohort}_aliquot_annotations.tsv"
    if not ann_path.exists():
        raise FileNotFoundError(f"[{cohort}] no annotations at {ann_path}; run stage 00 first")
    ann = pd.read_csv(ann_path, sep="\t", dtype=str)
    ann_map = dict(zip(ann["aliquot_submitter_id"], ann["sample_type"]))

    sample_map = s01.parse_sample_txt(sample_local)
    sample_map["sample_type"] = sample_map["aliquot_submitter_id"].map(ann_map)
    sample_map["condition"] = sample_map["sample_type"].map({
        "Primary Tumor": "Tumor", "Metastatic": "Tumor", "Recurrent Tumor": "Tumor",
        "Solid Tissue Normal": "Normal", "Blood Derived Normal": "Normal",
    })
    sample_map = sample_map.dropna(subset=["condition"]).copy()

    tmt = pd.read_csv(tmt10_local, sep="\t", low_memory=False)
    tmt = tmt[~tmt["Gene"].isin(["Mean", "Median", "StdDev", "NumRatios"])]
    log_ratio_cols = [c for c in tmt.columns if c.endswith(" Log Ratio")
                      and not c.endswith("Unshared Log Ratio")]
    aliquot_by_col = {c: s01.canonical_aliquot(c) for c in log_ratio_cols}
    valid_aliquots = set(sample_map["aliquot_submitter_id"])
    kept_cols = [c for c in log_ratio_cols if aliquot_by_col[c] in valid_aliquots]

    tmt = tmt[["Gene"] + kept_cols].melt(id_vars=["Gene"], var_name="col", value_name="log2_ratio")
    tmt["aliquot_submitter_id"] = tmt["col"].map(aliquot_by_col)
    tmt = tmt.drop(columns=["col"])
    tmt["log2_ratio"] = pd.to_numeric(tmt["log2_ratio"], errors="coerce")
    tmt = tmt.dropna(subset=["log2_ratio"])

    long = tmt.merge(
        sample_map[["aliquot_submitter_id", "sample_type", "condition"]],
        on="aliquot_submitter_id", how="inner")
    long = long.rename(columns={"Gene": "gene_symbol"})
    long["cohort"] = cohort
    long["log2_ratio"] = long["log2_ratio"].astype("float32")
    out = long[["gene_symbol", "cohort", "aliquot_submitter_id",
                "sample_type", "condition", "log2_ratio"]]
    n_t = int((sample_map["condition"] == "Tumor").sum())
    n_n = int((sample_map["condition"] == "Normal").sum())
    _log(f"  [{cohort}] {len(out):,} rows | {out['gene_symbol'].nunique()} genes | "
         f"{n_t} tumor + {n_n} normal aliquots")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--annotations-dir", type=Path, default=None,
                    help="Dir with <cohort>_aliquot_annotations.tsv (stage 00). "
                         "Default: <work-dir>/annotations (run stage 00 if absent).")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cohorts", default=None, help="Comma-separated subset (default: all 10).")
    ap.add_argument("--row-group-size", type=int, default=16384)
    ap.add_argument("--no-upload", action="store_true")
    args = ap.parse_args()

    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    args.work_dir.mkdir(parents=True, exist_ok=True)
    ann_dir = args.annotations_dir or (args.work_dir / "annotations")
    s01 = _load_stage01()
    cohorts = ([c.strip().upper() for c in args.cohorts.split(",")]
               if args.cohorts else list(s01.CPTAC_STUDIES.keys()))

    # Stage 00 (PDC annotations) if not already present.
    if not ann_dir.exists() or not any(ann_dir.glob("*_aliquot_annotations.tsv")):
        _log(f"[per-sample] stage 00: pulling PDC aliquot annotations -> {ann_dir}")
        s00 = _load_stage00()
        ann_dir.mkdir(parents=True, exist_ok=True)
        for cohort in cohorts:
            pdc_id, _ = s01.CPTAC_STUDIES[cohort]
            rows = s00.query_study(cohort, pdc_id)
            s00.write_tsv(cohort, rows, ann_dir / f"{cohort}_aliquot_annotations.tsv")

    _log(f"[per-sample] reshaping {len(cohorts)} cohorts -> long form")
    t0 = time.monotonic()
    frames = []
    skipped = []
    for cohort in cohorts:
        try:
            frames.append(per_sample_cohort(s01, cohort, args.work_dir, ann_dir))
        except Exception as e:  # noqa: BLE001 — one cohort must not lose the rest
            _log(f"  [{cohort}] SKIPPED — {type(e).__name__}: {e}")
            skipped.append(cohort)
    if not frames:
        _log("[per-sample] no cohorts produced data")
        return 1

    allrows = pd.concat(frames, ignore_index=True)
    allrows = allrows.sort_values(["gene_symbol", "cohort"]).reset_index(drop=True)
    _log(f"[per-sample] concatenated: {len(allrows):,} rows across {len(frames)} cohorts "
         f"({time.monotonic()-t0:.0f}s)" + (f" (skipped: {', '.join(skipped)})" if skipped else ""))

    schema = pa.schema([
        pa.field("gene_symbol", pa.string()), pa.field("cohort", pa.string()),
        pa.field("aliquot_submitter_id", pa.string()), pa.field("sample_type", pa.string()),
        pa.field("condition", pa.string()), pa.field("log2_ratio", pa.float32()),
    ])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pandas(allrows, schema=schema, preserve_index=False),
                   str(args.out), compression="snappy", row_group_size=args.row_group_size)
    size_bytes = args.out.stat().st_size
    md5 = _md5_hex(args.out)
    _log(f"[per-sample] wrote {args.out} ({size_bytes/1e6:.1f} MB) md5={md5}")
    _log(f"[per-sample] n_rows={len(allrows)} n_genes={allrows['gene_symbol'].nunique()} "
         f"n_cohorts={allrows['cohort'].nunique()} n_aliquots={allrows['aliquot_submitter_id'].nunique()}")

    if not args.no_upload:
        import boto3
        key = f"{OUTPUT_S3_PREFIX}/{args.out.name}"
        _log(f"[per-sample] uploading -> s3://{DEPMAP_S3_BUCKET}/{key}")
        boto3.client("s3").upload_file(str(args.out), DEPMAP_S3_BUCKET, key,
                                       ExtraArgs={"Metadata": {"md5": md5}})
    _log("[per-sample] done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
