"""subgroup_assignment.schema.json tests.

Covers the schema contract for per-sample subgroup-assignment product manifests,
plus the 2026-07-16 spine additions:
- data_source enum extended with genie + genie_bpc (the LOT work landed genie_bpc;
  GENIE-registry MAF strata are genie).
- subgroup_catalog_content_pin: optional SHA-256 of the resolved catalog, so an
  assignments product derived against a since-mutated catalog is detectable
  (release_pin labels are edited in place — see COADREAD/2026-Q2's 5 in-place edits).
"""

import json
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO / "schemas" / "subgroup_assignment.schema.json").read_text())


def _valid_manifest(**overrides):
    """A minimal schema-valid subgroup_assignment_product manifest."""
    m = {
        "manifest_kind": "subgroup_assignment_product",
        "assignment_product_id": "subgroup-assignments-coadread-tcga-2026-q2",
        "indication": "COADREAD",
        "data_source": "tcga",
        "release_pin": "2026-Q2",
        "subgroup_catalog_ref": "coadread-subgroups-2026-q2",
        "assigner_method": "subgroup_assigner_directly_tagged",
        "parquet_s3_uri": "s3://onc-compbio/data-catalog/derived/subgroup-assignments/COADREAD/tcga/2026-Q2/assignments.parquet",
        "parquet_schema": {
            "columns": [
                {"name": "sample_id", "type": "string"},
                {"name": "patient_id", "type": "string", "nullable": True},
                {"name": "stratum_id", "type": "string"},
                {"name": "is_member", "type": "bool", "nullable": True},
                {"name": "derivation_value", "type": "string"},
            ]
        },
        "n_samples_total": 276,
        "strata_summary": [
            {"subgroup_id": "MSI_H", "n_samples": 38, "derivation_source": "directly_tagged_clinical"},
            {"subgroup_id": "MSS", "n_samples": 193, "derivation_source": "directly_tagged_clinical"},
        ],
        "generated_at": "2026-07-16T16:00:00Z",
        "generated_by": "methods/subgroup_assigner_directly_tagged@abc1234",
        "schema_version": 1,
    }
    m.update(overrides)
    return m


def test_valid_manifest_passes():
    jsonschema.validate(instance=_valid_manifest(), schema=SCHEMA)


def test_wrong_manifest_kind_rejected():
    """The old emitted kind 'subgroup_assignment' (singular product) is invalid."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_valid_manifest(manifest_kind="subgroup_assignment"), schema=SCHEMA)


@pytest.mark.parametrize("source", ["tcga", "depmap", "ccle", "gdsc", "genie", "genie_bpc"])
def test_data_source_enum_includes_genie(source):
    """genie + genie_bpc are valid data sources (spine addition 2026-07-16)."""
    jsonschema.validate(instance=_valid_manifest(data_source=source), schema=SCHEMA)


def test_unknown_data_source_rejected():
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_valid_manifest(data_source="tempus"), schema=SCHEMA)


def test_content_pin_optional():
    """subgroup_catalog_content_pin is optional — a manifest without it still validates."""
    m = _valid_manifest()
    assert "subgroup_catalog_content_pin" not in m
    jsonschema.validate(instance=m, schema=SCHEMA)


def test_content_pin_valid_sha256():
    jsonschema.validate(
        instance=_valid_manifest(subgroup_catalog_content_pin="a" * 64),
        schema=SCHEMA,
    )


@pytest.mark.parametrize("bad", ["deadbeef", "A" * 64, "g" * 64, "a" * 63, "a" * 65])
def test_content_pin_rejects_non_sha256(bad):
    """Non-64-hex values (too short, uppercase, non-hex, wrong length) are rejected."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance=_valid_manifest(subgroup_catalog_content_pin=bad),
            schema=SCHEMA,
        )


def test_generated_by_provenance_pattern():
    """generated_by must be methods/<name>@<sha> — the emit path must supply real provenance."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_valid_manifest(generated_by="somebody"), schema=SCHEMA)


def test_parquet_schema_requires_five_columns():
    m = _valid_manifest()
    m["parquet_schema"]["columns"] = m["parquet_schema"]["columns"][:4]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=m, schema=SCHEMA)


def test_unevaluated_properties_rejected():
    """unevaluatedProperties:false — a stray top-level key is rejected."""
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=_valid_manifest(surprise="x"), schema=SCHEMA)
