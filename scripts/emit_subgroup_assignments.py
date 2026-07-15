#!/usr/bin/env python3
"""emit_subgroup_assignments.py — Phase 2b/c per-shard emission driver.

For a single (data_source × indication) shard:
  1. Invoke the appropriate assigner method
     (directly_tagged | maf_filter | classifier) against the subgroup catalog.
  2. Compute MD5 of the resulting assignments.parquet.
  3. Upload assignments.parquet + manifest.yaml to
     s3://onc-compbio/derived/subgroup-assignments/{indication}/{source}/{release_pin}/
     with x-amz-meta-md5 metadata stamping.
  4. Emit a derived-manifest stub YAML at data-catalog/manifests/derived/
     ready for one-branch-one-manifest PR.

This is Phase 2b/c operational-session workhorse. Not intended for interactive
per-target queries — the assigner methods themselves handle those.

Invocation:
    python -m scripts.emit_subgroup_assignments \
        --source tcga_marker_paper \
        --indication COADREAD \
        --release-pin 2026-Q2 \
        --catalog-repo /path/to/data-catalog \
        --run-dir ~/dev/framework-runs/subgroup-emit-2026-07-15/

    # Dry-run (prints plan; no S3 or method invocation):
    DRY_RUN=1 python -m scripts.emit_subgroup_assignments \
        --source tcga_marker_paper --indication COADREAD ...

Assigner-per-source mapping (declarative; drives which method to invoke):

    tcga_marker_paper     -> subgroup_assigner_directly_tagged (data-source=tcga)
    tcga_maf              -> subgroup_assigner_maf_filter      (data-source=tcga)
    depmap_omics_inferred -> subgroup_assigner_directly_tagged (data-source=depmap)
    depmap_somatic        -> subgroup_assigner_maf_filter      (data-source=depmap)
    depmap_expression     -> subgroup_assigner_classifier      (data-source=depmap)
    beataml_maf           -> subgroup_assigner_maf_filter      (custom MAF loader)
    target_aml_maf        -> subgroup_assigner_maf_filter      (custom MAF loader)

Batch driver (scripts/run_subgroup_batch.sh) iterates over the 20-shard matrix
and calls this script once per shard.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import click
import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]

# Source → (assigner_method_module, data_source_arg) mapping.
# The classifier assigner takes an additional --classifier-config arg;
# handled in _invoke_assigner below.
SOURCE_TO_ASSIGNER = {
    "tcga_marker_paper":     ("subgroup_assigner_directly_tagged", "tcga"),
    "tcga_maf":              ("subgroup_assigner_maf_filter",      "tcga"),
    "depmap_omics_inferred": ("subgroup_assigner_directly_tagged", "depmap"),
    "depmap_somatic":        ("subgroup_assigner_maf_filter",      "depmap"),
    "depmap_expression":     ("subgroup_assigner_classifier",      "depmap"),
    "beataml_maf":           ("subgroup_assigner_maf_filter",      "tcga"),
    "target_aml_maf":        ("subgroup_assigner_maf_filter",      "tcga"),
}

SourceKey = Literal[
    "tcga_marker_paper", "tcga_maf",
    "depmap_omics_inferred", "depmap_somatic", "depmap_expression",
    "beataml_maf", "target_aml_maf",
]


@dataclass(frozen=True)
class ShardSpec:
    """Descriptor for one Phase 2b/c emission shard."""
    source: str
    indication: str
    release_pin: str
    catalog_repo: Path
    run_dir: Path
    classifier_config: Path | None = None  # only for depmap_expression source

    @property
    def catalog_path(self) -> Path:
        """Locate the subgroup catalog YAML for this indication.

        Uses the 2026-Q2 catalog for COADREAD (anchor) and 2026-Q3 for all
        other iDAS indications. Falls back with a clear error if the file
        doesn't exist.
        """
        if self.indication == "COADREAD":
            path = self.catalog_repo / "subgroup-catalogs" / self.indication / "2026-Q2.yaml"
        else:
            path = self.catalog_repo / "subgroup-catalogs" / self.indication / "2026-Q3.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"Subgroup catalog not found: {path}. "
                f"Phase 1b ships 8 catalogs (target-contracts + data-catalog PRs merged 2026-07-15). "
                f"Verify data-catalog checkout is up to date."
            )
        return path

    @property
    def out_dir(self) -> Path:
        """Local staging directory for this shard's assignments.parquet + manifest.yaml."""
        return self.run_dir / self.indication / self.source

    @property
    def s3_uri_base(self) -> str:
        """S3 URI base prefix for uploads."""
        return (
            f"s3://onc-compbio/derived/subgroup-assignments/"
            f"{self.indication.lower()}/{self.source}/{self.release_pin.lower()}"
        )

    @property
    def derived_manifest_id(self) -> str:
        """Canonical derived-manifest id for the data-catalog PR."""
        return f"{self.source.replace('_', '-')}-subgroup-assignments-{self.indication.lower()}-v1"

    @property
    def derived_manifest_path(self) -> Path:
        """Where the derived-manifest YAML will land in data-catalog."""
        return self.catalog_repo / "manifests" / "derived" / f"{self.derived_manifest_id}.yaml"


