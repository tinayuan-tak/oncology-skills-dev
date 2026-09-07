#!/usr/bin/env python3
"""prefetch_guinney_cms.py — stage the Guinney 2015 CRC CMS consortium files
the COADREAD subgroup assigner reads.

The `subgroup_assigner_directly_tagged` CLI reads two Guinney files from a
LOCAL cache dir (`~/.cache/framework-guinney-2015-crc-cms/`):
  - cms_labels_public_all.txt          → CMS1-4 molecular-subtype labels
  - clinical_molecular_public_all.txt  → CIMP methylator-phenotype labels

Both live in S3 under
  s3://onc-compbio/data-catalog/sources/guinney-2015-crc-cms/
(see manifests/sources/guinney-2015-crc-cms-consortium.yaml in data-catalog).

BUG THIS FIXES: no prefetch step populated that cache dir, so the assigner's
`if cms_fallback.exists()` guard was False at emit time — the whole CMS+CIMP
merge was silently skipped and every CMS1-4 / CIMP_* stratum was emitted with
`is_member=None` for all 276 COADREAD samples (an all-null stratum family,
invisible downstream because the product still HAD rows). Mirrors the
prefetch_marker_paper.py / prefetch_cn_gistic.py pattern so the emit batch can
stage this source the same way.

Usage:
    python scripts/prefetch_guinney_cms.py
    DRY_RUN=1 python scripts/prefetch_guinney_cms.py   # print planned downloads
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click

S3_BUCKET = "onc-compbio"
S3_PREFIX = "data-catalog/sources/guinney-2015-crc-cms"
CACHE_DIR = "framework-guinney-2015-crc-cms"

# The two files the assigner reads (subgroup_assigner_directly_tagged/cli.py).
FILES = ("cms_labels_public_all.txt", "clinical_molecular_public_all.txt")


def _log(msg: str) -> None:
    click.echo(f"[prefetch-guinney-cms] {msg}", err=True)


def _s3_download(filename: str, dest: Path, dry_run: bool) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        _log(f"cache hit: {dest} (skip download)")
        return
    key = f"{S3_PREFIX}/{filename}"
    if dry_run:
        _log(f"DRY_RUN: would download s3://{S3_BUCKET}/{key} → {dest}")
        return
    _log(f"downloading s3://{S3_BUCKET}/{key} → {dest}")
    r = subprocess.run(
        ["aws", "s3", "cp", f"s3://{S3_BUCKET}/{key}", str(dest), "--no-progress"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        _log(f"download FAILED: {r.stderr}")
        sys.exit(r.returncode)


@click.command()
def main() -> int:
    """Stage the Guinney CMS + clinical files into the assigner's cache dir.

    Guinney is a COADREAD-only source (CRC Consensus Molecular Subtypes), so —
    unlike the marker-paper/MAF prefetchers — there is no --indication arg.
    """
    dry_run = os.environ.get("DRY_RUN") == "1"
    out_dir = Path.home() / ".cache" / CACHE_DIR
    _log("=== prefetch Guinney 2015 CRC CMS consortium ===")
    _log(f"  cache dir: {out_dir}")
    for fn in FILES:
        _s3_download(fn, out_dir / fn, dry_run=dry_run)
    _log("done.")
    return 0


if __name__ == "__main__":
    main()
