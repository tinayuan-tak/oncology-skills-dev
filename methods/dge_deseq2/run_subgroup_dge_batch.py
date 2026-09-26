#!/usr/bin/env python3
"""dge_deseq2.run_subgroup_dge_batch — the multi-axis by-subgroup DGE orchestrator (#738).

Runs the whole by-subgroup product for one indication in a single invocation, config-driven off
:func:`methods.dge_deseq2.config.subgroup_axes`:

  1. Load recount3 ONCE per indication (``00_load_recount3.R`` -> ``<out>/00_recount3.rds``). The
     stratified driver only subsets the TUMOR arm per stratum, so the cached bundle is shared across
     every axis — invoking ``run_pipeline.R`` per axis would reload recount3 each time.
  2. Per axis: resolve the assignment product to a local parquet
     (``subgroup_common.load_assignments``), then run
     ``07_stratified_four_cell_driver.R`` on the cached ``.rds`` into ``<out>/_axis_<axis>/``.
  3. Concatenate the per-axis ``sensitivity_by_subgroup.parquet`` shards (UNION columns, NA fill,
     sorted by ``[stratum_id, gene_symbol]``) into ``<out>/sensitivity_by_subgroup.parquet``.
  4. Merge the per-axis / per-stratum QC bundles into ``<out>/qc/<axis>__<stratum>/<cell>/`` and
     concatenate every per-stratum ``qc_summary.csv`` into ``<out>/qc/qc_summary.csv``.
  5. Aggregate the per-axis ``provenance_by_subgroup.yaml`` into one ``<out>/provenance_by_subgroup.yaml``.
  6. With ``--emit``: land the package via :mod:`emit_subgroup_data_package`.

The PLANNING surface — :func:`build_rscript_commands` (the ordered Rscript command list) and
:func:`concat_axis_parquets` (the pure column-union concat) — is unit-tested. The impure Rscript /
subprocess / filesystem shuffling is isolated below them.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import click
import yaml

from methods.subgroup_common.loaders import CACHE_ASSIGNMENTS, load_assignments

from . import config as _config
from .cli import compute_git_sha, resolve_config

METHOD_DIR = Path(__file__).resolve().parent
R_LIVE = METHOD_DIR / "r" / "live"
R_LOAD_RECOUNT3 = R_LIVE / "00_load_recount3.R"
R_STRATIFIED = R_LIVE / "07_stratified_four_cell_driver.R"

_RDS_NAME = "00_recount3.rds"
_SUBGROUP_PARQUET = "sensitivity_by_subgroup.parquet"
_SUBGROUP_PROVENANCE = "provenance_by_subgroup.yaml"


# --------------------------------------------------------------------------- #
# pure planning
# --------------------------------------------------------------------------- #
def _assignments_parquet(manifest_id: str) -> str:
    """Local cache path load_assignments writes the assignment parquet to (matches cli.py)."""
    return str(CACHE_ASSIGNMENTS / manifest_id / "assignments.parquet")


def _axis_out_dir(out_dir: Path, axis: str) -> Path:
    return Path(out_dir) / f"_axis_{axis}"


def build_rscript_commands(
    indication: str,
    config_path: Path,
    out_dir: Path,
    *,
    min_subgroup_tumor: int = 10,
    threads: int = 4,
    axes: list[dict] | None = None,
) -> list[list[str]]:
    """Build the ordered Rscript command list: one recount3 load + one 07 driver run per axis.

    Pure: constructs the assignment-parquet cache path (no I/O — the download happens in the impure
    orchestrator) and the per-axis out-dir. ``axes`` defaults to ``subgroup_axes()[indication]``,
    resolved against the config module at call time so it is monkeypatchable.
    """
    if axes is None:
        axes = _config.subgroup_axes()[indication]
    out_dir = Path(out_dir)
    rds_path = out_dir / _RDS_NAME

    commands: list[list[str]] = [["Rscript", str(R_LOAD_RECOUNT3), f"--config={config_path}", f"--out={rds_path}"]]
    for ax in axes:
        commands.append(
            [
                "Rscript",
                str(R_STRATIFIED),
                f"--in={rds_path}",
                f"--assignments={_assignments_parquet(ax['assignments_manifest'])}",
                f"--axis={ax['axis']}",
                f"--strata={','.join(ax['strata'])}",
                f"--min-subgroup-tumor={min_subgroup_tumor}",
                f"--out-dir={_axis_out_dir(out_dir, ax['axis'])}",
                f"--threads={threads}",
            ]
        )
    return commands


def concat_axis_parquets(frames):
    """Concatenate per-axis sensitivity frames: UNION columns (missing -> NA), sort by keys.

    Pure function of a list of DataFrames so a test can feed synthetic frames. A stratum/axis where a
    cell was skipped lacks that cell's log2fc/padj columns; those become NA in the union. Rows are
    sorted by ``[stratum_id, gene_symbol]`` so the parquet groups per stratum (query optimization,
    matching the 07 driver's own per-stratum concat).
    """
    import pandas as pd

    if not frames:
        raise ValueError("concat_axis_parquets: no per-axis frames to concatenate")
    all_cols: list[str] = []
    for df in frames:
        for c in df.columns:
            if c not in all_cols:
                all_cols.append(c)
    aligned = [df.reindex(columns=all_cols) for df in frames]
    combined = pd.concat(aligned, ignore_index=True)
    sort_keys = [k for k in ("stratum_id", "gene_symbol") if k in combined.columns]
    if sort_keys:
        combined = combined.sort_values(sort_keys, kind="stable").reset_index(drop=True)
    return combined


def _as_stratum_list(v) -> list:
    """Coerce a per-axis ``strata_{emitted,requested}`` value to a list of stratum names.

    The R driver serialises a SINGLE-stratum axis as a bare YAML scalar (e.g. ``strata_emitted:
    HER2_amp``) because R/yaml flattens a length-1 vector to a scalar. A naive ``list(...)`` would then
    iterate the *string* and explode it into characters (``['H','E','R','2',...]``). Wrap scalars in a
    one-element list; pass through real lists; drop ``None``/empty.
    """
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    return list(v)


def aggregate_subgroup_provenance(indication: str, axes: list[dict], per_axis_provs: list[dict]) -> dict:
    """Aggregate the per-axis ``provenance_by_subgroup.yaml`` docs into one indication-level doc.

    Whole-cohort scalars (substrate, tcga_studies, gtex_tissue, n_adjacent, n_gtex, versions) are
    constant across axes (only the tumor arm is subset), so they are taken from the first axis;
    per-axis structure (strata_{emitted,requested}, cells_ran) is unioned.
    """
    first = per_axis_provs[0] if per_axis_provs else {}
    strata_emitted: dict[str, list] = {}
    strata_requested: dict[str, list] = {}
    n_tumor_by_stratum: dict[str, int] = {}
    cells_ran: set[str] = set()
    for ax, prov in zip(axes, per_axis_provs):
        axis = ax["axis"]
        strata_emitted[axis] = _as_stratum_list(prov.get("strata_emitted"))
        strata_requested[axis] = _as_stratum_list(prov.get("strata_requested"))
        for stratum, n in (prov.get("n_tumor_by_stratum") or {}).items():
            n_tumor_by_stratum[stratum] = n
        for cells in (prov.get("cells_ran_by_stratum") or {}).values():
            cells_ran.update(cells)
    return {
        "indication": indication.upper(),
        "substrate": first.get("substrate"),
        "tcga_studies": first.get("tcga_studies"),
        "gtex_tissue": first.get("gtex_tissue"),
        "subgroup_axes": [ax["axis"] for ax in axes],
        "strata_emitted": strata_emitted,
        "strata_requested": strata_requested,
        "n_tumor_by_stratum": n_tumor_by_stratum,
        "n_adjacent": first.get("n_adjacent"),
        "n_gtex": first.get("n_gtex"),
        "cells_ran": sorted(cells_ran),
        "member_key": first.get("member_key"),
        "min_subgroup_tumor": first.get("min_subgroup_tumor"),
        "deseq2_version": first.get("deseq2_version"),
        "apeglm_version": first.get("apeglm_version"),
        "sva_version": first.get("sva_version"),
        "schema_version": "1",
    }


# --------------------------------------------------------------------------- #
# impure steps
# --------------------------------------------------------------------------- #
def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _concat_step(out_dir: Path, axes: list[dict]) -> Path:
    import pandas as pd

    frames = []
    for ax in axes:
        shard = _axis_out_dir(out_dir, ax["axis"]) / _SUBGROUP_PARQUET
        if shard.is_file():
            frames.append(pd.read_parquet(shard))
    if not frames:
        raise FileNotFoundError(f"no per-axis {_SUBGROUP_PARQUET} shards under {out_dir}")
    combined = concat_axis_parquets(frames)
    out_path = out_dir / _SUBGROUP_PARQUET
    combined.to_parquet(out_path, compression="snappy")
    return out_path


def _qc_merge_step(out_dir: Path, axes: list[dict]) -> None:
    import csv

    qc_root = out_dir / "qc"
    qc_root.mkdir(parents=True, exist_ok=True)
    summary_rows: list[list[str]] = []
    header: list[str] | None = None
    for ax in axes:
        axis_dir = _axis_out_dir(out_dir, ax["axis"])
        for strat_dir in sorted(axis_dir.glob("_strat_*")):
            stratum = strat_dir.name[len("_strat_") :]
            src_qc = strat_dir / "qc"
            if not src_qc.is_dir():
                continue
            for cell_dir in sorted(p for p in src_qc.iterdir() if p.is_dir()):
                dest = qc_root / f"{ax['axis']}__{stratum}" / cell_dir.name
                shutil.copytree(cell_dir, dest, dirs_exist_ok=True)
            per_summary = src_qc / "qc_summary.csv"
            if per_summary.is_file():
                with per_summary.open(newline="") as fh:
                    rows = list(csv.reader(fh))
                if rows:
                    header = header or rows[0]
                    summary_rows.extend(rows[1:])
    if header is not None:
        with (qc_root / "qc_summary.csv").open("w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(summary_rows)


def _provenance_step(out_dir: Path, indication: str, axes: list[dict]) -> Path:
    per_axis_provs = []
    for ax in axes:
        p = _axis_out_dir(out_dir, ax["axis"]) / _SUBGROUP_PROVENANCE
        if p.is_file():
            per_axis_provs.append(yaml.safe_load(p.read_text()))
    agg = aggregate_subgroup_provenance(indication, axes, per_axis_provs)
    out_path = out_dir / _SUBGROUP_PROVENANCE
    out_path.write_text(yaml.safe_dump(agg, sort_keys=False))
    return out_path


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
@click.command()
@click.option("--indication", required=True, help="OncoTree code with curated subgroup axes (e.g. ESCA).")
@click.option(
    "--catalog-repo",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Path to the data-catalog repo (config resolution + assignment-manifest fetch).",
)
@click.option("--out", required=True, type=click.Path(file_okay=False, path_type=Path), help="Run out-dir.")
@click.option("--min-subgroup-tumor", type=int, default=10, help="Min tumor members for a stratum to emit.")
@click.option("--threads", type=int, default=4)
@click.option("--release-pin", default="2026-Q3", help="Catalog release_pin (provenance only).")
@click.option("--emit/--no-emit", default=False, help="After concat, land the package via emit_subgroup_data_package.")
@click.option("--dry-run", is_flag=True, help="Print the ordered command list + planned concat/emit; do not execute.")
def main(
    indication: str,
    catalog_repo: Path,
    out: Path,
    min_subgroup_tumor: int,
    threads: int,
    release_pin: str,
    emit: bool,
    dry_run: bool,
) -> int:
    """Run the multi-axis by-subgroup DGE product for one indication."""
    axes = _config.subgroup_axes()[indication]
    config_path = resolve_config(indication, catalog_repo)
    out.mkdir(parents=True, exist_ok=True)

    commands = build_rscript_commands(
        indication, config_path, out, min_subgroup_tumor=min_subgroup_tumor, threads=threads, axes=axes
    )

    click.echo("=== run_subgroup_dge_batch ===")
    click.echo(f"  indication:        {indication}")
    click.echo(f"  catalog-repo:      {catalog_repo}")
    click.echo(f"  config:            {config_path}")
    click.echo(f"  out:               {out}")
    click.echo(f"  release-pin:       {release_pin}")
    click.echo(f"  axes:              {[ax['axis'] for ax in axes]}")
    click.echo(f"  min-subgroup-tumor:{min_subgroup_tumor}")
    for cmd in commands:
        click.echo(f"  Rscript cmd: {' '.join(cmd)}")
    click.echo(f"  concat -> {out / _SUBGROUP_PARQUET}")
    click.echo(f"  emit: {emit}")

    if dry_run:
        click.echo("(--dry-run: skipping execution)")
        return 0

    # Step 1: load recount3 once.
    _run(commands[0])
    # Step 2: resolve assignments + run the 07 driver per axis.
    for ax, cmd in zip(axes, commands[1:]):
        load_assignments(ax["assignments_manifest"], data_catalog_repo=catalog_repo)
        _run(cmd)
    # Steps 3-5: concat, QC merge, provenance aggregate.
    parquet = _concat_step(out, axes)
    _qc_merge_step(out, axes)
    _provenance_step(out, indication, axes)
    click.echo(f"[run_subgroup_dge_batch] wrote {parquet}")

    # Step 6: optional emit.
    if emit:
        from . import emit_subgroup_data_package as esdp

        git_sha = compute_git_sha(METHOD_DIR.parent.parent)
        esdp.main(["--out-dir", str(out), "--indication", indication, "--git-sha", git_sha])
    return 0


if __name__ == "__main__":
    sys.exit(main())