def _log(msg: str) -> None:
    click.echo(f"[emit-subgroup-assignments] {msg}", err=True)


def _invoke_assigner(shard: ShardSpec, dry_run: bool) -> tuple[Path, Path]:
    """Invoke the appropriate assigner method for this shard.

    Returns:
      (assignments_parquet_path, manifest_yaml_path)
    """
    if shard.source not in SOURCE_TO_ASSIGNER:
        raise ValueError(f"Unknown source: {shard.source!r}. Valid: {list(SOURCE_TO_ASSIGNER)}")
    method_module, data_source_arg = SOURCE_TO_ASSIGNER[shard.source]

    shard.out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", f"methods.{method_module}.cli",
        "--subgroup-catalog", str(shard.catalog_path),
        "--data-source", data_source_arg,
        "--release-pin", shard.release_pin,
        "--catalog-repo", str(shard.catalog_repo),
        "--out", str(shard.out_dir),
    ]
    if method_module == "subgroup_assigner_classifier":
        if shard.classifier_config is None:
            raise ValueError(
                f"Source {shard.source!r} requires --classifier-config; none provided."
            )
        cmd.extend(["--classifier-config", str(shard.classifier_config)])

    _log(f"invoking: {' '.join(cmd)}")

    if dry_run:
        _log("DRY_RUN=1 — skipping actual invocation")
        # For dry-run we don't actually invoke; return the expected paths.
        return shard.out_dir / "assignments.parquet", shard.out_dir / "manifest.yaml"

    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    if result.returncode != 0:
        _log(f"ASSIGNER FAILED (rc={result.returncode}):")
        _log(result.stderr)
        sys.exit(result.returncode)

    assignments_path = shard.out_dir / "assignments.parquet"
    manifest_path = shard.out_dir / "manifest.yaml"
    if not assignments_path.exists() or not manifest_path.exists():
        raise FileNotFoundError(
            f"Assigner ran but expected outputs missing: "
            f"{assignments_path} + {manifest_path}. Check assigner stdout: {result.stdout}"
        )
    return assignments_path, manifest_path


