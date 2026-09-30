"""query_evidence.py — RETRIEVAL-ONLY lookup of a core-artifact evidence.json.

This script reads a pre-computed evidence artifact from
s3://onc-compbio/core-artifacts/{ONCOTREE_CODE}/{subtype}/{gene}/{dimension}/evidence.json,
validates it, checks staleness, and returns it. It deliberately contains NO
analysis code — no pandas, no scipy, no expression loading. If you find
yourself wanting to add compute here, it belongs in a batch/ job instead.

The dimension → batch-job map below is how a missing artifact reports which
batch job would produce it (without triggering that job).

Path schema:
  core-artifacts/{ONCOTREE_CODE}/{subtype}/{gene}/{dimension}/evidence.json
  - indication is a literal AACR OncoTree code (uppercase): COADREAD, LUAD,
    LUSC, NSCLC, PAAD, STAD, etc. See https://oncotree.mskcc.org/.
  - subtype defaults to 'all' for unstratified analyses; molecular subtypes
    (CMS1, MSS-RASmut, etc.) are Takeda-internal vocabulary, not OncoTree.
  - examples: COADREAD/all/SCD1/expression-rna/, COADREAD/CMS4/SCD1/expression-rna/

Usage:
  python query_evidence.py --gene SCD1 --indication COADREAD --dimension expression-rna
  python query_evidence.py --gene SCD1 --indication COADREAD --subtype CMS4 --dimension expression-rna
  python query_evidence.py --gene SCD1 --indication COADREAD --all-dimensions
  python query_evidence.py --gene SCD1 --indication COADREAD --dimension expression-rna --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from botocore.exceptions import ClientError

# Hardened client (adaptive retry + ProfileNotFound fallback to the ambient credential
# chain) — the bare boto3.Session(profile_name=...) it replaces raised in any
# environment without the `cbg` profile and had no throttling protection.
from onc_methods.target_id_sidecar import s3_client

try:
    from jsonschema import Draft202012Validator

    _HAVE_JSONSCHEMA = True
except ImportError:
    _HAVE_JSONSCHEMA = False

BUCKET = "onc-compbio"
ARTIFACT_PREFIX = "core-artifacts"
SCHEMA_PATH = Path(__file__).resolve().parents[3] / "contracts" / "schemas" / "evidence.schema.json"

# Which batch job produces each dimension (for "missing artifact" guidance).
# Eight dimensions (revised 2026-06-15). The root batch/ dir (v1-era) was retired
# 2026-09-29 (#2138); expression-rna is now produced by methods/onc_methods/dge_deseq2
# (the carved-out, catalog-driven successor to batch/expression_rna_{indication}/).
# The remaining "planned" rows never had a real path — batch/ never grew them —
# so they're left as named-but-nonexistent placeholders rather than invented paths.
DIMENSION_BATCH_JOB = {
    "expression-rna": "methods/onc_methods/dge_deseq2",
    "expression-protein": "batch/expression_protein_{indication}/run_pipeline.R",  # planned (CPTAC)
    "dependency": "batch/dependency/run_pipeline.py",  # planned (DepMap)
    "mutation-profile": "batch/mutation_profile_{indication}/run_pipeline.py",  # planned (GDC somatic)
    "survival": "batch/survival_{indication}/run_pipeline.py",  # planned (GDC clinical)
    "safety": "batch/safety/run_pipeline.py",  # planned (HPA + gnomAD)
    "target-biology": "batch/target_biology/run_pipeline.py",  # planned (UniProt + HPA + SurfaceomeDB)
    "literature": "batch/literature/run_pipeline.py",  # exists (Ming-Ju), v2 schema port pending
}
DIMENSIONS = list(DIMENSION_BATCH_JOB.keys())


def artifact_key(indication: str, subtype: str, gene: str, dimension: str) -> str:
    return f"{ARTIFACT_PREFIX}/{indication}/{subtype}/{gene}/{dimension}/evidence.json"


def load_schema() -> dict | None:
    if not SCHEMA_PATH.exists():
        return None
    return json.loads(SCHEMA_PATH.read_text())


def fetch_artifact(client, indication: str, subtype: str, gene: str, dimension: str) -> dict | None:
    key = artifact_key(indication, subtype, gene, dimension)
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


def report_one(client, schema, indication, subtype, gene, dimension, as_json: bool) -> dict:
    art = fetch_artifact(client, indication, subtype, gene, dimension)
    label = f"{gene}/{indication}/{subtype}/{dimension}"
    if art is None:
        produced_by = DIMENSION_BATCH_JOB.get(dimension, "(unknown batch job)")
        produced_by = produced_by.format(indication=indication)
        result = {
            "gene": gene,
            "indication": indication,
            "subtype": subtype,
            "dimension": dimension,
            "status": "MISSING",
            "produced_by": produced_by,
            "note": "Artifact does not exist. This skill does not compute it — "
            "run the batch job (offline/scheduled) to produce it.",
        }
        if not as_json:
            print(f"[MISSING] {label} — no artifact.")
            print(f"          Produced by: {produced_by} (run offline; not from this skill).")
        return result

    errs = validate(art, schema)
    stale = (art.get("staleness") or {}).get("is_stale", False)
    status = "INVALID" if errs else ("STALE" if stale else "OK")

    if not as_json:
        print(f"[{status}] {label}")
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
    p.add_argument(
        "--subtype",
        default="all",
        help="Subtype slug (default 'all' for unstratified). Examples: all, CMS1, CMS4, MSS-RASmut, MSI-H.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--dimension", choices=DIMENSIONS)
    g.add_argument("--all-dimensions", action="store_true")
    p.add_argument(
        "--profile",
        default=None,
        help="AWS profile (default: cbg when configured, else the ambient credential chain).",
    )
    p.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = p.parse_args()

    client = s3_client(args.profile)
    schema = load_schema()
    if schema is None and not args.json:
        print("WARNING: evidence schema not found; skipping validation.", file=sys.stderr)

    dims = DIMENSIONS if args.all_dimensions else [args.dimension]
    results = {d: report_one(client, schema, args.indication, args.subtype, args.gene, d, args.json) for d in dims}

    if args.json:
        json.dump(results, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")

    # Exit non-zero only on schema-invalid artifacts (missing/stale are normal states).
    return 1 if any(r.get("status") == "INVALID" for r in results.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
