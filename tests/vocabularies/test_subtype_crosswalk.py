"""Validator for vocabularies/subtype_crosswalk.yaml (subtyping review 2026-08-09).

Asserts the registry is well-formed and STAYS IN SYNC with the data-catalog subgroup-catalogs:
- every stratum id declared here must exist in the corresponding catalog (no phantom ids),
- every association references strata declared in the SAME indication,
- relationship types are from the controlled vocabulary,
- cohort tokens are from the known data-source set.
The catalog-sync check is skipped gracefully if the sibling data-catalog repo isn't on disk.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO = Path(__file__).resolve().parents[2]
CROSSWALK = REPO / "vocabularies" / "subtype_crosswalk.yaml"
DATA_CATALOG = REPO.parent / "rnd-computational-biology-oncology-data-catalog"

_REL_TYPES = {"enriched_in", "co_defining", "mutually_exclusive", "orthogonal"}
_COHORTS = {"tcga", "depmap", "genie", "genie_bpc", "george_2015"}


def _load():
    return yaml.safe_load(CROSSWALK.read_text())


def test_yaml_well_formed_and_versioned():
    doc = _load()
    assert doc["schema_version"] == 1
    assert isinstance(doc["indications"], list) and doc["indications"]


def test_every_indication_has_axes_with_strata():
    doc = _load()
    for ind in doc["indications"]:
        assert ind.get("canonical_code")
        assert ind.get("axes"), f"{ind['canonical_code']}: no axes"
        for ax in ind["axes"]:
            assert ax.get("axis") and ax.get("strata"), f"{ind['canonical_code']}: malformed axis {ax}"
            for c in ax.get("cohorts", []):
                assert c in _COHORTS, f"{ind['canonical_code']}/{ax['axis']}: unknown cohort {c!r}"


def test_associations_reference_declared_strata_and_valid_relationships():
    doc = _load()
    for ind in doc["indications"]:
        declared = {s for ax in ind["axes"] for s in ax["strata"]}
        for assoc in ind.get("associations", []) or []:
            assert assoc["relationship"] in _REL_TYPES, (
                f"{ind['canonical_code']}: bad relationship {assoc['relationship']!r}"
            )
            assert assoc["from"] in declared, (
                f"{ind['canonical_code']}: association 'from' {assoc['from']!r} not a declared stratum"
            )
            assert assoc["to"] in declared, (
                f"{ind['canonical_code']}: association 'to' {assoc['to']!r} not a declared stratum"
            )


def test_no_stratum_id_duplicated_across_axes_within_indication():
    doc = _load()
    for ind in doc["indications"]:
        seen = {}
        for ax in ind["axes"]:
            for s in ax["strata"]:
                assert s not in seen, f"{ind['canonical_code']}: stratum {s!r} in both {seen.get(s)} and {ax['axis']}"
                seen[s] = ax["axis"]


@pytest.mark.skipif(not DATA_CATALOG.exists(), reason="sibling data-catalog repo not on disk")
def test_registry_strata_exist_in_catalog():
    """Every stratum id in the registry must exist in the indication's subgroup-catalog (keeps the
    registry from drifting into phantom ids). A registry id absent from the catalog = a stale entry."""
    doc = _load()
    import glob

    for ind in doc["indications"]:
        code = ind["canonical_code"]
        cat_files = glob.glob(str(DATA_CATALOG / "subgroup-catalogs" / code / "*.yaml"))
        if not cat_files:
            continue  # indication has no catalog yet (e.g. a registry-ahead-of-catalog case)
        cat = yaml.safe_load(Path(cat_files[0]).read_text())
        catalog_ids = {s["id"] for s in cat.get("atomic_strata", [])}
        for ax in ind["axes"]:
            for s in ax["strata"]:
                assert s in catalog_ids, f"{code}: registry stratum {s!r} ({ax['axis']}) not in catalog {cat_files[0]}"
