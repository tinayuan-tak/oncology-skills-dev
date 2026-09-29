"""The two Analysis-Products registries must not disagree (2026-09-11).

`products.yaml` exists TWICE: here at `vocabularies/products.yaml`, and in the
data-catalog at `core-artifacts-schema/products.yaml`. Both copies are live and
each has its own consumers:

  contracts copy  validators/validate_cards.py:45 (PRODUCTS_PATH) read in
                  _registered_product_ids() :995-1006, used at :1142 — an unknown
                  product_id is a WARNING (PRODUCT_ID_UNRESOLVED :1180), never an
                  error; tests/schemas/{test_product_path_templates.py:20,
                  test_indication_sentinel.py:30, test_result_schema_constraints.py:143};
                  and methods/methods/catalog_query/read.py:863 (_load_products —
                  manifest -> product reverse index; unseen ids are opaque, a missing
                  or unparseable file returns {} SILENTLY) plus read.py:966, a
                  stat-only read feeding the catalog-index cache digest
  catalog copy    data-catalog scripts/validate_catalog.py, which REJECTS a derived
                  manifest whose `product_id:` is not registered there

Note the asymmetry that makes this seam worth guarding: NO consumer of either copy
fails loudly on an id it has never seen. methods treats ids as opaque, the contracts
validator only warns (and returns early when the sibling is absent), and the one
fail-loud path — resolve_release()'s ReleaseResolutionError — never reads this
registry at all. So a product id that exists in one copy and not the other produces
no signal anywhere except here.

They were split by DC #55 ("migrate core-artifacts-schema into data-catalog") and
then edited independently in opposite directions: TC #141 backfilled
`core_artifact_path_template` here only, DC #67 registered `depmap-predictability`
there only. Nothing noticed, because no check spanned the two files.

HARDENED 2026-09-29 (#2098). The DC gate audit filed this seam as an unguarded
"triplication"; re-measuring on current main found (a) the monorepo's ROOT
`core-artifacts-schema/` copy is GONE (deleted by #2133/PR#2135), so it is a
DUPLICATION — this file and DC's — and (b) this guard already existed and already
compared the right things. What it did NOT do was hold itself accountable:

  * it skipped, unconditionally, when the data-catalog sibling was absent. As of
    #2090 `contracts-pytest` DOES check data-catalog out (`data-catalog-pinned`,
    pinned via `env.DATA_CATALOG_SHA`) and exports `DATA_CATALOG_ROOT` — so the
    graceful skip had stopped being a kindness and become a FAIL-OPEN: delete the
    checkout step or typo the env var and the only cross-repo check on the product
    registry goes silently vacuous while CI stays green. The skip is now allowed
    OUTSIDE CI only (house idiom: `pytest.fail(... " [CI]")` on `CI`).
  * the "catalog copy is a strict FIELD-subset" claim in this docstring was
    asserted nowhere, and the contracts-only *id* direction was unpinned, so a new
    divergence in either dimension arrived invisibly. Both are now closed-set pins
    (`CONTRACTS_ONLY_FIELDS`, `CONTRACTS_ONLY_PRODUCT_IDS`) — widening them is a
    deliberate, reviewable edit rather than a silent drift.
  * `schema_version` was never compared; a bump on one side only is exactly the
    silent drift this file exists to catch.

DELETE-AND-REPOINT was considered first (fewer copies beats more guards) and is
NOT viable: DC's copy carries none of the three fields below, and four contracts
suites plus the orchestrator path-template machinery require them. Byte-sync is
likewise impossible by construction — the two copies legitimately differ. A
semantic guard is the only honest enforcement here.

These tests pin the invariants that actually matter, deliberately NOT equality:

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

Outside CI the sibling may genuinely be absent (a bare checkout, someone's laptop)
and a false-fail there teaches people to ignore the check — so a local run still
skips, loudly and by name under `-rs`. Inside CI the sibling is guaranteed by the
`contracts-pytest` checkout step, so absence is a CI-configuration regression and
fails.

REUSABLE (for #2097, the measurement_types/indication_crosswalk byte-sync guard at
the adjacent seam): `require_data_catalog()` below is the fail-closed sibling
resolver — import it rather than re-deriving the DATA_CATALOG_ROOT fallback and the
CI/non-CI branch.
"""

import os
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CONTRACTS_REGISTRY = REPO / "vocabularies" / "products.yaml"
# data-catalog STAYS a separate repo (SK#2063 only folded target-contracts/analysis-methods into
# this monorepo), so the default is genuinely sibling-relative — never a hardcoded
# /home/sagemaker-user literal (SK#2137).
DATA_CATALOG_REPO = Path(
    os.environ.get("DATA_CATALOG_ROOT", str(REPO.parent.parent / "rnd-computational-biology-oncology-data-catalog"))
)
CATALOG_REGISTRY = DATA_CATALOG_REPO / "core-artifacts-schema" / "products.yaml"

# Fields this copy declares that DC's authoritative copy does not — the "strict
# field-subset" relationship the module docstring asserts. Required by
# tests/schemas/{test_product_path_templates,test_indication_sentinel}.py and by the
# orchestrators that template a core-artifact S3 key. CLOSED SET: adding a fourth
# contracts-only field is a real decision (it means DC's registry can no longer
# round-trip ours), so it must be declared here with a reason, not just appear.
CONTRACTS_ONLY_FIELDS = frozenset(
    {
        "core_artifact_path_template",
        "indication_sentinel",
        "requires_subgroup",
    }
)

