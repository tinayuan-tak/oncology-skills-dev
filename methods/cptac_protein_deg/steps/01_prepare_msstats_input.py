#!/usr/bin/env python3
"""Stage 01 — reshape CPTAC tmt10.tsv + sample.txt + PDC annotations into
MSstatsTMT-ready long-form TSV per cohort.

MSstatsTMT expects an input frame with columns:
    ProteinName  PSM  PeptideSequence  Charge  Channel  Condition
    BioReplicate  Run  Mixture  TechRepMixture  Intensity

CPTAC ships already-summarized gene-level log-ratio data (tmt10.tsv), not
raw PSMs. We adapt the input to MSstatsTMT's ProteinLevelData contract by
treating each Gene as a Protein with a single "pseudo-PSM" per aliquot.
`proteinSummarization(useLogMeasurements=TRUE)` accepts pre-aggregated
log values. `MSstatsTMT` treats `Intensity` as a linear scale; for
already-log data we exponentiate before feeding it in (MSstatsTMT then
log-transforms back internally with `logTrans=2`).

For each cohort emit a Feather (arrow) file rather than TSV: R reads it 5-10x
faster than TSV and preserves types. Columns emitted:
    ProteinName            gene symbol (tmt10.tsv first column)
    Charge                 fixed = 2 (dummy; required col)
    PeptideSequence        set to ProteinName (dummy; required col)
    PSM                    ProteinName + '_PSM1'
    Channel                TMT channel this aliquot occupies (from sample.txt)
    Condition              'Tumor' | 'Normal' | 'Norm' (Norm = reference-pool from PDC)
    BioReplicate           aliquot_submitter_id (case-derived)
    Run                    plex ID from sample.txt (AnalyticalSample col)
    Mixture                cohort-plex combined ID
    TechRepMixture         1 (no tech reps in CPTAC discovery)
    Intensity              2**log_ratio (undo log)

Reads:
    s3://onc-compbio/.../PDC######/Proteome/*.tmt10.tsv
    s3://onc-compbio/.../PDC######/Proteome/*.sample.txt
    <annotations_dir>/<cohort>_aliquot_annotations.tsv (from stage 00)
Writes:
    <work_dir>/<cohort>_msstats_input.feather
    <work_dir>/<cohort>_meta.json  (n_tumor, n_normal, n_genes, n_plexes)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import boto3
import pandas as pd
import pyarrow as pa
import pyarrow.feather as feather

S3_BUCKET = "onc-compbio"
CPTAC_PREFIX = "data-catalog/sources/pdc/cptac-snapshot-2026-07-01"

CPTAC_STUDIES = {
    "BRCA":  ("PDC000120", "CPTAC2_Breast_Prospective_Collection_BI_Proteome"),
    "COAD":  ("PDC000116", "CPTAC2_Prospective_Colon_PNNL_Proteome"),
    "OV":    ("PDC000110", "TCGA_Ovarian_JHU_Proteome"),
    "CCRCC": ("PDC000127", "CPTAC_CCRCC_Proteome"),
    "GBM":   ("PDC000204", "CPTAC3_Glioblastoma_Multiforme_Proteome"),
    "HNSCC": ("PDC000221", "CPTAC3_Head_and_Neck_Squamous_Cell_Carcinoma_Proteome"),
    "LUAD":  ("PDC000153", "CPTAC3_Lung_Adenocarcinoma_Proteome"),
    "LSCC":  ("PDC000234", "CPTAC3_Lung_Squamous_Cell_Carcinoma_Proteome"),
    "UCEC":  ("PDC000125", "CPTAC3_Uterine_Corpus_Endometrial_Carcinoma_Proteome"),
    "PDAC":  ("PDC000270", "CPTAC3_Pancreatic_Ductal_Adenocarcinoma_Proteome"),
}

TMT_CHANNELS = ["126", "127N", "127C", "128N", "128C", "129N", "129C", "130N", "130C", "131"]

s3 = None


def _s3():
    global s3
    if s3 is None:
        s3 = boto3.Session(profile_name="cbg").client("s3")
    return s3


def list_proteome_keys(pdc_id: str) -> list[str]:
    prefix = f"{CPTAC_PREFIX}/{pdc_id}/Proteome/"
    paginator = _s3().get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            keys.append(obj["Key"])
    return keys


def find_key(keys: list[str], suffix: str) -> str | None:
    """Return the first S3 key ending in `suffix`, excluding peptide-level TMT
    files (e.g. `.peptide.tmt11.tsv`). CPTAC PDC ships both gene- and
    peptide-level TMT files with overlapping suffixes; we always want the
    smaller, gene-level file."""
    for k in keys:
        if k.endswith(suffix) and ".peptide." not in k.rsplit("/", 1)[-1]:
            return k
    return None


def download(key: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    _s3().download_file(S3_BUCKET, key, str(dest))


def canonical_aliquot(colname: str) -> str:
    """Strip ' Log Ratio' + trailing '.N' technical-rep suffix."""
    s = re.sub(r"\s+(Log Ratio|Unshared Log Ratio)$", "", colname)
    s = re.sub(r"\.\d+$", "", s)  # drop .1 / .2 replicate suffix
    return s.strip()


def parse_sample_txt(sample_path: Path) -> pd.DataFrame:
    """Return a per-aliquot mapping: aliquot_submitter_id -> (Run, Channel).

    sample.txt schema (post-2016 CPTAC):
        FileNameRegEx | AnalyticalSample | 126 | 127N | ... | 131 | LabelReagent | Ratios
    Each row is one TMT plex; each channel column holds the aliquot occupying
    that channel. Channel "POOL" is a plex-reference pool (excluded).
    """
    df = pd.read_csv(sample_path, sep="\t", dtype=str)
    if "AnalyticalSample" not in df.columns:
        raise ValueError(f"sample.txt missing AnalyticalSample column: {sample_path}")
    long_rows = []
    for _, r in df.iterrows():
        plex = str(r["AnalyticalSample"]).strip()
        for ch in TMT_CHANNELS:
            if ch not in df.columns:
                continue
            aid = str(r[ch]).strip() if pd.notna(r[ch]) else ""
            if not aid or aid.upper() == "POOL" or "NULL" in aid.upper() or aid == "nan":
                continue
            # Drop optional _D# suffix comparison for join stability; keep raw for now
            long_rows.append({
                "aliquot_submitter_id": aid,
                "Run": plex,
                "Channel": ch,
            })
    return pd.DataFrame(long_rows)


def prep_cohort(cohort: str, work_dir: Path, annotations_dir: Path) -> dict:
    pdc_id, stem = CPTAC_STUDIES[cohort]
    t0 = time.time()

    keys = list_proteome_keys(pdc_id)
    tmt10_key = find_key(keys, ".tmt10.tsv") or find_key(keys, ".tmt11.tsv") or find_key(keys, ".itraq.tsv")
    sample_key = find_key(keys, ".sample.txt")
    if not tmt10_key or not sample_key:
        raise FileNotFoundError(
            f"[{cohort}] missing tmt10.tsv or sample.txt under s3://{S3_BUCKET}/{CPTAC_PREFIX}/{pdc_id}/Proteome/"
        )

    scratch = work_dir / cohort
    scratch.mkdir(parents=True, exist_ok=True)
    tmt10_local = scratch / Path(tmt10_key).name
    sample_local = scratch / Path(sample_key).name
    print(f"[01_prep {cohort}] downloading {tmt10_key.split('/')[-1]}", file=sys.stderr)
    download(tmt10_key, tmt10_local)
    download(sample_key, sample_local)

    # Load PDC annotations
    ann_path = annotations_dir / f"{cohort}_aliquot_annotations.tsv"
    if not ann_path.exists():
        raise FileNotFoundError(f"[{cohort}] no annotations at {ann_path}; run stage 00 first")
    ann = pd.read_csv(ann_path, sep="\t", dtype=str)
    ann_map = dict(zip(ann["aliquot_submitter_id"], ann["sample_type"]))

    # Parse sample.txt for plex + channel
    sample_map = parse_sample_txt(sample_local)
    # Build join key: sample.txt aliquot IDs may or may not match PDC exactly
    # (both are `<hex>_D#` short-forms). Join on exact match.
    sample_map["sample_type"] = sample_map["aliquot_submitter_id"].map(ann_map)
    sample_map["Condition"] = sample_map["sample_type"].map({
        "Primary Tumor": "Tumor",
        "Metastatic": "Tumor",
        "Recurrent Tumor": "Tumor",
        "Solid Tissue Normal": "Normal",
        "Blood Derived Normal": "Normal",
    })
    # Aliquots without a PDC annotation (usually plex-reference pools) → drop
    n_before = len(sample_map)
    sample_map = sample_map.dropna(subset=["Condition"]).copy()
    print(f"[01_prep {cohort}] sample.txt: {n_before} channels, "
          f"{len(sample_map)} with valid Tumor/Normal annotation", file=sys.stderr)

    # Load tmt10.tsv; keep only "Log Ratio" columns (drop "Unshared" for power)
    print(f"[01_prep {cohort}] parsing tmt10.tsv...", file=sys.stderr)
    tmt = pd.read_csv(tmt10_local, sep="\t", low_memory=False)
    # First col is Gene; skip Mean/Median/StdDev header rows
    tmt = tmt[~tmt["Gene"].isin(["Mean", "Median", "StdDev", "NumRatios"])]

    log_ratio_cols = [c for c in tmt.columns if c.endswith(" Log Ratio")
                      and not c.endswith("Unshared Log Ratio")]
    aliquot_by_col = {c: canonical_aliquot(c) for c in log_ratio_cols}

    # Only keep columns whose aliquot has a valid Condition
    valid_aliquots = set(sample_map["aliquot_submitter_id"])
    kept_cols = [c for c in log_ratio_cols if aliquot_by_col[c] in valid_aliquots]
    print(f"[01_prep {cohort}] tmt10 cols: {len(log_ratio_cols)} log-ratio; "
          f"{len(kept_cols)} kept after annotation join", file=sys.stderr)

    # Reshape to long form
    keep = ["Gene"] + kept_cols
    tmt = tmt[keep].copy()
    tmt = tmt.melt(id_vars=["Gene"], var_name="col", value_name="LogRatio")
    tmt["aliquot_submitter_id"] = tmt["col"].map(aliquot_by_col)
    tmt = tmt.drop(columns=["col"])
    tmt = tmt.dropna(subset=["LogRatio"])
    tmt["LogRatio"] = pd.to_numeric(tmt["LogRatio"], errors="coerce")
    tmt = tmt.dropna(subset=["LogRatio"])

    # Merge with sample_map for Run/Channel/Condition
    long = tmt.merge(sample_map[["aliquot_submitter_id", "Run", "Channel", "Condition"]],
                      on="aliquot_submitter_id", how="inner")

    # Build MSstatsTMT input frame
    out = pd.DataFrame({
        "ProteinName": long["Gene"],
        "PeptideSequence": long["Gene"],  # dummy at gene level
        "Charge": 2,
        "PSM": long["Gene"] + "_PSM1",
        "Channel": long["Channel"].astype(str),
        "Condition": long["Condition"],
        "BioReplicate": long["aliquot_submitter_id"],
        "Run": long["Run"],
        "Mixture": long["Run"],
        "TechRepMixture": 1,
        # MSstatsTMT expects linear intensity; undo log2
        "Intensity": (2.0 ** long["LogRatio"].astype(float)),
    })

    # Sanity: drop non-finite intensities (log ratio = NaN etc.)
    out = out[out["Intensity"].apply(lambda x: pd.notna(x) and x > 0)]

    out_path = work_dir / f"{cohort}_msstats_input.feather"
    feather.write_feather(pa.Table.from_pandas(out, preserve_index=False),
                          out_path, compression="zstd")

    meta = {
        "cohort": cohort,
        "pdc_study_id": pdc_id,
        "n_rows_msstats": int(len(out)),
        "n_proteins": int(out["ProteinName"].nunique()),
        "n_plexes": int(out["Run"].nunique()),
        "n_tumor_aliquots": int(sample_map[sample_map["Condition"] == "Tumor"]["aliquot_submitter_id"].nunique()),
        "n_normal_aliquots": int(sample_map[sample_map["Condition"] == "Normal"]["aliquot_submitter_id"].nunique()),
        "seconds_elapsed": round(time.time() - t0, 1),
    }
    (work_dir / f"{cohort}_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"[01_prep {cohort}] DONE: {meta['n_rows_msstats']:,} rows, "
          f"{meta['n_proteins']} proteins, "
          f"{meta['n_tumor_aliquots']}T/{meta['n_normal_aliquots']}N, "
          f"{meta['n_plexes']} plexes, {meta['seconds_elapsed']}s -> {out_path.name}",
          file=sys.stderr)
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--annotations-dir", required=True, type=Path)
    ap.add_argument("--cohort", default=None)
    args = ap.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    cohorts = [args.cohort] if args.cohort else list(CPTAC_STUDIES.keys())
    for c in cohorts:
        try:
            prep_cohort(c, args.work_dir, args.annotations_dir)
        except Exception as e:
            print(f"[01_prep {c}] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
            (args.work_dir / f"{c}_FAILED.txt").write_text(f"{type(e).__name__}: {e}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
