#!/usr/bin/env python3
"""subgroup_assigner_maf_filter CLI — generate per-sample subgroup assignments from MAF predicates.

Invocation:
    subgroup-assigner-maf-filter \
      --subgroup-catalog /path/to/coadread-subgroups-2026-q2.yaml \
      --data-source tcga \
      --release-pin 2026-Q2 \
      --catalog-repo /path/to/data-catalog \
      --out /path/to/output-dir/

The CLI:
  1. Loads the subgroup_catalog YAML; filters to atomic_strata with derivation_source == maf_filter_per_rule.
  2. Resolves the MAF input manifest from the catalog (typically gdc-pancohort-somatic-dr45-0
     for TCGA, OmicsSomaticMutations.csv for DepMap).
  3. For each MAF-derived stratum: applies the predicate (e.g., gene_symbol=='KRAS' AND
     protein_change=='p.G12C') against the MAF Parquet/CSV; groups by case_id; emits
     (case_id, subgroup_id, derivation_value=protein_change) rows.
  4. Writes assignments.parquet + manifest.yaml.

Iter-1b status: SCAFFOLDED. The CLI parses arguments, filters catalog to applicable strata,
and prints the plan. Actual MAF reading + predicate evaluation + Parquet emission is the
iter-1b execution-session deliverable. Reuses the gdc_somatic_hotspot method's MAF-loading
utilities when fully implemented.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml


METHOD_DIR = Path(__file__).resolve().parent
METHOD_VERSION = "0.1.0"

SUPPORTED_DERIVATION_SOURCES = {"maf_filter_per_rule"}


@click.command()
@click.option("--subgroup-catalog", required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to the subgroup_catalog YAML.")
@click.option("--data-source", required=True, type=click.Choice(["tcga", "depmap"]),
              help="Which data source's MAF to assign against.")
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
    """Generate per-sample subgroup assignments from MAF-filter predicates."""
    with subgroup_catalog.open() as f:
        catalog = yaml.safe_load(f)

    indication = catalog.get("indication")
    catalog_id = catalog.get("id")
    atomic = catalog.get("atomic_strata", [])

    applicable = []
    for s in atomic:
        if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES:
            continue
        applicable_sources = s.get("applicable_data_sources", [])
        if data_source not in applicable_sources:
            continue
        applicable.append(s)

    click.echo(f"=== subgroup_assigner_maf_filter ===")
    click.echo(f"  catalog:       {catalog_id} (indication={indication})")
    click.echo(f"  data_source:   {data_source}")
    click.echo(f"  release_pin:   {release_pin}")
    click.echo(f"  out:           {out}")
    click.echo(f"  applicable MAF-filter strata ({len(applicable)} of {len(atomic)}):")
    for s in applicable:
        gene_hint = ""
        rule = s.get("rule", "")
        if "gene_symbol" in rule:
            # Extract gene name from rule for at-a-glance scan
            import re
            m = re.search(r"gene_symbol\s*==\s*['\"]([A-Z0-9]+)['\"]", rule)
            if m:
                gene_hint = f"  [gene={m.group(1)}]"
        click.echo(f"    - {s['id']:<20}{gene_hint}")
        click.echo(f"      rule: {rule}")

    skipped = [s["id"] for s in atomic if s.get("derivation_source") not in SUPPORTED_DERIVATION_SOURCES]
    if skipped:
        click.echo(f"  skipped strata (non-MAF derivation): {skipped}")
        click.echo(f"  → dispatch to subgroup_assigner_directly_tagged (clinical / source-provided) "
                   f"or subgroup_assigner_classifier_run (classifier_run, iter-2)")

    if not applicable:
        click.echo(f"WARNING: no applicable MAF-filter strata for data_source={data_source}; nothing to emit.", err=True)
        return 0

    if dry_run:
        click.echo("(--dry-run: skipping actual assignment generation)")
        return 0

    click.echo()
    click.echo("ITER-1B SCAFFOLD: actual assignment generation pending.")
    click.echo("Required implementation steps for execution session:")
    click.echo("  1. Resolve MAF manifest from catalog-repo:")
    click.echo("     - tcga data-source → gdc-pancohort-somatic-dr45-0")
    click.echo("     - depmap data-source → OmicsSomaticMutations.csv from depmap-consortium-26q1")
    click.echo("  2. Load MAF Parquet/CSV; restrict to indication-relevant samples.")
    click.echo("  3. For each MAF-filter stratum, apply the predicate; group by case_id;")
    click.echo("     collect assignments (handle multi-gene composite rules at the case_id grouping step).")
    click.echo("  4. Emit assignments.parquet + manifest.yaml validating against subgroup_assignment.schema.json.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
