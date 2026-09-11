"""The two Analysis-Products registries must not disagree (2026-09-11).

`products.yaml` exists TWICE: here at `vocabularies/products.yaml`, and in the
data-catalog at `core-artifacts-schema/products.yaml`. Both copies are live and
each has its own consumers:

  contracts copy  validators/validate_cards.py (product_id referential integrity),
                  tests/schemas/{test_product_path_templates,test_indication_sentinel,
                  test_result_schema_constraints}.py, and analysis-methods'
                  methods/catalog_query/read.py (manifest -> product reverse index,
                  which also feeds the release-resolution digest)
  catalog copy    data-catalog scripts/validate_catalog.py, which REJECTS a derived
                  manifest whose `product_id:` is not registered there

They were split by DC #55 ("migrate core-artifacts-schema into data-catalog") and
then edited independently in opposite directions: TC #141 backfilled
`core_artifact_path_template` here only, DC #67 registered `depmap-predictability`
there only. Nothing noticed, because no check spanned the two files.

These tests pin the two invariants that actually matter, deliberately NOT equality:

  1. every catalog-registered product id exists here. This is the direction that
     bites — the catalog copy gates what a derived manifest may declare, so an id
     registered only there names a product this repo's validator cannot resolve.
     The reverse is legitimate: a planned product may live here with no catalog
     data yet, and forcing a catalog registration for a product that has no
     manifests would be backwards.
  2. no shared-key value drift. The catalog copy is a strict FIELD-subset of this
     one (it carries no core_artifact_path_template / requires_subgroup /
     indication_sentinel), so comparing only the keys both copies declare is the
     honest comparison — and it catches a `status:` or `sources:` edit applied to
     one copy and not the other, which is the failure mode that would otherwise
     be invisible until a pipeline read the wrong registry.

GRACEFUL-SKIP when the data-catalog sibling is absent, mirroring
validate_cards.py's `_DATA_CATALOG_REPO` pattern: a checkout-only CI runner has no
sibling, and a test that false-fails there teaches people to ignore it. The real
fix for that blind spot is cross-repo CI (TC #712); until then this at least fails
loudly in every working tree and in any runner that does check out both.
"""

import os
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CONTRACTS_REGISTRY = REPO / "vocabularies" / "products.yaml"
DATA_CATALOG_REPO = Path(
    os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
)
CATALOG_REGISTRY = DATA_CATALOG_REPO / "core-artifacts-schema" / "products.yaml"


def _by_id(path: Path) -> dict:
    return {p["id"]: p for p in yaml.safe_load(path.read_text())["products"]}


@pytest.fixture(scope="module")
def registries():
    if not CATALOG_REGISTRY.is_file():
        pytest.skip(f"data-catalog sibling absent ({CATALOG_REGISTRY}) — cannot compare registries")
    return _by_id(CONTRACTS_REGISTRY), _by_id(CATALOG_REGISTRY)


def test_every_catalog_registered_product_exists_here(registries):
    contracts, catalog = registries
    missing = sorted(set(catalog) - set(contracts))
    assert not missing, (
        f"registered in data-catalog's core-artifacts-schema/products.yaml but not in "
        f"vocabularies/products.yaml: {missing}. A derived manifest may declare these "
        f"product_ids and pass catalog CI, while this repo's validator cannot resolve them."
    )


def test_no_shared_key_value_drift(registries):
    contracts, catalog = registries
    drift = []
    for pid in sorted(set(contracts) & set(catalog)):
        here, there = contracts[pid], catalog[pid]
        for field in sorted(set(here) & set(there)):
            if here[field] != there[field]:
                drift.append(f"{pid}.{field}: contracts={here[field]!r} catalog={there[field]!r}")
    assert not drift, "the two products registries disagree on fields both declare:\n  " + "\n  ".join(drift)
