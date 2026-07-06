#!/usr/bin/env python3
"""dge_deseq2 CLI — thin Python wrapper over the R DESeq2 pipeline.

Invocation:
    dge-deseq2 --indication COADREAD \
               --contrast tumor_vs_adjacent \
               --release-pin 2026-Q2 \
               --catalog-repo /home/sagemaker-user/rnd-computational-biology-oncology-data-catalog \
               --out /tmp/dge_deseq2_run/

The CLI:
  1. Resolves --indication to a config YAML path under {catalog_repo}/subgroup-catalogs/{indication}/
     (or, during the migration window, falls back to legacy configs/{indication}.yaml in skills repo).
  2. Computes a git_sha for provenance.
  3. Invokes steps/run_pipeline.R with translated args.
  4. Validates the emitted Parquet against target-contracts/schemas/products/<product>.result.schema.json.

Iter-1 scope:
  - Only --contrast tumor_vs_adjacent is wired (the iter-1 dge-tumor-vs-adjacent product).
  - --stratify-by subgroup_catalog is an iter-1 deliverable but currently stubs;
    the R pipeline needs an iter-1 patch to read the subgroup catalog. Tracked in
    methods/dge_deseq2/tests/test_stratify_by_subgroup_catalog.py (TBD).
  - Byte-identity gate against legacy batch/expression_rna_COADREAD/ output:
    methods/dge_deseq2/tests/test_byte_identity_vs_legacy_coadread.py (TBD; requires R env).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click


METHOD_DIR = Path(__file__).resolve().parent
STEPS_DIR = METHOD_DIR / "steps"
RUN_PIPELINE = STEPS_DIR / "run_pipeline.R"


def resolve_config(indication: str, catalog_repo: Path | None) -> Path:
    """Find the indication's methods-facing config YAML.

    Resolution order (preferred → fallback):
      1. {catalog_repo}/indication-configs/{indication}.yaml        (R5 canonical location)
      2. {catalog_repo}/manifests/sources/{indication}.yaml         (alternative catalog location)

    NOTE: subgroup-catalogs/{indication}/{version}.yaml is a DIFFERENT artifact — it's the
    card-facing subgroup catalog, consumed by --stratify-by. Don't confuse the two.

    R7 cleanup (post-2026-06-26): the legacy claude-oncology-skills/configs/ fallback was
    removed when R7 deleted the migrated directories. Configs MUST live in the data-catalog
    repo from this point forward.
    """
    if not catalog_repo:
        raise click.ClickException(
            "--catalog-repo is required (R7: legacy fallback removed). "
            "Point at the rnd-computational-biology-oncology-data-catalog repo."
        )
    candidates = [
        catalog_repo / "indication-configs" / f"{indication}.yaml",
        catalog_repo / "manifests" / "sources" / f"{indication}.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise click.ClickException(
        f"No config found for indication={indication}. Searched: {[str(c) for c in candidates]}"
    )


def compute_git_sha(repo_path: Path) -> str:
    """Get the git HEAD sha of the repo (for provenance)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


@click.command()
@click.option("--indication", required=True, help="OncoTree code (e.g., COADREAD).")
@click.option("--contrast", default="tumor_vs_adjacent",
              type=click.Choice(["tumor_vs_adjacent", "four_cell_sensitivity",
                                  "tumor_vs_gtex", "subtype_stratified"]),
              help="DGE contrast. tumor_vs_adjacent = legacy GDC-STAR chain; "
                   "four_cell_sensitivity = recount3 four-cell discipline "
                   "(cells A/B/C/D + sensitivity.parquet).")
@click.option("--gtex-tissue", default=None,
              help="Override recount3 GTEx tissue code (four_cell_sensitivity only).")
@click.option("--release-pin", required=True, help="Catalog release_pin (e.g., 2026-Q2).")
@click.option("--catalog-repo", type=click.Path(file_okay=False, path_type=Path),
              default=Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"),
              help="Path to the data-catalog repo for config resolution.")
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path),
              help="Output directory for intermediate .rds + final parquet + provenance.")
@click.option("--parquet-uri", default=None,
              help="Final Parquet destination URI (s3:// or local). Defaults to {out}/result.parquet.")
@click.option("--threads", type=int, default=4)
@click.option("--stratify-by", default=None,
              help="Stratification axis. 'subgroup_catalog' enables per-subgroup DGE. ITER-1 STUB.")
@click.option("--gtex-tissue-override", "gtex_tissue", default=None,
              help="Override recount3 GTEx tissue code (four_cell_sensitivity only).")
@click.option("--dry-run", is_flag=True, help="Print the Rscript invocation without running it.")
def main(indication: str, contrast: str, release_pin: str, catalog_repo: Path,
         out: Path, parquet_uri: str | None, threads: int, stratify_by: str | None,
         gtex_tissue: str | None, dry_run: bool) -> int:
    """Invoke the DGE DESeq2 R pipeline for an indication × contrast."""

    if contrast in ("tumor_vs_gtex", "subtype_stratified"):
        raise click.ClickException(
            f"contrast={contrast} is not a standalone pipeline. tumor-vs-GTEx is now "
            f"a cell WITHIN --contrast four_cell_sensitivity (cell C); subtype_stratified "
            f"remains an iter-1 stub. Use four_cell_sensitivity or tumor_vs_adjacent."
        )

    if stratify_by:
        click.echo(
            f"WARNING: --stratify-by {stratify_by} is an iter-1 STUB; the R pipeline needs an "
            f"iter-1 patch to consume the subgroup catalog. Card 5 (subgroup-stratified-expression) "
            f"is blocked on this.",
            err=True,
        )

    out.mkdir(parents=True, exist_ok=True)

    config_path = resolve_config(indication, catalog_repo)
    if parquet_uri is None:
        parquet_uri = str(out / "result.parquet")

    git_sha = compute_git_sha(METHOD_DIR.parent.parent)

    cmd = [
        "Rscript", str(RUN_PIPELINE),
        f"--config={config_path}",
        f"--catalog-repo={catalog_repo}",
        f"--git-sha={git_sha}",
        f"--out-dir={out}",
        f"--parquet-uri={parquet_uri}",
        f"--threads={threads}",
        f"--contrast={contrast}",
    ]
    if gtex_tissue:
        cmd.append(f"--gtex-tissue={gtex_tissue}")

    click.echo(f"=== dge-deseq2 invocation ===")
    click.echo(f"  indication:   {indication}")
    click.echo(f"  contrast:     {contrast}")
    click.echo(f"  release-pin:  {release_pin}")
    click.echo(f"  config:       {config_path}")
    click.echo(f"  catalog-repo: {catalog_repo}")
    click.echo(f"  out:          {out}")
    click.echo(f"  parquet-uri:  {parquet_uri}")
    click.echo(f"  git-sha:      {git_sha}")
    if contrast == "four_cell_sensitivity":
        click.echo(f"  gtex-tissue:  {gtex_tissue or '(derived from config)'}")
    click.echo()
    click.echo(f"  Rscript cmd:  {' '.join(cmd)}")

    if dry_run:
        click.echo("(--dry-run: skipping execution)")
        return 0

    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except FileNotFoundError:
        raise click.ClickException(
            "Rscript not found on PATH. dge-deseq2 requires R + DESeq2 (see methods/ pixi.toml)."
        )


if __name__ == "__main__":
    sys.exit(main())