# Product ids registered HERE but not in DC's copy. Legitimate in principle — a
# planned product may exist here before any catalog data does — but currently EMPTY
# (26 ids, both copies, verified 2026-09-29). Pinned closed so a one-sided
# registration is a deliberate, reviewed addition instead of an invisible
# divergence: an id only this copy knows is an id DC's validate_catalog.py will
# REJECT on any derived manifest that declares it.
CONTRACTS_ONLY_PRODUCT_IDS: frozenset[str] = frozenset()


def require_data_catalog() -> Path:
    """Fail-closed resolver for the data-catalog sibling checkout.

    Returns the DC repo root. Inside CI a missing sibling FAILS (the
    `contracts-pytest` job checks it out and exports `DATA_CATALOG_ROOT`, so absence
    means that wiring regressed and every cross-repo check silently went vacuous);
    outside CI it skips, since a bare local checkout legitimately lacks it.
    """
    if DATA_CATALOG_REPO.is_dir():
        return DATA_CATALOG_REPO
    reason = (
        f"data-catalog sibling absent ({DATA_CATALOG_REPO}) — cross-repo comparison cannot run. "
        f"Set DATA_CATALOG_ROOT or clone the sibling."
    )
    pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    raise AssertionError("unreachable")  # pragma: no cover


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def _by_id(doc: dict) -> dict:
    return {p["id"]: p for p in doc["products"]}


@pytest.fixture(scope="module")
def docs():
    require_data_catalog()
    if not CATALOG_REGISTRY.is_file():
        reason = f"data-catalog product registry missing ({CATALOG_REGISTRY}) — cannot compare registries"
        pytest.fail(reason + " [CI]") if os.environ.get("CI") else pytest.skip(reason)
    return _load(CONTRACTS_REGISTRY), _load(CATALOG_REGISTRY)


@pytest.fixture(scope="module")
def registries(docs):
    contracts_doc, catalog_doc = docs
    return _by_id(contracts_doc), _by_id(catalog_doc)


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


def test_schema_version_matches(docs):
    """A `schema_version:` bump applied to one copy only is silent registry drift."""
    contracts_doc, catalog_doc = docs
    assert contracts_doc.get("schema_version") == catalog_doc.get("schema_version"), (
        f"products.yaml schema_version diverged: contracts={contracts_doc.get('schema_version')!r} "
        f"catalog={catalog_doc.get('schema_version')!r}. The registries are meant to describe the "
        f"same product vocabulary at the same schema version; bump both or neither."
    )


def test_contracts_only_product_ids_are_the_declared_closed_set(registries):
    """A product registered HERE but not in the catalog must be a declared exception.

    The reverse direction of `test_every_catalog_registered_product_exists_here` is
    legitimate (a planned product can precede its data) but must not be SILENT: DC's
    validate_catalog.py rejects any derived manifest declaring an id its own registry
    does not carry, so a one-sided registration here is a latent publish-time failure.
    Pinned closed rather than merely warned so the divergence is reviewed once, at the
    moment it is introduced.
    """
    contracts, catalog = registries
    contracts_only = frozenset(contracts) - frozenset(catalog)
    assert contracts_only == CONTRACTS_ONLY_PRODUCT_IDS, (
        f"contracts-only product ids changed: {sorted(contracts_only)} != declared "
        f"{sorted(CONTRACTS_ONLY_PRODUCT_IDS)}. If you deliberately registered a product here "
        f"ahead of its catalog data, add its id to CONTRACTS_ONLY_PRODUCT_IDS with a reason — and "
        f"know that data-catalog's validate_catalog.py will REJECT a derived manifest declaring it "
        f"until DC's core-artifacts-schema/products.yaml registers it too."
    )


def test_catalog_copy_is_a_strict_field_subset(registries):
    """Pin the field-level shape the module docstring claims but never checked.

    `test_no_shared_key_value_drift` compares only keys both copies declare, which is
    the honest comparison ONLY as long as the extra keys are the known, deliberate
    contracts-only set. An undeclared fourth field would silently enlarge the
    uncompared surface — the shared-key test would stay green while the registries
    grew further apart.
    """
    contracts, catalog = registries
    undeclared: list[str] = []
    for pid in sorted(set(contracts) & set(catalog)):
        for field in sorted(set(contracts[pid]) - set(catalog[pid])):
            if field not in CONTRACTS_ONLY_FIELDS:
                undeclared.append(f"{pid}.{field}")
    assert not undeclared, (
        f"fields present in vocabularies/products.yaml but not in data-catalog's copy, and not "
        f"declared in CONTRACTS_ONLY_FIELDS: {undeclared}. Either mirror the field into DC's "
        f"authoritative copy, or add it to CONTRACTS_ONLY_FIELDS with the reason it is "
        f"contracts-only — silently widening the uncompared surface defeats "
        f"test_no_shared_key_value_drift."
    )


def test_catalog_copy_declares_no_field_the_contracts_copy_lacks(registries):
    """DC is authoritative: a field it adds must be mirrored here, not dropped.

    This is the direction that loses information. `test_no_shared_key_value_drift`
    cannot see a field DC added and we never picked up — it simply is not a shared
    key — so an authoritative addition would sit unnoticed on the far side of the seam.
    """
    contracts, catalog = registries
    missing: list[str] = []
    for pid in sorted(set(contracts) & set(catalog)):
        for field in sorted(set(catalog[pid]) - set(contracts[pid])):
            missing.append(f"{pid}.{field}")
    assert not missing, (
        f"declared in data-catalog's authoritative core-artifacts-schema/products.yaml but absent "
        f"from vocabularies/products.yaml: {missing}. DC's copy is the source of truth for the "
        f"shared product vocabulary — mirror the field here."
    )
