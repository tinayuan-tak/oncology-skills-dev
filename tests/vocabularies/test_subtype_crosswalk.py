"""Validator for vocabularies/subtype_crosswalk.yaml (subtyping review 2026-08-09).

Asserts the registry is well-formed and STAYS IN SYNC with the data-catalog subgroup-catalogs
IN BOTH DIRECTIONS:
- every stratum id declared here must exist in the corresponding catalog (no phantom ids),
- every catalog stratum must be registered here OR named in `intentionally_excluded` (no SILENT
  omissions -- see test_catalog_strata_are_registered_or_declared_excluded for why the missing
  direction mattered),
- every association references strata declared in the SAME indication,
- relationship types are from the controlled vocabulary,
- cohort tokens are from the known data-source set.
The catalog-sync checks are skipped gracefully if the sibling data-catalog repo isn't on disk.
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


def _catalog_docs():
    """{indication: parsed catalog} for every subgroup-catalog on disk.

    Picks the LEXICALLY LAST version file per indication (`2026-Q2.yaml` > `2026-Q1.yaml`) rather than
    glob's first: an indication that gains a new quarter must be read at its NEWEST catalog, or the
    guard silently keeps validating a superseded stratum set. (The forward test predates this and still
    reads `cat_files[0]`; every indication currently has exactly one file, so the two agree today.)
    """
    import glob

    out = {}
    for d in sorted(glob.glob(str(DATA_CATALOG / "subgroup-catalogs" / "*"))):
        files = sorted(glob.glob(str(Path(d) / "*.yaml")))
        if files:
            out[Path(d).name] = yaml.safe_load(Path(files[-1]).read_text())
    return out


def _catalog_stratum_ids(cat):
    """Every stratum id a catalog declares -- atomic AND composite.

    `composite_cohorts` is a separate top-level list from `atomic_strata` and the forward test reads
    only the latter, so COADREAD's three GENIE-BPC line-of-therapy composites were outside BOTH
    directions of the sync check. They are excluded by DECLARATION now, not by the reader's blind spot.
    """
    ids = set()
    for key in ("atomic_strata", "composite_cohorts"):
        for s in cat.get(key) or []:
            if isinstance(s, dict) and s.get("id"):
                ids.add(s["id"])
    return ids


def _declared_index(doc, key):
    """{(indication, stratum_id): block} from `intentionally_excluded` or `pending_authoring`."""
    out = {}
    for blk in doc.get(key) or []:
        for sid in blk.get("strata") or []:
            out[(blk["indication"], sid)] = blk
    return out


def _excluded_index(doc):
    return _declared_index(doc, "intentionally_excluded")


def _pending_index(doc):
    return _declared_index(doc, "pending_authoring")


# The pending-authoring debt PINNED BY NAME. A derived count would let a new orphan be parked here to
# turn the reverse guard green; pinning the ids means adding one requires editing this test, and
# REMOVING one (i.e. actually authoring it) also requires editing this test, so the ledger cannot
# silently grow OR silently claim credit it has not earned.
_EXPECTED_PENDING = {
    ("AML", "FLT3_ITD"),
    ("AML", "NPM1_mut"),
    ("AML", "IDH1_mut"),
    ("AML", "IDH2_mut"),
    ("AML", "TP53_mut"),
    ("AML", "adverse_cytogenetics"),
    ("HNSC", "TP53_mut"),
    ("HNSC", "PIK3CA_mut"),
    ("HNSC", "NOTCH1_mut"),
    ("HNSC", "CCND1_amp"),
    ("HNSC", "TMB_high"),
    ("ESCA", "TP53_mut"),
}


@pytest.mark.skipif(not DATA_CATALOG.exists(), reason="sibling data-catalog repo not on disk")
def test_catalog_strata_are_registered_or_declared_excluded():
    """The MIRROR of test_registry_strata_exist_in_catalog. Every guard has a DIRECTION, and this one
    had only the direction that catches a registry TYPO -- not the one that catches a real capability
    gap.

    A catalog stratum absent from this registry is invisible to the DEFAULT-ON, verdict-bearing subtype
    tier: tp_common.default_subtypes() reads the registry, so the run proceeds WHOLE-COHORT and nothing
    reports a gap. The foundation audit found 21 such orphans across 9 catalogs -- including AML, which
    has a complete 6-stratum catalog and no registry entry at all.

    Excluding a stratum is now a declaration with a reason, not an absence.
    """
    doc = _load()
    registered = {(ind["canonical_code"], s) for ind in doc["indications"] for ax in ind["axes"] for s in ax["strata"]}
    declared = set(_excluded_index(doc)) | set(_pending_index(doc))
    orphans = []
    for code, cat in _catalog_docs().items():
        for sid in sorted(_catalog_stratum_ids(cat)):
            if (code, sid) not in registered and (code, sid) not in declared:
                orphans.append(f"{code}/{sid}")
    assert not orphans, (
        "catalog strata neither registered nor DECLARED -- these run WHOLE-COHORT silently under the "
        f"default-on subtype tier and nothing reports it: {orphans}. Resolve by one of three: add them "
        "to an axis, add them to intentionally_excluded (never, with a reason), or add them to "
        "pending_authoring (not yet, with what it is blocked on)."
    )


@pytest.mark.skipif(not DATA_CATALOG.exists(), reason="sibling data-catalog repo not on disk")
def test_exclusions_are_live_reasoned_and_not_a_way_to_hide_a_registered_stratum():
    """Anti-vacuity for the block itself, in three directions.

    (a) NON-EMPTY + reasoned: an exclusion with no reason is a suppression.
    (b) LIVE: every excluded id must still exist in its catalog. A stale exclusion is how a real
        orphan hides -- if the catalog renames `stage_I`, the old entry keeps excusing nothing while
        the new id goes unguarded.
    (c) DISJOINT: an id may not be both registered and excluded, or the two directions disagree about
        the same stratum and the reverse guard can be satisfied by a contradiction.
    """
    doc = _load()
    excluded = _excluded_index(doc)
    assert excluded, "intentionally_excluded is empty -- the reverse guard would then be trivially green"
    for (code, sid), blk in excluded.items():
        assert len(str(blk.get("reason", "")).strip()) > 30, f"{code}/{sid}: exclusion needs a substantive reason"

    cats = _catalog_docs()
    for blk in doc["intentionally_excluded"] or []:
        assert blk.get("class"), f"{blk['indication']}: exclusion block needs a `class`"
        cat = cats.get(blk["indication"])
        if cat is None:
            continue  # catalog not on disk for this indication
        ids = _catalog_stratum_ids(cat)
        for sid in blk["strata"]:
            assert sid in ids, (
                f"{blk['indication']}/{sid}: excluded id no longer exists in the catalog -- a STALE "
                "exclusion. Remove it, or update it to the renamed id."
            )

    registered = {(ind["canonical_code"], s) for ind in doc["indications"] for ax in ind["axes"] for s in ax["strata"]}
    both = sorted(set(excluded) & registered)
    assert not both, f"strata both registered AND excluded: {both}"


@pytest.mark.skipif(not DATA_CATALOG.exists(), reason="sibling data-catalog repo not on disk")
def test_every_catalogued_indication_has_a_registry_entry():
    """The indication-level mirror. AML shipped a complete 6-stratum catalog with NO registry entry, so
    every AML profile ran whole-cohort while the data sat right there -- a whole indication lost, not
    one stratum. An indication may be excluded wholesale only by declaring all of its strata."""
    doc = _load()
    registered_inds = {ind["canonical_code"] for ind in doc["indications"]}
    declared = set(_excluded_index(doc)) | set(_pending_index(doc))
    missing = []
    for code, cat in _catalog_docs().items():
        if code in registered_inds:
            continue
        unexcused = [s for s in _catalog_stratum_ids(cat) if (code, s) not in declared]
        if unexcused:
            missing.append(f"{code} ({len(unexcused)} strata)")
    assert not missing, (
        f"indications with a subgroup-catalog but no registry entry: {sorted(missing)} -- "
        "every profile run for these silently reads whole-cohort"
    )


@pytest.mark.skipif(not DATA_CATALOG.exists(), reason="sibling data-catalog repo not on disk")
def test_pending_authoring_ledger_is_pinned_live_and_disjoint():
    """The debt ledger, guarded like a debt and not like an excuse.

    `pending_authoring` is what keeps the reverse guard landable while the 12 real gaps wait on measured
    denominators. That makes it the obvious place to hide a future orphan, so:

    (a) PINNED BY NAME against _EXPECTED_PENDING -- a derived count would be satisfied by any 12 ids.
        Both growing and shrinking the ledger must be a deliberate edit here.
    (b) LIVE -- every pending id still exists in its catalog; a stale entry excuses nothing while the
        real id goes unguarded.
    (c) DISJOINT from both `intentionally_excluded` (opposite claims about the same stratum) and from
        the registered axes (already authored -- the entry should have been removed).
    (d) REASONED -- `blocked_on` plus a substantive `reason`, so the ledger says what would clear it.
    """
    doc = _load()
    pending = _pending_index(doc)
    assert set(pending) == _EXPECTED_PENDING, (
        "pending_authoring drifted from the pinned ledger.\n"
        f"  added (new debt, needs review): {sorted(set(pending) - _EXPECTED_PENDING)}\n"
        f"  removed (authored? then register it and update _EXPECTED_PENDING): "
        f"{sorted(_EXPECTED_PENDING - set(pending))}"
    )

    cats = _catalog_docs()
    for blk in doc["pending_authoring"] or []:
        assert blk.get("blocked_on"), f"{blk['indication']}: pending block needs `blocked_on`"
        assert len(str(blk.get("reason", "")).strip()) > 30, f"{blk['indication']}: needs a real reason"
        cat = cats.get(blk["indication"])
        if cat is None:
            continue
        ids = _catalog_stratum_ids(cat)
        for sid in blk["strata"]:
            assert sid in ids, f"{blk['indication']}/{sid}: pending id not in the catalog -- STALE entry"

    registered = {(ind["canonical_code"], s) for ind in doc["indications"] for ax in ind["axes"] for s in ax["strata"]}
    assert not set(pending) & registered, f"pending but already registered: {sorted(set(pending) & registered)}"
    assert not set(pending) & set(_excluded_index(doc)), (
        f"a stratum cannot be both pending and permanently excluded: {sorted(set(pending) & set(_excluded_index(doc)))}"
    )
