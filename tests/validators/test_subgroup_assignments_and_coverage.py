"""Tests for the subgroup-assignment validator + coverage-matrix generator.

Uses synthetic catalogs + manifests in tmp dirs (no dependence on the real
data-catalog repo or emitted products), so the tests are hermetic and CI-safe.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "validators" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


V = _load("validate_subgroup_assignments")
CM = _load("build_subgroup_coverage_matrix")


# ---------- fixtures ----------

def _catalog(tmp: Path, indication="COADREAD") -> Path:
    ind_dir = tmp / "subgroup-catalogs" / indication
    ind_dir.mkdir(parents=True)
    cat = {
        "id": "coadread-subgroups-2026-q2",
        "indication": indication,
        "version": "2026-Q2",
        "atomic_strata": [
            {"id": "MSI_H", "applicable_data_sources": ["tcga", "depmap"],
             "expected_n_tcga_coadread": 40, "subtype_defining_data": "genomic"},
            {"id": "MSS", "applicable_data_sources": ["tcga", "depmap"],
             "expected_n_tcga_coadread": 200},
            {"id": "KRAS_G12C", "applicable_data_sources": ["tcga"],
             "expected_n_tcga_coadread": 20},
            {"id": "right_sided", "applicable_data_sources": ["tcga"]},
        ],
    }
    p = ind_dir / "2026-Q2.yaml"
    p.write_text(yaml.safe_dump(cat))
    return p


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _manifest(tmp: Path, catalog_path: Path, pin: str | None = None, strata=None,
              data_source="tcga") -> Path:
    """A schema-valid-ish manifest (the validator loads the real schema)."""
    strata = strata or [
        {"subgroup_id": "MSI_H", "n_samples": 38, "derivation_source": "directly_tagged_clinical"},
        {"subgroup_id": "MSS", "n_samples": 193, "derivation_source": "directly_tagged_clinical"},
        {"subgroup_id": "KRAS_G12C", "n_samples": 8, "derivation_source": "directly_tagged_clinical"},
    ]
    m = {
        "manifest_kind": "subgroup_assignment_product",
        "assignment_product_id": f"subgroup-assignments-coadread-{data_source}-2026-q2",
        "indication": "COADREAD",
        "data_source": data_source,
        "release_pin": "2026-Q2",
        "subgroup_catalog_ref": "coadread-subgroups-2026-q2",
        "subgroup_catalog_content_pin": pin if pin is not None else _sha(catalog_path),
        "assigner_method": "subgroup_assigner_directly_tagged",
        "parquet_s3_uri": "s3://onc-compbio/data-catalog/derived/subgroup-assignments/COADREAD/tcga/2026-Q2/assignments.parquet",
        "parquet_schema": {"columns": [
            {"name": "sample_id", "type": "string"},
            {"name": "patient_id", "type": "string", "nullable": True},
            {"name": "stratum_id", "type": "string"},
            {"name": "is_member", "type": "bool", "nullable": True},
            {"name": "derivation_value", "type": "string"},
        ]},
        "n_samples_total": 276,
        "strata_summary": strata,
        "generated_at": "2026-07-16T16:00:00Z",
        "generated_by": "methods/subgroup_assigner_directly_tagged@abc1234",
        "schema_version": 1,
    }
    d = tmp / "products" / f"{data_source}-x" ; d.mkdir(parents=True)
    p = d / "manifest.yaml"
    p.write_text(yaml.safe_dump(m))
    return p


# ---------- validator ----------

def test_valid_fresh_manifest_ok(tmp_path):
    cat = _catalog(tmp_path)
    mani = _manifest(tmp_path, cat)  # pin = current catalog hash
    r = V.validate_manifest_file(mani, catalog_repo=tmp_path)
    assert r.ok
    assert not any("STALE" in e for e in r.errors)


def test_stale_content_pin_is_error(tmp_path):
    cat = _catalog(tmp_path)
    mani = _manifest(tmp_path, cat, pin="0" * 64)  # deliberately wrong pin
    r = V.validate_manifest_file(mani, catalog_repo=tmp_path)
    assert not r.ok
    assert any("STALE" in e for e in r.errors)


def test_edit_catalog_makes_manifest_stale(tmp_path):
    cat = _catalog(tmp_path)
    mani = _manifest(tmp_path, cat)      # pin matches
    assert V.validate_manifest_file(mani, catalog_repo=tmp_path).ok
    cat.write_text(cat.read_text() + "\n# in-place edit\n")  # 6th-edit scenario
    r = V.validate_manifest_file(mani, catalog_repo=tmp_path)
    assert not r.ok and any("STALE" in e for e in r.errors)


def test_unknown_stratum_is_error(tmp_path):
    cat = _catalog(tmp_path)
    mani = _manifest(tmp_path, cat, strata=[
        {"subgroup_id": "NOT_IN_CATALOG", "n_samples": 10, "derivation_source": "directly_tagged_clinical"},
    ])
    r = V.validate_manifest_file(mani, catalog_repo=tmp_path)
    assert not r.ok
    assert any("not an atomic_stratum" in e for e in r.errors)


def test_expected_n_divergence_warns(tmp_path):
    cat = _catalog(tmp_path)
    # MSS emitted n=193 vs expected 200 → within tolerance (ok); KRAS_G12C n=8 vs 20 → warn
    mani = _manifest(tmp_path, cat)
    r = V.validate_manifest_file(mani, catalog_repo=tmp_path)
    assert r.ok  # divergence is a warning, not an error
    assert any("KRAS_G12C" in w for w in r.warnings)


def test_missing_catalog_warns_not_errors(tmp_path):
    cat = _catalog(tmp_path)
    mani = _manifest(tmp_path, cat)
    r = V.validate_manifest_file(mani, catalog_repo=tmp_path / "nonexistent")
    assert r.ok  # structural pass; cross-checks skipped with a warning
    assert any("not found" in w for w in r.warnings)


# ---------- coverage matrix ----------

def test_matrix_status_vocabulary(tmp_path):
    cat = _catalog(tmp_path)
    _manifest(tmp_path, cat)  # tcga product covering MSI_H/MSS/KRAS_G12C
    matrix = CM.build_matrix("COADREAD", catalog_repo=tmp_path, products_root=tmp_path / "products")
    by = {(c["stratum"], c["data_source"]): c["status"] for c in matrix["cells"]}
    # live: MSI_H/tcga (n=38 >= 30)
    assert by[("MSI_H", "tcga")] == "live"
    # below_floor: KRAS_G12C/tcga (n=8 < 30)
    assert by[("KRAS_G12C", "tcga")] == "below_floor"
    # data_blocked: MSI_H/depmap (applicable, but no depmap product emitted)
    assert by[("MSI_H", "depmap")] == "data_blocked"
    # out_of_scope: KRAS_G12C/depmap (not in its applicable_data_sources)
    assert by[("KRAS_G12C", "depmap")] == "out_of_scope"


def test_matrix_marks_stale_on_catalog_edit(tmp_path):
    cat = _catalog(tmp_path)
    _manifest(tmp_path, cat)
    cat.write_text(cat.read_text() + "\n# edit\n")  # product pin now stale
    matrix = CM.build_matrix("COADREAD", catalog_repo=tmp_path, products_root=tmp_path / "products")
    statuses = {c["status"] for c in matrix["cells"] if c["data_source"] == "tcga" and c["stratum"] == "MSI_H"}
    assert statuses == {"stale"}


def test_matrix_content_pin_recorded(tmp_path):
    cat = _catalog(tmp_path)
    matrix = CM.build_matrix("COADREAD", catalog_repo=tmp_path, products_root=tmp_path / "empty")
    assert matrix["catalog_content_pin"] == _sha(cat)
    # with no products, all applicable cells are data_blocked
    assert all(c["status"] in ("data_blocked", "out_of_scope") for c in matrix["cells"])
