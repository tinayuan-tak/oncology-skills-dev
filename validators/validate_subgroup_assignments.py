#!/usr/bin/env python3
"""
validate_subgroup_assignments.py — subgroup_assignment_product manifest validator.

Two layers, mirroring validate_cards.py:
  (1) Structural — the manifest YAML must validate against
      schemas/subgroup_assignment.schema.json.
  (2) Cross-reference — checks JSON Schema cannot perform:
      (a) CONTENT-PIN STALENESS. The manifest's subgroup_catalog_content_pin is the
          sha256 of the resolved catalog at generation time. Re-hash the CURRENT
          catalog file; if it differs, the assignments product was derived against a
          since-mutated catalog (release_pin labels are edited in place — see
          COADREAD/2026-Q2's growth 6→18 strata) and is STALE → needs re-emit.
      (b) STRATA-COUNT vs. CATALOG. Every subgroup_id in strata_summary must be an
          atomic_stratum in the referenced catalog; and where the catalog declares an
          expected_n_* for the product's data_source, warn if the emitted count
          diverges beyond tolerance (catches silent join losses / wrong-lineage shards).

The catalog lives in the data-catalog repo; pass --catalog-repo (default: the standard
SageMaker sibling path). A manifest whose catalog can't be located gets a WARNING for
the cross-checks (structural validation still runs) rather than a hard error.

Usage:
  python validate_subgroup_assignments.py <manifest.yaml | dir>
  python validate_subgroup_assignments.py <dir> --catalog-repo /path/to/data-catalog

  from validate_subgroup_assignments import validate_manifest_file, ValidationReport
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schemas" / "subgroup_assignment.schema.json"
DEFAULT_CATALOG_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")

# data_source → catalog expected_n_* field suffix. The COADREAD catalog carries
# expected_n_tcga_coadread etc.; DepMap uses expected_n_depmap. Divergence beyond
# this fraction of the expected count raises a WARNING (not an error — real cohorts
# drift from literature estimates; a 0-vs-expected or order-of-magnitude gap is the
# signal we want).
_EXPECTED_N_TOLERANCE = 0.5


@dataclass
class ValidationReport:
    manifest_path: str
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text())


def _find_catalog(catalog_ref: str, indication: str, catalog_repo: Path) -> Path | None:
    """Locate the subgroup-catalog file for a catalog ref. Catalogs live at
    data-catalog/subgroup-catalogs/{INDICATION}/{quarter}.yaml; the ref encodes the
    quarter (e.g. coadread-subgroups-2026-q2 → 2026-Q2.yaml)."""
    ind_dir = catalog_repo / "subgroup-catalogs" / indication
    if not ind_dir.exists():
        return None
    for f in sorted(ind_dir.glob("*.yaml")):
        cat = yaml.safe_load(f.read_text())
        if cat.get("id") == catalog_ref:
            return f
    return None


def _check_content_pin(manifest: dict, catalog_path: Path, report: ValidationReport) -> None:
    stored = manifest.get("subgroup_catalog_content_pin")
    if not stored:
        report.add_warning(
            "no subgroup_catalog_content_pin — staleness cannot be verified. "
            "Re-emit with a current assigner to stamp the catalog hash."
        )
        return
    current = _sha256_file(catalog_path)
    if stored != current:
        report.add_error(
            f"STALE: subgroup_catalog_content_pin {stored[:12]}… does not match the "
            f"current catalog hash {current[:12]}… ({catalog_path.name}). The catalog "
            f"was edited in place after this product was emitted; re-run the assigner."
        )


def _check_strata_vs_catalog(manifest: dict, catalog: dict, report: ValidationReport) -> None:
    atomic = {s["id"]: s for s in catalog.get("atomic_strata", []) or []}
    data_source = manifest.get("data_source", "")
    indication = manifest.get("indication", "").lower()
    # expected_n field candidates, most-specific first.
    exp_fields = [f"expected_n_{data_source}_{indication}", f"expected_n_{data_source}"]

    for row in manifest.get("strata_summary", []) or []:
        sid = row["subgroup_id"]
        if sid not in atomic:
            report.add_error(
                f"strata_summary references '{sid}' which is not an atomic_stratum in "
                f"catalog {catalog.get('id')}."
            )
            continue
        stratum = atomic[sid]
        expected = next((stratum[f] for f in exp_fields if f in stratum), None)
        if expected is None or expected == 0:
            continue  # no literature estimate for this source, or genuinely-zero
        got = row["n_samples"]
        if got == 0 or abs(got - expected) > _EXPECTED_N_TOLERANCE * expected:
            report.add_warning(
                f"stratum '{sid}': emitted n={got} diverges >{int(_EXPECTED_N_TOLERANCE*100)}% "
                f"from catalog {exp_fields[0]}={expected}. Possible join loss, wrong-lineage "
                f"shard, or stale catalog estimate — verify."
            )


def validate_manifest_file(
    path: str | Path, catalog_repo: Path | None = None, schema: dict | None = None
) -> ValidationReport:
    path = Path(path)
    report = ValidationReport(manifest_path=str(path))
    schema = schema or _load_schema()
    catalog_repo = catalog_repo or DEFAULT_CATALOG_REPO

    try:
        manifest = yaml.safe_load(path.read_text())
    except Exception as e:  # noqa: BLE001
        report.add_error(f"could not parse YAML: {e}")
        return report

    # (1) Structural
    for err in Draft202012Validator(schema).iter_errors(manifest):
        loc = "/".join(str(x) for x in err.absolute_path) or "(root)"
        report.add_error(f"schema: {loc}: {err.message}")
    if not report.ok:
        return report  # cross-checks assume a well-formed manifest

    # (2) Cross-reference
    catalog_path = _find_catalog(
        manifest["subgroup_catalog_ref"], manifest["indication"], catalog_repo
    )
    if catalog_path is None:
        report.add_warning(
            f"catalog '{manifest['subgroup_catalog_ref']}' not found under "
            f"{catalog_repo}/subgroup-catalogs/{manifest['indication']}/ — content-pin "
            f"staleness + strata-count cross-checks skipped."
        )
        return report

    catalog = yaml.safe_load(catalog_path.read_text())
    _check_content_pin(manifest, catalog_path, report)
    _check_strata_vs_catalog(manifest, catalog, report)
    return report


def validate_directory(root: str | Path, catalog_repo: Path | None = None) -> list[ValidationReport]:
    root = Path(root)
    schema = _load_schema()
    return [
        validate_manifest_file(p, catalog_repo=catalog_repo, schema=schema)
        for p in sorted(root.rglob("manifest.yaml"))
    ]


def _format_report(r: ValidationReport) -> str:
    status = "OK" if r.ok and not r.warnings else ("WARN" if r.ok else "FAIL")
    lines = [f"  [{status}] {r.manifest_path}"]
    lines += [f"      ERROR: {e}" for e in r.errors]
    lines += [f"      warn:  {w}" for w in r.warnings]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate subgroup_assignment_product manifests.")
    parser.add_argument("path", help="manifest.yaml or a directory to walk")
    parser.add_argument("--catalog-repo", type=Path, default=DEFAULT_CATALOG_REPO)
    parser.add_argument("--strict-warnings", action="store_true")
    args = parser.parse_args(argv)

    target = Path(args.path)
    if target.is_dir():
        reports = validate_directory(target, catalog_repo=args.catalog_repo)
    else:
        reports = [validate_manifest_file(target, catalog_repo=args.catalog_repo)]

    print("validate_subgroup_assignments.py results:")
    for r in reports:
        print(_format_report(r))
    n_err = sum(1 for r in reports if not r.ok)
    n_warn = sum(1 for r in reports if r.warnings)
    print(f"\nSummary: {len(reports)} manifest(s); {n_err} with errors, {n_warn} with warnings.")

    if n_err:
        return 1
    if args.strict_warnings and n_warn:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
