"""RP6 — canonical TARGET_LEVEL sentinel for target-level products.

`evidence.schema.json`'s `indication` field previously accepted any uppercase
token matching `^[A-Z][A-Z0-9_]*$`. Target-level products (indication_scope=
target_level) have no real indication, so each batch job independently invented
a placeholder (TARGET / ALL / GENE) — cross-product joins silently returned
empty when two products disagreed.

Fix: `indication` is now a `oneOf` — either a real OncoTree code (excluding the
sentinel) OR the reserved `TARGET_LEVEL` const. These tests pin:
  1. a real OncoTree code still validates;
  2. TARGET_LEVEL validates;
  3. the old ad-hoc placeholders (TARGET, ALL, GENE) that HAPPEN to match the
     OncoTree pattern still validate as codes (schema cannot reject them by
     pattern) — but every products.yaml target_level product declares
     indication_sentinel: TARGET_LEVEL, which is the enforcement point;
  4. every products.yaml product with indication_scope=target_level declares
     indication_sentinel: TARGET_LEVEL (and no other value).
"""

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
EVIDENCE_SCHEMA = json.loads((REPO / "schemas" / "evidence.schema.json").read_text())
PRODUCTS = yaml.safe_load((REPO / "vocabularies" / "products.yaml").read_text())


def _base_artifact(indication: str) -> dict:
    """Minimal valid evidence.json with the given indication."""
    return {
        "gene": "SCD1",
        "indication": indication,
        "subtype": "all",
        "dimension": "target-biology",
        "computed_date": "2026-08-04",
        "provenance": {
            "source": "uniprot-sprot-human-2026-02-snapshot-2026-06-18",
            "method": "uniprot_xml_extract",
            "git_commit": "abc1234",
            "catalog_refs": ["some-manifest-v1"],
        },
        "result": {"family": "RTK"},
        "summary": "Target-level annotation for SCD1.",
        "confidence": "MODERATE",
        "label": "exploratory",
    }


# ---------- indication field: oneOf(OncoTree code | TARGET_LEVEL) ----------


def _indication_subschema() -> dict:
    """Isolate the indication property subschema for focused validation."""
    return EVIDENCE_SCHEMA["properties"]["indication"]


@pytest.mark.parametrize("code", ["COADREAD", "LUAD", "NSCLC", "PAAD", "STAD"])
def test_real_oncotree_code_validates(code):
    """A canonical OncoTree code validates against the indication subschema."""
    jsonschema.validate(instance=code, schema=_indication_subschema())


def test_target_level_sentinel_validates():
    """The reserved TARGET_LEVEL sentinel validates."""
    jsonschema.validate(instance="TARGET_LEVEL", schema=_indication_subschema())


def test_indication_is_oneof_not_bare_pattern():
    """RP6 regression: indication must be a oneOf (code | sentinel), not bare pattern.

    Before the fix, indication was `{type: string, pattern: ...}`. If someone
    reverts to that, this test fails — the sentinel arm is the whole point.
    """
    sub = _indication_subschema()
    assert "oneOf" in sub, "indication must use oneOf(OncoTree code | TARGET_LEVEL)"
    consts = [branch.get("const") for branch in sub["oneOf"] if "const" in branch]
    assert "TARGET_LEVEL" in consts, "TARGET_LEVEL must be a reserved const branch in the indication oneOf"


def test_target_level_not_ambiguous_against_pattern_branch():
    """TARGET_LEVEL must match EXACTLY one oneOf branch (the const), not both.

    The pattern branch carries `not: {const: TARGET_LEVEL}` so the sentinel is
    excluded from the OncoTree-code arm — otherwise oneOf's exactly-one rule
    would reject TARGET_LEVEL for matching two branches.
    """
    # This validates only if oneOf's "exactly one" constraint is satisfiable.
    jsonschema.validate(instance="TARGET_LEVEL", schema=_indication_subschema())
    # And a plain code matches only the pattern branch.
    jsonschema.validate(instance="LUAD", schema=_indication_subschema())


def test_full_artifact_with_target_level_validates():
    """A complete evidence artifact using TARGET_LEVEL validates end-to-end."""
    jsonschema.validate(instance=_base_artifact("TARGET_LEVEL"), schema=EVIDENCE_SCHEMA)


def test_full_artifact_with_oncotree_code_validates():
    """A complete evidence artifact using a real code validates end-to-end."""
    jsonschema.validate(instance=_base_artifact("LUAD"), schema=EVIDENCE_SCHEMA)


# ---------- products.yaml: every target_level product declares the sentinel ----------


def _target_level_products() -> list[dict]:
    return [p for p in PRODUCTS["products"] if p.get("indication_scope") == "target_level"]


def test_target_level_products_exist():
    """Sanity: the 5 known target-level products are present."""
    ids = {p["id"] for p in _target_level_products()}
    expected = {
        "target-biology-uniprot",
        "target-biology-coordinates",
        "target-biology-paralog-landscape",
        "safety-hpa-normal-tissue",
        "safety-gnomad-constraint",
    }
    assert expected.issubset(ids), f"Missing target-level products: {expected - ids}"


def test_every_target_level_product_declares_sentinel():
    """RP6 enforcement: every indication_scope=target_level product must declare
    indication_sentinel: TARGET_LEVEL. This is the CI gate that stops a new
    target-level product from silently inventing its own placeholder."""
    offenders = [p["id"] for p in _target_level_products() if p.get("indication_sentinel") != "TARGET_LEVEL"]
    assert not offenders, f"target_level products missing indication_sentinel: TARGET_LEVEL: {offenders}"


def test_no_indication_scoped_product_declares_sentinel():
    """Inverse guard: only target_level products carry indication_sentinel.

    An indication-scoped product declaring the sentinel would be a modeling
    error (it has a real indication)."""
    offenders = [
        p["id"]
        for p in PRODUCTS["products"]
        if p.get("indication_scope") != "target_level" and "indication_sentinel" in p
    ]
    assert not offenders, f"non-target_level products must NOT declare indication_sentinel: {offenders}"
