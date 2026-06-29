#!/usr/bin/env python3
"""subgroup_assigner_directly_tagged CLI — generate per-sample subgroup assignments
from directly-tagged source fields.

Invocation:
    subgroup-assigner-directly-tagged \
      --subgroup-catalog /path/to/coadread-subgroups-2026-q2.yaml \
      --data-source tcga \
      --release-pin 2026-Q2 \
      --catalog-repo /path/to/data-catalog \
      --out /path/to/output-dir/

The CLI:
  1. Loads the subgroup_catalog YAML; filters to atomic_strata with derivation_source in
     {directly_tagged_clinical, directly_tagged_source_provided}.
  2. Resolves the catalog's input manifest (e.g., tcga-gdc-dr45-0 for TCGA clinical).
  3. For each directly-tagged stratum: applies the simple field-equals predicate against
     the source data; emits (case_id, subgroup_id, derivation_value) rows.
  4. Writes:
       <out>/assignments.parquet  (the per-sample assignment table)
       <out>/manifest.yaml        (the subgroup_assignment manifest validating against schema)

Iter-1b status: SCAFFOLDED. The CLI parses arguments and prints the plan; the actual
clinical-metadata reader + Parquet emitter is the iter-1b execution-session deliverable.
The dry-run path exercises the resolution + planning logic without requiring the catalog
manifest data.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

# Derivation sources this method handles. Other sources (maf_filter_per_rule, classifier_run)
# are dispatched to other assigner methods.
SUPPORTED_DERIVATION_SOURCES = {
    "directly_tagged_clinical",
    "directly_tagged_source_provided",
}


@click.command()
@click.option("--subgroup-catalog", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to the subgroup_catalog YAML.")
@click.option("--data-source", required=True, type=click.Choice(["tcga", "depmap"]),
              help="Which data source to assign against.")
@click.option("--release-pin", required=True, help="Catalog release_pin identifier (e.g., 2026-Q2).")
@click.option("--catalog-repo", type=click.Path(file_okay=False, path_type=Path),
              default=Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"),
              help="Path to the data-catalog repo for input-manifest resolution.")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Output directory; assignments.parquet + manifest.yaml land here.")
@click.option("--dry-run", is_flag=True,
              help="Parse the catalog, print the plan, do not produce assignments.")
def main(subgroup_catalog: Path, data_source: str, release_pin: str,
         catalog_repo: Path, out: Path, dry_run: bool) -> int:
    """Generate per-sample subgroup assignments from directly-tagged source fields."""
    with subgroup_catalog.open() as f:
        catalog = yaml.safe_load(f)

    indication = catalog.get("indication")
    catalog_id = catalog.get("id")
    atomic = catalog.get("atomic_strata", [])

    # Filter to directly-tagged strata applicable to the requested data_source
    applicable = []
    for s in atomic:
        if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES:
            continue
        applicable_sources = s.get("applicable_data_sources", [])
        if data_source not in applicable_sources:
            continue
        applicable.append(s)

    click.echo(f"=== subgroup_assigner_directly_tagged ===")
    click.echo(f"  catalog:       {catalog_id} (indication={indication})")
    click.echo(f"  data_source:   {data_source}")
    click.echo(f"  release_pin:   {release_pin}")
    click.echo(f"  out:           {out}")
    click.echo(f"  applicable strata ({len(applicable)} of {len(atomic)}):")
    for s in applicable:
        click.echo(f"    - {s['id']:<20} rule={s['rule']!r}")

    skipped = [s["id"] for s in atomic if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES]
    if skipped:
        click.echo(f"  skipped strata (non-tagged derivation): {skipped}")
        click.echo(f"  → dispatch these to subgroup_assigner_maf_filter (maf_filter_per_rule) "
                   f"or subgroup_assigner_classifier_run (classifier_run, iter-2)")

    if not applicable:
        click.echo(f"WARNING: no applicable directly-tagged strata for data_source={data_source}; nothing to emit.", err=True)
        return 0

    if dry_run:
        click.echo("(--dry-run: skipping actual assignment generation)")
        return 0

    # ============ Iter-1b SCAFFOLD ============
    # The actual implementation reads the catalog's input manifest, applies each stratum's
    # rule (e.g., `clinical.msi_status == 'MSI-H'`) against the clinical metadata, and
    # emits the assignment Parquet + manifest.yaml. Iter-1b execution-session deliverable.
    click.echo()
    click.echo("ITER-1B SCAFFOLD: actual assignment generation pending.")
    click.echo("Required implementation steps for execution session:")
    click.echo("  1. Resolve TCGA clinical metadata manifest from catalog-repo (tcga-gdc-dr45-0).")
    click.echo("  2. Load the clinical Parquet/CSV for the indication.")
    click.echo("  3. For each applicable stratum, apply the rule predicate, collect case_ids.")
    click.echo("  4. Emit assignments.parquet (one row per (case_id, subgroup_id)).")
    click.echo("  5. Emit manifest.yaml validating against target-contracts/schemas/subgroup_assignment.schema.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
