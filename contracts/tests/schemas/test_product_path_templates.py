"""Finding C — every product declares core_artifact_path_template.

The evidence.json location for each product must be derivable from the registry
(products.yaml), not hard-coded in orchestrators. Before this fix only the 4
expression-rna products declared core_artifact_path_template; the other 21 fell
back to hard-coded paths.

These tests pin: (1) every product declares the template; (2) the template uses
the canonical core-artifacts layout and the RP6 sentinels (TARGET_LEVEL for
target_level scope, PAN_CANCER for pan_cancer scope). s3_path_template (derived
parquet location) is intentionally NOT backfilled here — those are per-pipeline
and set when each pipeline is authored.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PRODUCTS = yaml.safe_load((REPO / "vocabularies" / "products.yaml").read_text())["products"]


def test_every_product_declares_core_artifact_path_template():
    missing = [p["id"] for p in PRODUCTS if "core_artifact_path_template" not in p]
    assert not missing, f"products missing core_artifact_path_template: {missing}"


def test_template_uses_core_artifacts_prefix():
    for p in PRODUCTS:
        t = p["core_artifact_path_template"]
        assert t.startswith("s3://onc-compbio/core-artifacts/"), f"{p['id']}: unexpected prefix {t!r}"
        assert t.endswith(".evidence.json"), f"{p['id']}: must end .evidence.json ({t!r})"
        assert "{gene}" in t, f"{p['id']}: template must include {{gene}} token ({t!r})"


def test_target_level_products_use_TARGET_LEVEL_sentinel():
    """RP6 alignment: target_level products path under TARGET_LEVEL, subtype 'all'."""
    for p in PRODUCTS:
        if p.get("indication_scope") == "target_level":
            t = p["core_artifact_path_template"]
            assert "/TARGET_LEVEL/all/" in t, (
                f"{p['id']}: target_level product must path under /TARGET_LEVEL/all/ ({t!r})"
            )


def test_pan_cancer_products_use_PAN_CANCER_sentinel():
    for p in PRODUCTS:
        if p.get("indication_scope") == "pan_cancer":
            t = p["core_artifact_path_template"]
            assert "/PAN_CANCER/all/" in t, f"{p['id']}: pan_cancer product must path under /PAN_CANCER/all/ ({t!r})"


def test_indication_scoped_products_use_INDICATION_token():
    """single_indication / *_with_subgroups / lineage_mapped keep the {INDICATION} token."""
    scoped = {"single_indication", "single_indication_with_subgroups", "lineage_mapped"}
    for p in PRODUCTS:
        if p.get("indication_scope") in scoped:
            t = p["core_artifact_path_template"]
            assert "{INDICATION}" in t, f"{p['id']}: indication-scoped product must keep {{INDICATION}} token ({t!r})"


def test_dimension_appears_in_template_path():
    """The dimension segment must match the product's declared dimension."""
    for p in PRODUCTS:
        t = p["core_artifact_path_template"]
        assert f"/{p['dimension']}/" in t, f"{p['id']}: dimension {p['dimension']!r} not in path ({t!r})"
