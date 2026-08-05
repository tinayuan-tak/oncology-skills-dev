#!/usr/bin/env python3
"""
build_subgroup_coverage_matrix.py — derive the subgroup coverage matrix.

The coverage matrix answers, per indication: for each atomic stratum, is there an
emitted assignments product covering it, and is that product usable? It is a
DERIVED artifact — never hand-authored — computed by joining three sources of
truth (per the architecture review):

  1. what strata COULD exist   → data-catalog subgroup-catalogs/{IND}/*.yaml atomic_strata
  2. what actually RESOLVED     → emitted subgroup_assignment_product manifests
                                  (strata_summary counts + content-pin freshness)
  3. the subgroup-n floor       → default 30 (matches subgroup_common.SUBGROUP_N_FLOOR)

Per (stratum × data_source) cell, status ∈:
  live         — emitted, content-pin fresh, n >= floor
  below_floor  — emitted, content-pin fresh, 0 < n < floor (renders, underpowered)
  stale        — emitted but content-pin != current catalog hash (needs re-emit)
  data_blocked — stratum declares the source in applicable_data_sources but no
                 product covers it (nothing emitted, or n==0)
  out_of_scope — stratum does not declare this data_source as applicable

Emits coverage/{INDICATION}.coverage.yaml. Run with --check to fail (exit 1) when
the committed matrix differs from a freshly-computed one — the "generated file is
stale" CI guard that keeps the matrix honest.

Usage:
  python build_subgroup_coverage_matrix.py --indication COADREAD
  python build_subgroup_coverage_matrix.py --indication COADREAD --check
  python build_subgroup_coverage_matrix.py --all            # every catalog
"""

from __future__ import annotations
import os

import argparse
import hashlib
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
COVERAGE_DIR = REPO / "coverage"
DEFAULT_CATALOG_REPO = Path(os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog"))
# Where locally-emitted products live (session cache). Phase-2b/c will add the
# published-manifest path; the generator reads whichever is present.
DEFAULT_PRODUCTS_ROOT = Path.home() / ".cache" / "framework-subgroup-pipeline" / "subgroup-assignments"
SUBGROUP_N_FLOOR = 30


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_catalog(indication: str, catalog_repo: Path) -> tuple[dict, Path] | tuple[None, None]:
    ind_dir = catalog_repo / "subgroup-catalogs" / indication
    if not ind_dir.exists():
        return None, None
    cats = sorted(ind_dir.glob("*.yaml"))
    if not cats:
        return None, None
    # Latest by filename (quarter labels sort lexically: 2026-Q2 < 2026-Q3).
    path = cats[-1]
    return yaml.safe_load(path.read_text()), path


def _emitted_products(indication: str, products_root: Path) -> list[dict]:
    """Load emitted manifests for an indication (by manifest.indication match)."""
    out = []
    if not products_root.exists():
        return out
    for mpath in sorted(products_root.rglob("manifest.yaml")):
        m = yaml.safe_load(mpath.read_text())
        if m.get("indication") == indication and m.get("manifest_kind") == "subgroup_assignment_product":
            out.append(m)
    return out


def _cell_status(n: int | None, pin_fresh: bool) -> str:
    if not pin_fresh:
        return "stale"
    if n is None or n == 0:
        return "data_blocked"
    if n < SUBGROUP_N_FLOOR:
        return "below_floor"
    return "live"


def build_matrix(indication: str, catalog_repo: Path, products_root: Path) -> dict:
    catalog, catalog_path = _load_catalog(indication, catalog_repo)
    if catalog is None:
        raise FileNotFoundError(f"no subgroup catalog for {indication} under {catalog_repo}")

    current_pin = _sha256_file(catalog_path)
    products = _emitted_products(indication, products_root)

    # Index emitted counts: (data_source, stratum_id) -> (n_samples, pin_fresh)
    emitted: dict[tuple[str, str], tuple[int, bool]] = {}
    for m in products:
        src = m["data_source"]
        pin_fresh = m.get("subgroup_catalog_content_pin") == current_pin
        for row in m.get("strata_summary", []) or []:
            emitted[(src, row["subgroup_id"])] = (row["n_samples"], pin_fresh)

    # All data sources referenced by any stratum or any emitted product.
    all_sources = sorted(
        {ds for s in catalog.get("atomic_strata", []) or [] for ds in (s.get("applicable_data_sources") or [])}
        | {m["data_source"] for m in products}
    )

    rows = []
    for stratum in catalog.get("atomic_strata", []) or []:
        sid = stratum["id"]
        applicable = set(stratum.get("applicable_data_sources") or [])
        for src in all_sources:
            if src not in applicable:
                status = "out_of_scope"
                n = None
            elif (src, sid) in emitted:
                n, pin_fresh = emitted[(src, sid)]
                status = _cell_status(n, pin_fresh)
            else:
                status = "data_blocked"
                n = None
            rows.append({
                "stratum": sid, "data_source": src, "status": status,
                "n_samples": n, "subtype_defining_data": stratum.get("subtype_defining_data"),
            })

    return {
        "indication": indication,
        "catalog_ref": catalog["id"],
        "catalog_content_pin": current_pin,
        "subgroup_n_floor": SUBGROUP_N_FLOOR,
        "n_products_found": len(products),
        "cells": rows,
    }


def _write_matrix(matrix: dict) -> Path:
    COVERAGE_DIR.mkdir(parents=True, exist_ok=True)
    out = COVERAGE_DIR / f"{matrix['indication']}.coverage.yaml"
    out.write_text(yaml.safe_dump(matrix, sort_keys=False))
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build/check the subgroup coverage matrix.")
    parser.add_argument("--indication", help="single indication (e.g. COADREAD)")
    parser.add_argument("--all", action="store_true", help="every catalog under the catalog repo")
    parser.add_argument("--catalog-repo", type=Path, default=DEFAULT_CATALOG_REPO)
    parser.add_argument("--products-root", type=Path, default=DEFAULT_PRODUCTS_ROOT)
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed matrix differs from freshly computed")
    args = parser.parse_args(argv)

    if args.all:
        cat_root = args.catalog_repo / "subgroup-catalogs"
        indications = sorted(d.name for d in cat_root.iterdir() if d.is_dir()) if cat_root.exists() else []
    elif args.indication:
        indications = [args.indication]
    else:
        parser.error("pass --indication or --all")

    rc = 0
    for ind in indications:
        try:
            matrix = build_matrix(ind, args.catalog_repo, args.products_root)
        except FileNotFoundError as e:
            print(f"  SKIP {ind}: {e}", file=sys.stderr)
            continue
        out_path = COVERAGE_DIR / f"{ind}.coverage.yaml"
        fresh = yaml.safe_dump(matrix, sort_keys=False)
        if args.check:
            if not out_path.exists():
                print(f"  MISSING {out_path.name} — run without --check to generate.", file=sys.stderr)
                rc = 1
            elif out_path.read_text() != fresh:
                print(f"  STALE {out_path.name} — committed matrix differs from computed; regenerate.", file=sys.stderr)
                rc = 1
            else:
                print(f"  OK {out_path.name}")
        else:
            _write_matrix(matrix)
            summary = {}
            for c in matrix["cells"]:
                summary[c["status"]] = summary.get(c["status"], 0) + 1
            print(f"  wrote {out_path.name}: {summary}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
