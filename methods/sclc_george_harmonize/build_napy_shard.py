#!/usr/bin/env python3
"""build_napy_shard — derive SCLC NAPY (A/N/P/Y) strata from the harmonized George product.

George 2015 predates the Rudin 2019 NAPY nomenclature, so no subtype label ships. This
derives SCLC-A/N/P/Y per sample from the four master transcription-factor markers
(ASCL1 / NEUROD1 / POU2F3 / YAP1) by ARGMAX of their log2(TPM+1), with a minimum-expression
FLOOR: a sample whose top marker is below the floor is labeled `SCLC_uncommitted` rather than
force-assigned (the "underpowered → honest null" discipline). Emits a subgroup-assignment
shard (tall sample × stratum, is_member tri-value) matching the resolver-product schema so
the tumor-presence subtype reader consumes it unchanged.

derivation_source = expression_argmax_napy (a Tier-3 transcriptional derivation — the marker
call, NOT a source-provided clinical label). Output:
  sclc-subgroup-assignments-v1/assignments.parquet  (+ sibling manifest.yaml in session cache).

Usage:
  python -m methods.sclc_george_harmonize.build_napy_shard --out <cache>/sclc-subgroup-assignments-v1 [--no-upload]
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

S3_BUCKET = "onc-compbio"
DEFAULT_AWS_PROFILE = "cbg"
LONG_KEY = "data-catalog/derived/sclc-george-tpm-long-v1/sclc_george_tpm_long.parquet"
OUTPUT_S3_PREFIX = "data-catalog/derived/subgroup-assignments/SCLC/george/2015"
MANIFEST_ID = "sclc-subgroup-assignments-v1"
RELEASE_PIN = "george-2015"

# marker → NAPY stratum. The four master TFs (Rudin 2019).
NAPY = {"ASCL1": "SCLC_A", "NEUROD1": "SCLC_N", "POU2F3": "SCLC_P", "YAP1": "SCLC_Y"}
# minimum log2(TPM+1) the winning marker must clear to make a committed call. ~5.67 = the
# framework's "high" cutoff (TPM≈50) is too strict for a lineage-defining TF call; use the
# "moderate" cutoff log2(11)≈3.46 (TPM≈10) — a marker below this is not convincingly ON.
MIN_MARKER_LOG2TPM = 3.46


def _log(m): print(m, file=sys.stderr, flush=True)


def _md5_hex(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)  # noqa: S324
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _s3():
    import boto3
    return boto3.Session(profile_name=DEFAULT_AWS_PROFILE).client("s3")


def build():
    """Read the NAPY marker rows from the long product, argmax-assign per sample, melt to a
    tall (sample × stratum, is_member) shard. Returns (assignments_df, summary_dict)."""
    import pyarrow.parquet as pq
    import pyarrow.fs as fs
    import pandas as pd

    # pushdown-read only the 4 marker genes (the product is ensembl-sorted; gene_symbol filter
    # still prunes via the row-group stats on the co-sorted symbol column).
    tbl = pq.read_table(f"{S3_BUCKET}/{LONG_KEY}", filesystem=fs.S3FileSystem(),
                        filters=[("gene_symbol", "in", list(NAPY))],
                        columns=["gene_symbol", "sample_id", "log2_tpm"])
    df = tbl.to_pandas()
    # a symbol may map to >1 ensembl row; collapse to one value per (gene, sample) via max.
    wide = (df.groupby(["sample_id", "gene_symbol"])["log2_tpm"].max()
              .unstack("gene_symbol"))
    markers = [m for m in NAPY if m in wide.columns]
    _log(f"[read] {wide.shape[0]} samples × {len(markers)} NAPY markers")

    top_marker = wide[markers].idxmax(axis=1)
    top_value = wide[markers].max(axis=1)
    committed = top_value >= MIN_MARKER_LOG2TPM
    # per-sample assigned stratum: the argmax marker's NAPY label, or uncommitted below the floor
    assigned = top_marker.map(NAPY).where(committed, "SCLC_uncommitted")

    strata_ids = list(NAPY.values()) + ["SCLC_uncommitted"]
    rows = []
    for sid in wide.index:
        a = assigned[sid]
        for stratum in strata_ids:
            rows.append({
                "sample_id": sid,
                "patient_id": sid,            # George RNA sample_id IS the patient grain here
                "source_native_id": sid,
                "stratum_id": stratum,
                "is_member": bool(a == stratum),
                "derivation_source": "expression_argmax_napy",
                "derivation_value": (f"{top_marker[sid]}={top_value[sid]:.2f}"
                                     if stratum == a else ""),
                "evaluated_at_release": RELEASE_PIN,
            })
    assignments = pd.DataFrame(rows)
    # de-facto stratum grouping (primary_filter_column: stratum_id)
    assignments = assignments.sort_values(["stratum_id", "sample_id"]).reset_index(drop=True)

    summary = {s: int((assigned == s).sum()) for s in strata_ids}
    return assignments, summary


def write(df, out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    parquet = out_dir / "assignments.parquet"
    df.to_parquet(parquet, index=False)
    return {"md5": _md5_hex(parquet), "size_bytes": parquet.stat().st_size,
            "n_rows": len(df), "path": str(parquet)}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Derive SCLC NAPY strata → subgroup-assignment shard.")
    p.add_argument("--out", required=True, type=Path,
                   help="output dir (session cache: .../subgroup-assignments/sclc-subgroup-assignments-v1)")
    p.add_argument("--no-upload", action="store_true")
    args = p.parse_args(argv)

    df, summary = build()
    meta = write(df, args.out)
    _log(f"[write] {meta['path']}: {meta['n_rows']} rows / md5={meta['md5']}")
    _log("[napy] subtype distribution (committed argmax; floor log2TPM>=%.2f):" % MIN_MARKER_LOG2TPM)
    for s, n in summary.items():
        _log(f"    {s}: {n}")
    # correctness: SCLC-A must be the dominant stratum (published ~70%)
    if summary.get("SCLC_A", 0) < max((v for k, v in summary.items() if k != "SCLC_A"), default=0):
        _log("  WARNING: SCLC_A is not the dominant stratum — unexpected for this cohort")
    else:
        _log("  check SCLC_A dominant: OK")

    if not args.no_upload:
        key = f"{OUTPUT_S3_PREFIX}/assignments.parquet"
        _s3().upload_file(meta["path"], S3_BUCKET, key, ExtraArgs={"Metadata": {"md5": meta["md5"]}})
        _log(f"[upload] s3://{S3_BUCKET}/{key}")
    else:
        _log("[upload] skipped (--no-upload)")
    print(f"md5={meta['md5']} size_bytes={meta['size_bytes']} n_rows={meta['n_rows']} "
          f"dist={summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
