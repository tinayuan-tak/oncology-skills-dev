"""write_evidence.py — emit a per-gene evidence.json from the DGE Parquet.

Reads one row of the DGE Parquet (per-gene predicate-pushdown), assembles an
evidence.json conforming to core-artifacts-schema/evidence.schema.json,
schema-validates it BEFORE upload, and writes it to:

  s3://onc-compbio/core-artifacts/{ONCOTREE_CODE}/{subtype}/{gene}/{dimension}/evidence.json

The companion provenance.yaml from 05_provenance.R is also copied alongside.

This is the bridge from DGE batch output (Parquet, one row per gene) to the
retrieval contract (evidence.json, one file per gene/indication/subtype/dim).
The retrieval skill skills/query-target-evidence/ reads what this writes.

Usage:
  pixi run python batch/expression_rna_COADREAD/scripts/write_evidence.py \
      --gene SCD1 \
      --indication COADREAD \
      --subtype all \
      --parquet-uri s3://onc-compbio/data-catalog/derived/COADREAD-dge/{sha}/tumor_vs_adjacent.parquet \
      --provenance-yaml /tmp/expression_rna_COADREAD/05_provenance.yaml \
      --derived-manifest-id COADREAD-dge-{sha-prefix} \
      --git-sha {sha}
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path
from urllib.parse import urlparse

import boto3
import pyarrow.parquet as pq
import yaml
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "core-artifacts-schema" / "evidence.schema.json"

BUCKET = "onc-compbio"
ARTIFACT_PREFIX = "core-artifacts"


def parse_s3_uri(uri: str) -> tuple[str, str]:
    p = urlparse(uri)
    if p.scheme != "s3" or not p.netloc:
        raise ValueError(f"Not an S3 URI: {uri}")
    return p.netloc, p.path.lstrip("/")


def fetch_gene_row(parquet_uri: str, gene: str, profile: str) -> dict:
    """Read one row out of the (gene_symbol-sorted) Parquet via predicate pushdown.

    The Parquet is written sorted by gene_symbol with row-group-size=1024
    (see 04_write_parquet.R), so per-gene reads scan only the relevant
    row group rather than the full file.
    """
    fs_kwargs = {"profile": profile} if parquet_uri.startswith("s3://") else {}
    if parquet_uri.startswith("s3://"):
        import pyarrow.fs as pafs
        bucket, key = parse_s3_uri(parquet_uri)
        # boto3-resolved creds → arrow-filesystem; respects AWS_PROFILE.
        fs = pafs.S3FileSystem(**fs_kwargs)
        path = f"{bucket}/{key}"
    else:
        fs = None
        path = parquet_uri

    table = pq.read_table(
        path,
        filesystem=fs,
        filters=[("gene_symbol", "=", gene)],
    )
    if table.num_rows == 0:
        raise SystemExit(f"Gene {gene!r} not found in {parquet_uri}")
    if table.num_rows > 1:
        raise SystemExit(
            f"Multiple rows for {gene!r} ({table.num_rows}) — "
            "DGE Parquet should be one row per gene_symbol."
        )
    row = {col: table[col][0].as_py() for col in table.column_names}
    return row


def _clean_float(x):
    """JSON can't carry NaN/Inf — convert to None.

    DESeq2 uses NA for genes that fail independent filtering (padj=NA) or
    when baseMean=0 (lfc=NA). Schema needs these as JSON null, not 'NaN'.
    """
    if x is None:
        return None
    try:
        if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
            return None
    except TypeError:
        pass
    return x


def build_evidence(
    *,
    gene: str,
    indication: str,
    subtype: str,
    dimension: str,
    row: dict,
    provenance_yaml: dict,
    derived_manifest_id: str,
    git_sha: str,
    label: str,
) -> dict:
    n_tumor = int(row.get("n_tumor") or provenance_yaml.get("cohort", {}).get("n_tumor") or 0)
    n_normal = int(row.get("n_normal") or provenance_yaml.get("cohort", {}).get("n_normal") or 0)

    log2fc = _clean_float(row.get("log2FoldChange"))
    padj = _clean_float(row.get("padj"))
    pvalue = _clean_float(row.get("pvalue"))
    base_mean = _clean_float(row.get("baseMean"))
    lfc_se = _clean_float(row.get("lfcSE"))
    is_actionable = bool(row.get("is_actionable") or False)

    # Direction language for the human summary.
    if log2fc is None or padj is None:
        direction = "no testable signal"
    elif padj >= 0.05:
        direction = "no significant differential expression"
    elif log2fc >= 1:
        direction = f"strongly upregulated in tumor (log2FC = {log2fc:.2f}, padj = {padj:.2e})"
    elif log2fc > 0:
        direction = f"modestly upregulated in tumor (log2FC = {log2fc:.2f}, padj = {padj:.2e})"
    elif log2fc <= -1:
        direction = f"strongly downregulated in tumor (log2FC = {log2fc:.2f}, padj = {padj:.2e})"
    else:
        direction = f"modestly downregulated in tumor (log2FC = {log2fc:.2f}, padj = {padj:.2e})"

    summary = (
        f"{gene} in {indication} ({subtype}) shows {direction}, "
        f"based on TCGA tumor (n={n_tumor}) vs adjacent-normal (n={n_normal}) "
        f"DESeq2 + apeglm-shrunk Wald test."
    )

    # Confidence directional bucketing — we deliberately don't compute a numeric score
    # (dropped per runbook). HIGH = clear actionable up/down with adequate cohort;
    # MODERATE = significant but not actionable-magnitude or marginal cohort;
    # EMERGING = below the FDR bar but suggestive directionality.
    if is_actionable and n_tumor >= 30 and n_normal >= 20:
        confidence = "HIGH"
    elif (padj is not None and padj < 0.05) and n_tumor >= 10:
        confidence = "MODERATE"
    elif (pvalue is not None and pvalue < 0.05):
        confidence = "EMERGING"
    else:
        confidence = "NOT_ASSESSED"

    catalog_refs = [
        provenance_yaml.get("source", {}).get("manifest_id"),
        derived_manifest_id,
    ]
    catalog_refs = [r for r in catalog_refs if r]

    artifact = {
        "gene": gene,
        "indication": indication,
        "subtype": subtype,
        "dimension": dimension,
        "computed_date": provenance_yaml.get("computed_date") or dt.date.today().isoformat(),
        "provenance": {
            "source": (
                f"TCGA {'/'.join(provenance_yaml.get('source', {}).get('manifest_id', '').split('-')[:2]).upper()} "
                f"via {provenance_yaml.get('source', {}).get('manifest_id', 'tcga-gdc-dr45-0')}"
            ),
            "release": str(provenance_yaml.get("source", {}).get("release") or "DR45.0"),
            "method": provenance_yaml.get("method", {}).get(
                "name", "DESeq2 + lfcShrink(apeglm), Wald test, BH-FDR"
            ),
            "git_commit": git_sha,
            "parameter_hash": provenance_yaml.get("parameter_hash", ""),
            "catalog_refs": catalog_refs,
        },
        "result": {
            "tumor_vs_adjacent_log2fc": log2fc,
            "lfcSE": lfc_se,
            "pvalue": pvalue,
            "padj": padj,
            "baseMean": base_mean,
            "n_tumor": n_tumor,
            "n_normal": n_normal,
            "is_actionable": is_actionable,
        },
        "summary": summary,
        "confidence": confidence,
        "label": label,
    }
    return artifact


def validate_or_die(artifact: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text())
    errors = list(Draft202012Validator(schema).iter_errors(artifact))
    if errors:
        msgs = [
            f"{'/'.join(str(x) for x in e.absolute_path) or '(root)'}: {e.message}"
            for e in errors
        ]
        sys.exit("Schema validation failed:\n  - " + "\n  - ".join(msgs))


def upload_artifact(
    artifact: dict,
    indication: str,
    subtype: str,
    gene: str,
    dimension: str,
    profile: str,
    provenance_yaml_path: Path | None,
    dry_run: bool,
) -> str:
    key_dir = f"{ARTIFACT_PREFIX}/{indication}/{subtype}/{gene}/{dimension}"
    evidence_key = f"{key_dir}/evidence.json"
    body = json.dumps(artifact, indent=2, sort_keys=False).encode("utf-8")

    if dry_run:
        print(f"[dry-run] would PUT {len(body)} bytes to s3://{BUCKET}/{evidence_key}")
        if provenance_yaml_path:
            print(f"[dry-run] would PUT {provenance_yaml_path} → s3://{BUCKET}/{key_dir}/provenance.yaml")
        return evidence_key

    s3 = boto3.Session(profile_name=profile).client("s3")
    s3.put_object(
        Bucket=BUCKET, Key=evidence_key, Body=body,
        ContentType="application/json",
    )
    print(f"[ok] PUT s3://{BUCKET}/{evidence_key}  ({len(body)} bytes)")

    if provenance_yaml_path:
        prov_key = f"{key_dir}/provenance.yaml"
        s3.put_object(
            Bucket=BUCKET, Key=prov_key,
            Body=provenance_yaml_path.read_bytes(),
            ContentType="application/yaml",
        )
        print(f"[ok] PUT s3://{BUCKET}/{prov_key}")

    return evidence_key


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--gene", required=True)
    p.add_argument("--indication", required=True,
                   help="OncoTree code (uppercase), e.g. COADREAD")
    p.add_argument("--subtype", default="all")
    p.add_argument("--dimension", default="expression-rna",
                   choices=["expression-rna"])
    p.add_argument("--parquet-uri", required=True,
                   help="DGE Parquet from 04_write_parquet.R (s3:// or local)")
    p.add_argument("--provenance-yaml", required=True,
                   help="provenance.yaml from 05_provenance.R")
    p.add_argument("--derived-manifest-id", required=True,
                   help="data-catalog derived manifest id, e.g. COADREAD-dge-abc1234")
    p.add_argument("--git-sha", required=True)
    p.add_argument("--label", default="pre-specified",
                   choices=["pre-specified", "exploratory"])
    p.add_argument("--profile", default="cbg")
    p.add_argument("--dry-run", action="store_true",
                   help="Build + validate the artifact; print without uploading.")
    p.add_argument("--out-json", default=None,
                   help="Optional: write the artifact to this local path too "
                        "(useful with --dry-run for inspection).")
    args = p.parse_args()

    provenance = yaml.safe_load(Path(args.provenance_yaml).read_text())
    row = fetch_gene_row(args.parquet_uri, args.gene, args.profile)

    artifact = build_evidence(
        gene=args.gene,
        indication=args.indication,
        subtype=args.subtype,
        dimension=args.dimension,
        row=row,
        provenance_yaml=provenance,
        derived_manifest_id=args.derived_manifest_id,
        git_sha=args.git_sha,
        label=args.label,
    )
    validate_or_die(artifact)

    if args.out_json:
        Path(args.out_json).write_text(json.dumps(artifact, indent=2))
        print(f"[ok] wrote local copy to {args.out_json}")

    upload_artifact(
        artifact, args.indication, args.subtype, args.gene, args.dimension,
        profile=args.profile,
        provenance_yaml_path=Path(args.provenance_yaml),
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
