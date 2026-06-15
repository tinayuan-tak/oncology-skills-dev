"""query_evidence.py — RETRIEVAL-ONLY lookup of a core-artifact evidence.json.

This script reads a pre-computed evidence artifact from
s3://onc-compbio/core-artifacts/{indication}/{gene}/{dimension}/evidence.json,
validates it, checks staleness, and returns it. It deliberately contains NO
analysis code — no pandas, no scipy, no expression loading. If you find
yourself wanting to add compute here, it belongs in a batch/ job instead.

The dimension → batch-job map below is how a missing artifact reports which
batch job would produce it (without triggering that job).

Usage:
  python query_evidence.py --gene SCD1 --indication crc --dimension expression
  python query_evidence.py --gene SCD1 --indication crc --all-dimensions
  python query_evidence.py --gene SCD1 --indication crc --dimension expression --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

try:
    from jsonschema import Draft202012Validator
    _HAVE_JSONSCHEMA = True
except ImportError:
    _HAVE_JSONSCHEMA = False

BUCKET = "onc-compbio"
ARTIFACT_PREFIX = "core-artifacts"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "core-artifacts-schema" / "evidence.schema.json"

# Which batch job produces each dimension (for "missing artifact" guidance).
DIMENSION_BATCH_JOB = {
    "expression": "batch/run_global_dge.py",
    "dependency": "batch/run_global_dependency.py",      # planned
    "genomic-context": "batch/run_genomic_context.py",   # planned
    "patient-stratification": "batch/run_patient_strat.py",  # planned
    "clinical-outcomes": "batch/run_clinical_outcomes.py",   # planned
    "safety": "batch/run_safety.py",                     # planned
    "target-biology": "batch/run_target_biology.py",     # planned
    "literature": "batch/run_literature.py",             # planned
}
DIMENSIONS = list(DIMENSION_BATCH_JOB.keys())


def s3_client(profile: str):
    return boto3.Session(profile_name=profile).client("s3")


def artifact_key(indication: str, gene: str, dimension: str) -> str:
    return f"{ARTIFACT_PREFIX}/{indication}/{gene}/{dimension}/evidence.json"


def load_schema() -> dict | None:
    if not SCHEMA_PATH.exists():
        return None
    return json.loads(SCHEMA_PATH.read_text())


def fetch_artifact(client, indication: str, gene: str, dimension: str) -> dict | None:
    key = artifact_key(indication, gene, dimension)
    try:
        obj = client.get_object(Bucket=BUCKET, Key=key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404", "NoSuchBucket"):
            return None
        raise
    return json.loads(obj["Body"].read())


def validate(artifact: dict, schema: dict | None) -> list[str]:
    if schema is None or not _HAVE_JSONSCHEMA:
        return []
    return [
        f"{'/'.join(str(x) for x in e.absolute_path) or '(root)'}: {e.message}"
        for e in Draft202012Validator(schema).iter_errors(artifact)
    ]


def report_one(client, schema, indication, gene, dimension, as_json: bool) -> dict:
    art = fetch_artifact(client, indication, gene, dimension)
    if art is None:
        result = {
            "gene": gene, "indication": indication, "dimension": dimension,
            "status": "MISSING",
            "produced_by": DIMENSION_BATCH_JOB.get(dimension, "(unknown batch job)"),
            "note": "Artifact does not exist. This skill does not compute it — "
                    "run the batch job (offline/scheduled) to produce it.",
        }
        if not as_json:
            print(f"[MISSING] {gene}/{indication}/{dimension} — no artifact.")
            print(f"          Produced by: {result['produced_by']} (run offline; not from this skill).")
        return result

    errs = validate(art, schema)
    stale = (art.get("staleness") or {}).get("is_stale", False)
    status = "INVALID" if errs else ("STALE" if stale else "OK")

    if not as_json:
        print(f"[{status}] {gene}/{indication}/{dimension}")
        print(f"  computed_date: {art.get('computed_date')}")
        print(f"  confidence:    {art.get('confidence')}   label: {art.get('label')}")
        prov = art.get("provenance", {})
        print(f"  source:        {prov.get('source')}  release: {prov.get('release')}")
        print(f"  catalog_refs:  {', '.join(prov.get('catalog_refs', []))}")
        print(f"  summary:       {art.get('summary')}")
        if stale:
            print("  ** STALE — stored result returned; scientist decides. Not auto-rerun. **")
        if errs:
            print(f"  ** SCHEMA ERRORS ({len(errs)}): {errs[:3]} **")

    return {"status": status, "errors": errs, "artifact": art}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--gene", required=True)
    p.add_argument("--indication", required=True)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dimension", choices=DIMENSIONS)
    g.add_argument("--all-dimensions", action="store_true")
    p.add_argument("--profile", default="cbg")
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = p.parse_args()

    client = s3_client(args.profile)
    schema = load_schema()
    if schema is None and not args.json:
        print("WARNING: evidence schema not found; skipping validation.", file=sys.stderr)

    dims = DIMENSIONS if args.all_dimensions else [args.dimension]
    results = {d: report_one(client, schema, args.indication, args.gene, d, args.json) for d in dims}

    if args.json:
        json.dump(results, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")

    # Exit non-zero only on schema-invalid artifacts (missing/stale are normal states).
    return 1 if any(r.get("status") == "INVALID" for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