def _md5sum(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _upload_to_s3(local_path: Path, s3_uri: str, md5: str, dry_run: bool) -> None:
    """Upload a local file to S3 with x-amz-meta-md5 metadata."""
    if dry_run:
        _log(f"DRY_RUN=1 — would upload {local_path} → {s3_uri} (md5={md5})")
        return
    cmd = [
        "aws", "s3", "cp", str(local_path), s3_uri,
        "--metadata", f"md5={md5}",
        "--no-progress",
    ]
    _log(f"uploading: {local_path.name} → {s3_uri}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        _log(f"UPLOAD FAILED (rc={result.returncode}):")
        _log(result.stderr)
        sys.exit(result.returncode)


def _emit_derived_manifest_stub(shard: ShardSpec, parquet_md5: str, manifest_md5: str,
                                 parquet_n_rows: int, dry_run: bool) -> None:
    """Emit a derived-manifest YAML stub in the data-catalog directory,
    ready for a one-branch-one-manifest PR.

    The stub carries the canonical fields required by data-catalog convention:
    id, manifest_kind, s3_uri, files[], provenance, cited_by. Manifest-schema
    validation is deferred to the data-catalog PR review step.
    """
    manifest_id = shard.derived_manifest_id
    manifest_yaml = {
        "id": manifest_id,
        "manifest_kind": "derived_product",
        "schema_version": 1,
        "indication": shard.indication,
        "release_pin": shard.release_pin,
        "s3_uri": shard.s3_uri_base,
        "source_manifest_ids": _upstream_manifest_ids(shard.source),
        "assigner_method": {
            "name": SOURCE_TO_ASSIGNER[shard.source][0],
            "release_pin": shard.release_pin,
        },
        "files": [
            {
                "path": "assignments.parquet",
                "md5": parquet_md5,
                "n_rows": parquet_n_rows,
                "description": "Tall per-(sample, stratum) assignment rows conforming to "
                               "target-contracts/schemas/subgroup_assignment.schema.json.",
            },
            {
                "path": "manifest.yaml",
                "md5": manifest_md5,
                "description": "Assigner-emitted subgroup_assignment manifest (co-located sidecar).",
            },
        ],
        "subgroup_catalog_ref": {
            "id": _catalog_id_from_shard(shard),
        },
        "notes": (
            f"Phase 2b/c emission — {shard.source} × {shard.indication}. "
            f"Consumed by Phase-3 methods via analysis-methods/methods/subgroup_common/"
            f"loaders.py:load_assignments({manifest_id!r})."
        ),
    }
    if dry_run:
        _log(f"DRY_RUN=1 — would write {shard.derived_manifest_path} "
             f"(id={manifest_id}, n_rows={parquet_n_rows})")
        return
    shard.derived_manifest_path.parent.mkdir(parents=True, exist_ok=True)
    shard.derived_manifest_path.write_text(yaml.safe_dump(manifest_yaml, sort_keys=False))
    _log(f"wrote {shard.derived_manifest_path}")


def _upstream_manifest_ids(source: str) -> list[str]:
    """Map a source key to the upstream source-manifest ids it consumes."""
    return {
        "tcga_marker_paper":     ["tcga-marker-papers-subtypes-2018"],
        "tcga_maf":              ["tcga-mc3-public-v0-2-8", "gdc-pancohort-somatic-dr45-0"],
        "depmap_omics_inferred": ["depmap-consortium-26q1"],
        "depmap_somatic":        ["depmap-consortium-26q1"],
        "depmap_expression":     ["depmap-consortium-26q1"],
        "beataml_maf":           ["gdc-pancohort-somatic-dr45-0"],   # BeatAML1.0-COHORT via GDC
        "target_aml_maf":        ["gdc-pancohort-somatic-dr45-0"],   # TARGET-AML via GDC
    }.get(source, [])


def _catalog_id_from_shard(shard: ShardSpec) -> str:
    """Match the id: field of the subgroup catalog for this indication.

    Matches the pattern used in target-contracts/schemas/subgroup_catalog.schema.json
    id-field examples: coadread-subgroups-2026-q2, nsclc-subgroups-2026-q3.
    """
    quarter = "2026-q2" if shard.indication == "COADREAD" else "2026-q3"
    return f"{shard.indication.lower()}-subgroups-{quarter}"


@click.command()
@click.option("--source", required=True, type=click.Choice(list(SOURCE_TO_ASSIGNER)),
              help="Data source key.")
@click.option("--indication", required=True,
              type=click.Choice(["COADREAD", "NSCLC", "SCLC", "HNSC", "STAD", "ESCA", "PAAD", "AML"]),
              help="iDAS canonical indication code.")
@click.option("--release-pin", required=True, help="Catalog release-pin (e.g. 2026-Q2 or 2026-Q3).")
@click.option("--catalog-repo", type=click.Path(file_okay=False, path_type=Path),
              default=Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"),
              help="Path to data-catalog repo.")
@click.option("--run-dir", type=click.Path(file_okay=False, path_type=Path),
              default=Path.home() / "dev" / "framework-runs" / "subgroup-emit",
              help="Local staging directory for compute artefacts.")
@click.option("--classifier-config", type=click.Path(exists=True, dir_okay=False, path_type=Path),
              default=None,
              help="Classifier config YAML — REQUIRED when --source=depmap_expression.")
def main(source: str, indication: str, release_pin: str, catalog_repo: Path,
         run_dir: Path, classifier_config: Path | None) -> int:
    """Emit one (source × indication) shard of subgroup assignments."""
    dry_run = bool(os.environ.get("DRY_RUN"))

    shard = ShardSpec(
        source=source, indication=indication, release_pin=release_pin,
        catalog_repo=catalog_repo, run_dir=run_dir,
        classifier_config=classifier_config,
    )

    _log(f"=== emit-subgroup-assignments ===")
    _log(f"  shard:           {source} × {indication}")
    _log(f"  release_pin:     {release_pin}")
    _log(f"  catalog:         {shard.catalog_path}")
    _log(f"  local out_dir:   {shard.out_dir}")
    _log(f"  s3 uri (base):   {shard.s3_uri_base}")
    _log(f"  manifest id:     {shard.derived_manifest_id}")
    _log(f"  manifest path:   {shard.derived_manifest_path}")

    # 1. Invoke assigner
    assignments_path, manifest_path = _invoke_assigner(shard, dry_run)

    # 2. Compute MD5s (skip in dry-run since files don't exist)
    if dry_run:
        parquet_md5 = "<dry-run-md5-not-computed>"
        manifest_md5 = "<dry-run-md5-not-computed>"
        n_rows = 0
    else:
        import pyarrow.parquet as pq
        parquet_md5 = _md5sum(assignments_path)
        manifest_md5 = _md5sum(manifest_path)
        n_rows = pq.read_metadata(assignments_path).num_rows
        _log(f"  parquet md5:  {parquet_md5}  ({n_rows} rows)")
        _log(f"  manifest md5: {manifest_md5}")

    # 3. Upload to S3
    _upload_to_s3(assignments_path, f"{shard.s3_uri_base}/assignments.parquet",
                  parquet_md5, dry_run)
    _upload_to_s3(manifest_path, f"{shard.s3_uri_base}/manifest.yaml",
                  manifest_md5, dry_run)

    # 4. Emit derived-manifest stub for data-catalog PR
    _emit_derived_manifest_stub(shard, parquet_md5, manifest_md5, n_rows, dry_run)

    _log(f"DONE {source} × {indication}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
