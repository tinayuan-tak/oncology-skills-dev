"""Tests for subgroup_common.manifest — the shared schema-valid emitter.

Validates the emitted manifest against the actual target-contracts schema when
that repo is present; otherwise falls back to structural assertions so the test
is meaningful in isolation. Covers the product-id shape, content-pin, per-stratum
strata_summary, variant discrimination, and the assigner-method enum mapping.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from methods.subgroup_common import manifest as M

_SCHEMA_PATH = Path(
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
    "/schemas/subgroup_assignment.schema.json"
)


def _assignments():
    """A tall (sample, stratum, is_member) frame like the assigners emit."""
    rows = []
    for i in range(40):
        sid = f"TCGA-XX-{i:04d}"
        rows.append({"sample_id": sid, "patient_id": sid, "source_native_id": sid,
                     "stratum_id": "MSI_H", "is_member": i < 12,
                     "derivation_source": "directly_tagged_clinical",
                     "derivation_value": "MSI-H" if i < 12 else "",
                     "evaluated_at_release": "2026-Q2"})
        rows.append({"sample_id": sid, "patient_id": sid, "source_native_id": sid,
                     "stratum_id": "MSS", "is_member": i >= 12,
                     "derivation_source": "directly_tagged_clinical",
                     "derivation_value": "MSS" if i >= 12 else "",
                     "evaluated_at_release": "2026-Q2"})
    return pd.DataFrame(rows)


def _catalog(tmp_path) -> tuple[dict, Path]:
    cat = {
        "id": "coadread-subgroups-2026-q2",
        "indication": "COADREAD",
        "version": "2026-Q2",
        "atomic_strata": [
            {"id": "MSI_H", "derivation_source": "directly_tagged_clinical"},
            {"id": "MSS", "derivation_source": "directly_tagged_clinical"},
        ],
    }
    p = tmp_path / "catalog.yaml"
    p.write_text(yaml.safe_dump(cat))
    return cat, p


def test_emitted_manifest_shape(tmp_path):
    cat, cat_path = _catalog(tmp_path)
    out = tmp_path / "out"; out.mkdir()
    _assignments().to_parquet(out / "assignments.parquet")
    mpath = M.emit_assignment_manifest(
        out_dir=out, catalog=cat, catalog_path=cat_path,
        data_source="tcga", release_pin="2026-Q2",
        assignments=_assignments(),
        assigner_method="subgroup_assigner_directly_tagged",
    )
    m = yaml.safe_load(mpath.read_text())
    assert m["manifest_kind"] == "subgroup_assignment_product"
    assert m["assignment_product_id"] == "subgroup-assignments-coadread-tcga-2026-q2"
    assert m["data_source"] == "tcga"
    assert m["subgroup_catalog_ref"] == "coadread-subgroups-2026-q2"
    # content-pin is a 64-hex sha256 of the catalog file
    assert len(m["subgroup_catalog_content_pin"]) == 64
    assert m["subgroup_catalog_content_pin"] == M.sha256_file(cat_path)
    # generated_by provenance shape
    assert m["generated_by"].startswith("methods/subgroup_assigner_directly_tagged@")
    # strata_summary carries per-stratum member counts (is_member==True)
    by = {s["subgroup_id"]: s for s in m["strata_summary"]}
    assert by["MSI_H"]["n_samples"] == 12
    assert by["MSS"]["n_samples"] == 28
    assert by["MSI_H"]["derivation_source"] == "directly_tagged_clinical"
    # n_samples_total = distinct samples (each sample in both strata → 40)
    assert m["n_samples_total"] == 40
    # >=5 typed columns
    assert len(m["parquet_schema"]["columns"]) >= 5


def test_variant_disambiguates_product_id(tmp_path):
    cat, cat_path = _catalog(tmp_path)
    out = tmp_path / "out"; out.mkdir()
    mpath = M.emit_assignment_manifest(
        out_dir=out, catalog=cat, catalog_path=cat_path,
        data_source="tcga", release_pin="2026-Q2",
        assignments=_assignments(),
        assigner_method="subgroup_assigner_maf_filter", variant="maf",
    )
    m = yaml.safe_load(mpath.read_text())
    assert m["assignment_product_id"] == "subgroup-assignments-coadread-tcga-maf-2026-q2"
    # the variant MUST also appear in the S3 path — otherwise the maf product
    # collides with the directly_tagged product at the same tcga key.
    assert "/tcga/maf/2026-Q2/" in m["parquet_s3_uri"]


def test_same_source_variants_do_not_collide_on_s3(tmp_path):
    """Two products sharing data_source (tcga directly_tagged + tcga maf) must
    land at DISTINCT S3 keys — the collision that would overwrite one on publish."""
    cat, cat_path = _catalog(tmp_path)
    out1 = tmp_path / "dt"; out1.mkdir()
    out2 = tmp_path / "maf"; out2.mkdir()
    dt = yaml.safe_load(M.emit_assignment_manifest(
        out_dir=out1, catalog=cat, catalog_path=cat_path, data_source="tcga",
        release_pin="2026-Q2", assignments=_assignments(),
        assigner_method="subgroup_assigner_directly_tagged").read_text())
    maf = yaml.safe_load(M.emit_assignment_manifest(
        out_dir=out2, catalog=cat, catalog_path=cat_path, data_source="tcga",
        release_pin="2026-Q2", assignments=_assignments(),
        assigner_method="subgroup_assigner_maf_filter", variant="maf").read_text())
    assert dt["parquet_s3_uri"] != maf["parquet_s3_uri"]
    # directly_tagged (no variant) stays at the base source path
    assert "/tcga/2026-Q2/" in dt["parquet_s3_uri"]
    assert "/tcga/maf/2026-Q2/" in maf["parquet_s3_uri"]


def test_classifier_method_enum_mapping(tmp_path):
    """Bare 'subgroup_assigner_classifier' maps to the schema enum '_classifier_run'."""
    cat, cat_path = _catalog(tmp_path)
    out = tmp_path / "out"; out.mkdir()
    mpath = M.emit_assignment_manifest(
        out_dir=out, catalog=cat, catalog_path=cat_path,
        data_source="depmap", release_pin="2026-Q3",
        assignments=_assignments(),
        assigner_method="subgroup_assigner_classifier", variant="classifier",
    )
    m = yaml.safe_load(mpath.read_text())
    assert m["assigner_method"] == "subgroup_assigner_classifier_run"


def test_content_pin_changes_with_catalog(tmp_path):
    """The whole point: editing the catalog flips the content-pin."""
    cat, cat_path = _catalog(tmp_path)
    pin1 = M.sha256_file(cat_path)
    cat_path.write_text(cat_path.read_text() + "\n# an in-place edit\n")
    pin2 = M.sha256_file(cat_path)
    assert pin1 != pin2


@pytest.mark.skipif(not _SCHEMA_PATH.exists(), reason="target-contracts schema not present")
def test_emitted_manifest_validates_against_schema(tmp_path):
    import jsonschema
    schema = json.loads(_SCHEMA_PATH.read_text())
    cat, cat_path = _catalog(tmp_path)
    out = tmp_path / "out"; out.mkdir()
    for method, variant, source in [
        ("subgroup_assigner_directly_tagged", None, "tcga"),
        ("subgroup_assigner_maf_filter", "maf", "genie"),
        ("subgroup_assigner_directly_tagged", None, "genie_bpc"),
        ("subgroup_assigner_classifier", "classifier", "depmap"),
    ]:
        mpath = M.emit_assignment_manifest(
            out_dir=out, catalog=cat, catalog_path=cat_path,
            data_source=source, release_pin="2026-Q2",
            assignments=_assignments(),
            assigner_method=method, variant=variant,
        )
        m = yaml.safe_load(mpath.read_text())
        jsonschema.validate(instance=m, schema=schema)  # raises on failure
