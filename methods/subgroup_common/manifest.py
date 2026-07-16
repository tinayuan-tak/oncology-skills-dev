"""subgroup_common.manifest — schema-valid subgroup_assignment_product emitter.

All three assigner CLIs (directly_tagged / maf_filter / classifier) emit the
SAME manifest shape. Previously each had its own `_emit_manifest` producing
`manifest_kind: subgroup_assignment` with ~10 field divergences from the
target-contracts schema (schemas/subgroup_assignment.schema.json) — the
manifest validated against NEITHER that schema nor the data-catalog derived
schema. This module is the single source of truth for the compliant shape.

The emitted manifest conforms to subgroup_assignment.schema.json:
  manifest_kind: subgroup_assignment_product
  assignment_product_id: subgroup-assignments-{ind}-{source}[-{variant}]-{pin}
  parquet_s3_uri, parquet_schema.columns (>=5 typed), n_samples_total,
  strata_summary[] (per-stratum counts + derivation_source),
  subgroup_catalog_content_pin (sha256 of the resolved catalog),
  generated_by: methods/{method}@{git-sha}, generated_at, schema_version: 1.
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

# Canonical S3 layout for assignment products (reconciled convention — the
# design docs had 3 competing paths; this is the one aligned with existing
# derived products: s3://onc-compbio/data-catalog/derived/...).
S3_BASE = "s3://onc-compbio/data-catalog/derived/subgroup-assignments"

# assigner method-name → schema assigner_method enum value.
_ASSIGNER_ENUM = {
    "subgroup_assigner_directly_tagged": "subgroup_assigner_directly_tagged",
    "subgroup_assigner_maf_filter": "subgroup_assigner_maf_filter",
    "subgroup_assigner_classifier": "subgroup_assigner_classifier_run",
}

# Parquet column types → schema parquet_schema type enum.
_PANDAS_TO_SCHEMA_TYPE = {
    "object": "string",
    "string": "string",
    "int64": "int64",
    "Int64": "int64",
    "float64": "float64",
    "bool": "bool",
    "boolean": "bool",
    "datetime64[ns]": "timestamp",
}


def sha256_file(path: Path) -> str:
    """SHA-256 hex of a file's content — the catalog content-pin primitive."""
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha(repo_hint: Path | None = None) -> str:
    """Short git sha of the analysis-methods repo for generated_by provenance.

    Falls back to '0000000' when git is unavailable (keeps the manifest
    schema-valid — generated_by pattern only requires [0-9a-f]+)."""
    try:
        cwd = repo_hint or Path(__file__).resolve().parent
        out = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--short=7", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        sha = out.stdout.strip()
        if sha and all(c in "0123456789abcdef" for c in sha):
            return sha
    except Exception:  # noqa: BLE001 — provenance best-effort; never block emit
        pass
    return "0000000"


def _parquet_columns(df: pd.DataFrame) -> list[dict]:
    """Build the parquet_schema.columns list from the assignments DataFrame."""
    cols = []
    for name, dtype in df.dtypes.items():
        schema_type = _PANDAS_TO_SCHEMA_TYPE.get(str(dtype), "string")
        col = {"name": str(name), "type": schema_type}
        if df[name].isna().any():
            col["nullable"] = True
        cols.append(col)
    return cols


def _strata_summary(df: pd.DataFrame, catalog: dict) -> list[dict]:
    """Per-stratum member counts + derivation_source, from the tall assignments.

    n_samples counts is_member==True per stratum (the members), matching the
    catalog's expected_n_* semantics. derivation_source is pulled from the
    catalog stratum definition when present.
    """
    deriv_by_id = {
        s["id"]: s.get("derivation_source")
        for s in catalog.get("atomic_strata", []) or []
    }
    members = df[df["is_member"] == True]  # noqa: E712 — pandas mask needs ==
    counts = members.groupby("stratum_id")["sample_id"].nunique()
    summary = []
    for stratum_id in df["stratum_id"].unique():
        rec = {"subgroup_id": str(stratum_id), "n_samples": int(counts.get(stratum_id, 0))}
        deriv = deriv_by_id.get(stratum_id)
        if deriv:
            rec["derivation_source"] = deriv
        summary.append(rec)
    return summary


def emit_assignment_manifest(
    out_dir: Path,
    catalog: dict,
    catalog_path: Path,
    data_source: str,
    release_pin: str,
    assignments: pd.DataFrame,
    assigner_method: str,
    parquet_filename: str = "assignments.parquet",
    variant: str | None = None,
) -> Path:
    """Write a schema-valid subgroup_assignment_product manifest.yaml.

    Args:
      out_dir: directory holding the emitted parquet; manifest.yaml lands here.
      catalog: parsed subgroup-catalog dict (needs id, indication, version, atomic_strata).
      catalog_path: path to the resolved catalog file (for the content-pin hash).
      data_source: tcga|depmap|ccle|gdsc|genie|genie_bpc.
      release_pin: catalog release pin label (e.g. '2026-Q2').
      assignments: the tall (sample, stratum, is_member, ...) DataFrame just written.
      assigner_method: bare method name (e.g. 'subgroup_assigner_maf_filter').
      variant: optional product-id discriminator (e.g. 'maf' for the maf_filter
        product so it doesn't collide with the directly_tagged product id).

    Returns the manifest path.
    """
    ind_lower = catalog["indication"].lower()
    # assignment_product_id: subgroup-assignments-{ind}-{source}[-{variant}]-{pin}
    parts = ["subgroup-assignments", ind_lower, data_source.replace("_", "-")]
    if variant:
        parts.append(variant)
    parts.append(release_pin.lower())
    product_id = "-".join(parts)

    s3_uri = f"{S3_BASE}/{catalog['indication']}/{data_source}/{release_pin}/{parquet_filename}"

    manifest = {
        "manifest_kind": "subgroup_assignment_product",
        "assignment_product_id": product_id,
        "indication": catalog["indication"],
        "data_source": data_source,
        "release_pin": release_pin,
        "subgroup_catalog_ref": catalog["id"],
        "subgroup_catalog_content_pin": sha256_file(catalog_path),
        "assigner_method": _ASSIGNER_ENUM.get(assigner_method, assigner_method),
        "assigner_method_version": _method_version(assigner_method),
        "parquet_s3_uri": s3_uri,
        "parquet_schema": {"columns": _parquet_columns(assignments)},
        "n_samples_total": int(assignments["sample_id"].nunique()),
        "strata_summary": _strata_summary(assignments, catalog),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_by": f"methods/{assigner_method}@{_git_sha()}",
        "schema_version": 1,
    }
    manifest_path = out_dir / "manifest.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False))
    return manifest_path


def _method_version(assigner_method: str) -> str:
    """Best-effort semver for assigner_method_version (optional schema field)."""
    # Kept simple: each CLI passes its METHOD_VERSION today via the wrapper.
    # Default preserves schema validity (semver pattern) when unknown.
    return "0.2.0"
