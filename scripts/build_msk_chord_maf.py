"""build_msk_chord_maf — materialize msk-chord-per-sample-maf-v1 (scope-coherence Phase 2).

MSK-CHORD ships mutations as JSONL (mutations.jsonl.gz) with `entrezGeneId` (NOT a Hugo symbol) and a
`sampleId`. This builds the per-sample MAF product that mirrors genie-registry-per-sample-maf-v1:
  - entrezGeneId → HGNC symbol via hgnc_entrez_crosswalk
  - sample → indication via data_clinical_sample.txt CANCER_TYPE (reverse of MSK_CANCER_TYPE)
  - non-synonymous variants only (same 8-class filter as the GENIE MAF builder)
Emits per-indication rows: indication, gene_symbol, effect, sample_id, protein_change,
source_native_id, patient_id. Writes one pan-indication parquet (sort key gene_symbol) + optional upload.

Usage:
    AWS_PROFILE=cbg python -m scripts.build_msk_chord_maf --out /tmp/msk_maf.parquet [--upload]
    DRY_RUN=1 ... --upload    # prints S3 key + md5 without uploading
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # methods/ importable

from methods.msk_panel_coverage.read import MSK_CANCER_TYPE  # framework indication → MSK CANCER_TYPE

S3_BUCKET = "onc-compbio"
MSK_PREFIX = "data-catalog/sources/cbioportal/msk_chord_2024"
MUTATIONS_KEY = f"{MSK_PREFIX}/mutations.jsonl.gz"
CLINICAL_KEY = f"{MSK_PREFIX}/data_clinical_sample.txt"
S3_KEY = "data-catalog/derived/msk-chord-per-sample-maf-v1/per_sample_maf.parquet"

# Same non-synonymous vocabulary the GENIE MAF builder retains (MSK mutationType is title-case).
_NON_SYNONYMOUS = {
    "Missense_Mutation", "Nonsense_Mutation", "Frame_Shift_Ins", "Frame_Shift_Del",
    "In_Frame_Ins", "In_Frame_Del", "Splice_Site", "Nonstop_Mutation", "Translation_Start_Site",
}


def _s3():
    import boto3
    return boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "cbg")).client("s3")


def _sample_to_indication() -> dict:
    """{SAMPLE_ID: framework indication} from clinical CANCER_TYPE (reverse of MSK_CANCER_TYPE). A sample
    whose CANCER_TYPE maps to several framework codes (e.g. COADREAD) uses the canonical code."""
    import pandas as pd
    body = _s3().get_object(Bucket=S3_BUCKET, Key=CLINICAL_KEY)["Body"].read()
    df = pd.read_csv(io.BytesIO(body), sep="\t", comment="#", dtype=str)
    # canonical framework code per CANCER_TYPE string (first key that maps to it)
    ct_to_ind = {}
    for ind, ct in MSK_CANCER_TYPE.items():
        ct_to_ind.setdefault(ct, ind)   # COADREAD before COAD/READ (dict insertion order), NSCLC before LUAD…
    out = {}
    for sid, ct in zip(df["SAMPLE_ID"], df["CANCER_TYPE"]):
        ind = ct_to_ind.get(ct)
        if sid and ind:
            out[str(sid)] = ind
    return out


def build() -> "pandas.DataFrame":
    import pandas as pd
    from methods.hgnc_entrez_crosswalk.read import load_entrez_to_symbol
    entrez_to_symbol = load_entrez_to_symbol()
    sample_ind = _sample_to_indication()
    raw = _s3().get_object(Bucket=S3_BUCKET, Key=MUTATIONS_KEY)["Body"].read()
    rows = []
    n_seen = n_kept = 0
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as fh:
        for line in fh:
            n_seen += 1
            r = json.loads(line)
            if r.get("mutationType") not in _NON_SYNONYMOUS:
                continue
            sid = r.get("sampleId")
            ind = sample_ind.get(sid)
            if ind is None:
                continue                       # sample not in a framework indication MSK-CHORD carries
            try:
                sym = entrez_to_symbol.get(int(r.get("entrezGeneId")))
            except (TypeError, ValueError):
                sym = None
            if not sym:
                continue                       # unmapped entrez id (dropped, logged in the count)
            n_kept += 1
            rows.append({"indication": ind, "gene_symbol": sym,
                         "effect": r.get("mutationType"), "sample_id": sid,
                         "protein_change": r.get("proteinChange"),
                         "source_native_id": sid, "patient_id": r.get("patientId")})
    print(f"  scanned {n_seen} variants, kept {n_kept} non-synonymous in-indication", file=sys.stderr)
    df = pd.DataFrame(rows, columns=["indication", "gene_symbol", "effect", "sample_id",
                                     "protein_change", "source_native_id", "patient_id"])
    return df.sort_values(["indication", "gene_symbol"]).reset_index(drop=True)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Materialize msk-chord-per-sample-maf-v1.")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--upload", action="store_true")
    args = ap.parse_args(argv)
    df = build()
    df.to_parquet(args.out, index=False)
    md5 = hashlib.md5(args.out.read_bytes()).hexdigest()
    by_ind = df.groupby("indication")["sample_id"].nunique().to_dict()
    print(f"wrote {len(df)} rows -> {args.out}  (md5 {md5}, {args.out.stat().st_size} bytes)")
    print(f"  samples by indication: {by_ind}")
    if args.upload:
        if os.environ.get("DRY_RUN"):
            print(f"[DRY_RUN] would upload {args.out} -> s3://{S3_BUCKET}/{S3_KEY}  (md5 {md5})")
            return 0
        _s3().upload_file(str(args.out), S3_BUCKET, S3_KEY, ExtraArgs={"Metadata": {"md5": md5}})
        print(f"uploaded -> s3://{S3_BUCKET}/{S3_KEY}  (md5 {md5}, size {args.out.stat().st_size}, rows {len(df)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
