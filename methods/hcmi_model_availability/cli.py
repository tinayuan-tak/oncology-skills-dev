"""hcmi_model_availability.cli — materialize the per-indication HCMI model-availability product.

Scientific-gap #1 (2026-08-14), lighter-v1: the TRANSLATIONAL-BRIDGE axis the framework lacked —
"for indication Y, how many patient-derived (HCMI organoid / next-gen cancer) models exist to
preclinically validate a nominated target?" This v1 is model-AVAILABILITY-by-indication
(target-independent cohort context); the genotype-MATCHED v2 (does a model carry target X's alteration?)
joins the HCMI WXS MAFs on top of this crosswalk and is the follow-up.

SOURCE (pre-existing ingestion — ZERO new pulls): HCMI-CMDC DR45 (hcmi-cmdc-dr45-0), the 805 per-case
ClinicalData JSONs under s3://onc-compbio/data-catalog/sources/hcmi/cmdc-dr45-0/HCMI-CMDC/.

METHOD (aggregate_model_availability): walk the 805 case JSONs, read each
ClinicalData."GDC Clinical Data Entities"[0].{primary_site, disease_type} (GDC vocabulary) + the
SubjectData.submitter_id model id, apply a (primary_site, disease_type) -> framework-indication
crosswalk for the TSS-mapped core set (COADREAD / PAAD / NSCLC / GC — the same 4 the clonality product
covers), and count distinct models per indication. model_availability_class thresholds:
deep_model_coverage (>=50) / moderate_model_coverage (15-49) / sparse_model_coverage (<15).

VALIDATION (2026-08-14): 376 / 805 models map to the 4 core indications — COADREAD 209 (deep),
PAAD 115 (deep), NSCLC 27 (moderate), GC 25 (moderate) — consistent with HCMI's documented
GI/colorectal-heavy composition.

ROLE: VERDICT-INERT translational facet on first wiring; drives NO resolver rung.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
from collections import Counter, defaultdict
from typing import Optional

_BUCKET = "onc-compbio"
_HCMI_PREFIX = "data-catalog/sources/hcmi/cmdc-dr45-0/HCMI-CMDC/"

# (primary_site, disease_type) -> framework indication crosswalk (TSS-mapped core set).
# Keyed on lowercased substring matches against the GDC clinical vocabulary; deliberately conservative
# (adenocarcinoma histologies only) so a mis-histology model is left unmapped rather than mis-assigned.
_MODEL_AVAILABILITY_CLASS_THRESHOLDS = {"deep": 50, "moderate": 15}  # else sparse


def crosswalk_indication(primary_site: "Optional[str]", disease_type: "Optional[str]") -> "Optional[str]":
    """(primary_site, disease_type) -> framework indication code, or None if unmapped."""
    ps = (primary_site or "").lower()
    dt = (disease_type or "").lower()
    if any(x in ps for x in ("colon", "rectum", "rectosigmoid")) and "adenom" in dt:
        return "COADREAD"
    if "pancreas" in ps and ("ductal" in dt or "adenom" in dt):
        return "PAAD"
    if ("bronchus" in ps or "lung" in ps) and any(x in dt for x in ("adenom", "squamous", "epithelial")):
        return "NSCLC"
    if "stomach" in ps and "adenom" in dt:
        return "GC"
    return None


def _availability_class(n: int) -> str:
    if n >= _MODEL_AVAILABILITY_CLASS_THRESHOLDS["deep"]:
        return "deep_model_coverage"
    if n >= _MODEL_AVAILABILITY_CLASS_THRESHOLDS["moderate"]:
        return "moderate_model_coverage"
    return "sparse_model_coverage"


def _list_case_jsons(s3) -> list:
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=_BUCKET, Prefix=_HCMI_PREFIX):
        for obj in page.get("Contents", []):
            k = obj["Key"]
            base = k.rsplit("/", 1)[-1]
            if base.startswith("HCM-") and base.endswith(".json"):
                keys.append(k)
    return keys


def _read_one(key: str):
    """Return (model_id, primary_site, disease_type) for one case JSON, or None on any read/parse error."""
    import boto3
    try:
        d = json.loads(boto3.client("s3").get_object(Bucket=_BUCKET, Key=key)["Body"].read())["ClinicalData"]
        mid = (d.get("SubjectData") or {}).get("submitter_id")
        ent = (d.get("GDC Clinical Data Entities") or [{}])[0]
        return (mid, ent.get("primary_site"), ent.get("disease_type"))
    except Exception:  # absence-discipline: exempt -- build-time batch; a single unreadable case is skipped (COUNTED + WARNed by aggregate_model_availability so throttling can't silently undercount)
        return None


def aggregate_model_availability(max_workers: int = 24) -> list:
    """Walk the HCMI case JSONs and aggregate patient-derived model counts per framework indication."""
    import boto3
    os.environ.setdefault("AWS_PROFILE", "cbg")
    s3 = boto3.client("s3")
    keys = _list_case_jsons(s3)
    rows = []
    n_unreadable = 0                       # _read_one returned None = a read/parse FAILURE (not a genuine no-model-id case)
    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for r in ex.map(_read_one, keys):
            if r is None:
                n_unreadable += 1
                continue
            if r[0]:
                rows.append(r)
    if n_unreadable:
        import sys as _sys
        print(f"WARNING: {n_unreadable}/{len(keys)} HCMI case JSONs were unreadable/unparseable and "
              f"were SKIPPED — if this is S3 throttling (not genuine gaps) the per-indication model "
              f"counts UNDERCOUNT. Re-run to confirm stability.", file=_sys.stderr)
    per = defaultdict(lambda: {"models": set(), "sites": Counter()})
    for mid, ps, dt in rows:
        ind = crosswalk_indication(ps, dt)
        if ind:
            per[ind]["models"].add(mid)
            per[ind]["sites"][f"{ps}|{dt}"] += 1
    out = []
    for ind in sorted(per):
        n = len(per[ind]["models"])
        out.append({
            "indication": ind,
            "n_patient_derived_models": n,
            "model_availability_class": _availability_class(n),
            "source": "HCMI-CMDC-DR45",
            "primary_site_breakdown": "; ".join(f"{k}={c}" for k, c in per[ind]["sites"].most_common()),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Materialize the per-indication HCMI model-availability product.")
    ap.add_argument("--out", required=True, help="output parquet path")
    ap.add_argument("--max-workers", type=int, default=24)
    args = ap.parse_args()
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = aggregate_model_availability(max_workers=args.max_workers)
    pq.write_table(pa.Table.from_pylist(rows), args.out)
    total = sum(r["n_patient_derived_models"] for r in rows)
    print(f"wrote {len(rows)} indications ({total} mapped models) -> {args.out}")
    for r in rows:
        print(f"  {r['indication']:9} n={r['n_patient_derived_models']:4}  {r['model_availability_class']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
