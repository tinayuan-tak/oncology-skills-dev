#!/usr/bin/env python3
"""Stage 00 — pull per-aliquot tumor/normal annotations from PDC GraphQL.

The tmt10.tsv files ship with aliquot_submitter_id columns (short-hex + _D#
suffix) but no tumor-vs-normal label. That label lives on PDC's biospecimen
node, queried via `biospecimenPerStudy(pdc_study_id: "PDC######")`. This
stage emits one TSV per cohort keyed by aliquot_submitter_id -> sample_type.

Aliquots labeled "Internal Reference - Pooled Sample" are the plex-reference
pools and are excluded from the design matrix downstream (they map to the
POOL channel in sample.txt).

Idempotent: writes only if missing OR --force is passed.

Reads: PDC GraphQL (open, no auth); 10 study IDs from CPTAC_STUDIES.
Writes: <annotations_dir>/<cohort>_aliquot_annotations.tsv (cohort, aliquot_submitter_id, sample_type, case_submitter_id).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PDC_GRAPHQL = "https://pdc.cancer.gov/graphql"

CPTAC_STUDIES = {
    "BRCA": "PDC000120",
    "COAD": "PDC000116",
    "OV": "PDC000110",
    "CCRCC": "PDC000127",
    "GBM": "PDC000204",
    "HNSCC": "PDC000221",
    "LUAD": "PDC000153",
    "LSCC": "PDC000234",
    "UCEC": "PDC000125",
    "PDAC": "PDC000270",
}


def gql(query: str, retries: int = 3, backoff_s: float = 2.0) -> dict:
    """POST a GraphQL query to PDC with retry-with-backoff on transient errors."""
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                PDC_GRAPHQL,
                data=json.dumps({"query": query}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            time.sleep(backoff_s * (2**attempt))
    raise RuntimeError(f"PDC GraphQL failed after {retries} attempts: {last_err}")


def query_study(cohort: str, pdc_id: str) -> list[dict]:
    q = f'''
    {{
      biospecimenPerStudy(pdc_study_id: "{pdc_id}", acceptDUA: true) {{
        aliquot_submitter_id
        sample_type
        case_submitter_id
      }}
    }}
    '''
    r = gql(q)
    if "errors" in r:
        raise RuntimeError(f"PDC error for {cohort} ({pdc_id}): {r['errors']}")
    rows = r.get("data", {}).get("biospecimenPerStudy") or []
    return rows


def write_tsv(cohort: str, rows: list[dict], out_path: Path) -> tuple[int, int]:
    """Write annotations; return (n_tumor, n_normal) after filtering pools."""
    tumor_types = {"Primary Tumor", "Metastatic", "Recurrent Tumor"}
    normal_types = {"Solid Tissue Normal", "Blood Derived Normal"}
    n_tumor = n_normal = 0
    with out_path.open("w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["cohort", "aliquot_submitter_id", "sample_type", "case_submitter_id"])
        for r in rows:
            aid = r.get("aliquot_submitter_id") or ""
            st = r.get("sample_type") or ""
            if not aid or "Pooled Sample" in aid or "Internal Reference" in aid:
                continue
            w.writerow([cohort, aid, st, r.get("case_submitter_id") or ""])
            if st in tumor_types:
                n_tumor += 1
            elif st in normal_types:
                n_normal += 1
    return n_tumor, n_normal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--annotations-dir", required=True, type=Path)
    ap.add_argument("--cohort", default=None, help="Optional single-cohort filter (default: all 10).")
    ap.add_argument("--force", action="store_true", help="Re-query even if TSV already exists.")
    args = ap.parse_args()

    args.annotations_dir.mkdir(parents=True, exist_ok=True)

    cohorts = [args.cohort] if args.cohort else list(CPTAC_STUDIES.keys())
    print(f"[00_pull_annotations] {len(cohorts)} cohorts", file=sys.stderr)

    for cohort in cohorts:
        pdc_id = CPTAC_STUDIES.get(cohort)
        if not pdc_id:
            print(f"[00_pull_annotations] SKIP unknown cohort: {cohort}", file=sys.stderr)
            continue
        out_path = args.annotations_dir / f"{cohort}_aliquot_annotations.tsv"
        if out_path.exists() and not args.force:
            print(f"[00_pull_annotations] {cohort}: CACHED ({out_path.name})", file=sys.stderr)
            continue
        t0 = time.time()
        rows = query_study(cohort, pdc_id)
        n_tumor, n_normal = write_tsv(cohort, rows, out_path)
        print(
            f"[00_pull_annotations] {cohort} ({pdc_id}): "
            f"{n_tumor} tumor + {n_normal} normal aliquots "
            f"({time.time() - t0:.1f}s) -> {out_path.name}",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
