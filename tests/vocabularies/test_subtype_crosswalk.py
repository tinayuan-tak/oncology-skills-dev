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

import re
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
#
# ★ CUT 12 -> 6 on 2026-09-14 (stage 3d). The six HNSC/ESCA entries were AUTHORED, not dropped: each is
# now registered on a real axis and each cleared `authoring_rule.registrable_when` against a MEASURED
# shard denominator -- asserted by name in test_authored_strata_rest_on_a_measured_denominator below, so
# removing them from this pin could not be a way of quietly deleting the debt. AML stays, and its block
# now names THREE independent sufficient blockers rather than one.
_EXPECTED_PENDING = {
    ("AML", "FLT3_ITD"),
    ("AML", "NPM1_mut"),
    ("AML", "IDH1_mut"),
    ("AML", "IDH2_mut"),
    ("AML", "TP53_mut"),
    ("AML", "adverse_cytogenetics"),
}

# The six strata stage 3d moved OUT of `pending_authoring` and onto real axes. Pinned here for the same
# reason the pending ledger is pinned, in the opposite direction: shrinking _EXPECTED_PENDING is only
# honest if something else asserts the removed ids were actually authored AND measured.
_AUTHORED_STAGE_3D = {
    ("HNSC", "TP53_mut"),
    ("HNSC", "PIK3CA_mut"),
    ("HNSC", "NOTCH1_mut"),
    ("HNSC", "CCND1_amp"),
    ("HNSC", "TMB_high"),
    ("ESCA", "TP53_mut"),
}

# ★ Registered strata that VIOLATE `authoring_rule.registrable_when` -- `absent` (a measured zero over a
# full denominator) on EVERY cohort their axis declares. Both are PRE-EXISTING and both are real:
# PAAD FGFR2_fusion and RET_fusion_PAAD measure 0 members of 190 evaluable of 190 rows on tcga, and
# their catalogs' `expected_n_depmap: 1` cannot rescue them -- that note reads "NOT MEASURED ... no
# fusion-consensus product", and `fusion`'s `cohorts:` does not declare depmap anyway. Pinned by
# EQUALITY, so a newly authored violation is an error and fixing one of these two is also an error until
# the pin is deleted. Not fixed here: de-registering a stratum is verdict-bearing.
_ABSENT_ON_EVERY_DECLARED_COHORT = {
    ("PAAD", "FGFR2_fusion"),
    ("PAAD", "RET_fusion_PAAD"),
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

    `pending_authoring` is what keeps the reverse guard landable while the real gaps wait on measured
    denominators (12 at stage 3c; 6 after stage 3d authored the HNSC/ESCA six). That makes it the obvious
    place to hide a future orphan, so:

    (a) PINNED BY NAME against _EXPECTED_PENDING -- a derived count would be satisfied by any N ids.
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


# =================================================================================================
# Stage 3d -- the authored axes, and the rule they had to clear
# =================================================================================================


def _registered_index(doc):
    """{(indication, stratum_id): axis_block} over every registered axis."""
    out = {}
    for ind in doc["indications"]:
        for ax in ind.get("axes") or []:
            for sid in ax.get("strata") or []:
                out[(ind["canonical_code"], sid)] = ax
    return out


def _evidence_state(stratum, cohort):
    """`authoring_rule`'s trichotomy for ONE (stratum, declared cohort), read off the catalog.

    Returns `measured` (n>=30), `underpowered` (1<=n<30), `absent` (a MEASURED zero), `not_measured`
    (a count with no measurement behind it) or `no_key` (the catalog declares nothing for this cohort).

    Two traps live here, and this helper is the only place to get them right:

    (1) THE COHORT TOKEN IS NOT THE KEY NAME. One `--data-source tcga` run writes `expected_n_tcga`,
        `_tcga_coadread`, `_tcga_pdac`, `_tcga_nsclc`, `_tcga_sclc` AND `_tcga_gc`, so this matches by
        PREFIX rather than against a hardcoded list of the spellings that happen to exist today -- a
        hardcoded set silently narrows to 1-of-6 the moment the population splits again.
    (2) THE VALUE IS NOT THE EVIDENCE. `0` doubles as an N/A sentinel, and `evaluable == 0` is not
        `n == 0`, so ONLY an `Observed emit` note turns a count into a measurement -- of members or of
        absence. A note reading "Corrected ... Reset to the N/A sentinel 0" is NOT an absence claim.
        Admitting it as one is precisely how NSCLC histology's depmap claim came to be filed as
        contradicted while the published shard measures 118 and 32 members of 150 evaluable.
    """
    pref = f"expected_n_{cohort}"
    keys = [k for k in stratum if (k == pref or k.startswith(pref + "_")) and not k.endswith("_note")]
    if not keys:
        return "no_key"
    states = []
    for k in keys:
        n = stratum[k]
        note = str(stratum.get(f"{k}_denominator_note") or "")
        if not isinstance(n, int) or not note.startswith("Observed emit"):
            states.append("not_measured")
        elif n == 0:
            states.append("absent")
        elif n < 30:
            states.append("underpowered")
        else:
            states.append("measured")
    for best in ("measured", "underpowered", "absent", "not_measured"):
        if best in states:
            return best
    return "no_key"


def _catalog_strata_index():
    """{(indication, stratum_id): stratum_block} over every catalog on disk."""
    out = {}
    for code, cat in _catalog_docs().items():
        for key in ("atomic_strata", "composite_cohorts"):
            for s in cat.get(key) or []:
                if isinstance(s, dict) and s.get("id"):
                    out[(code, s["id"])] = s
    return out


@pytest.mark.skipif(not DATA_CATALOG.exists(), reason="sibling data-catalog repo not on disk")
def test_authored_strata_are_registered_on_a_real_axis_with_cohorts():
    """The positive half of cutting _EXPECTED_PENDING from 12 to 6.

    Shrinking a debt ledger and authoring the debt look identical from the ledger's side, so the six
    removed ids are asserted PRESENT here: on a named axis, with a `cohorts:` list. An axis with no
    cohorts is unroutable -- `tp_facets_subtype.py` builds `cohorts_of` from it, and a stratum whose
    axis claims no cohort can never be joined to a shard.
    """
    doc = _load()
    reg = _registered_index(doc)
    missing = sorted(_AUTHORED_STAGE_3D - set(reg))
    assert not missing, (
        f"stage 3d claims these were authored, but they are not on any axis: {missing} -- either "
        "register them or put them back in pending_authoring and restore the _EXPECTED_PENDING entries"
    )
    for key in sorted(_AUTHORED_STAGE_3D):
        ax = reg[key]
        assert ax.get("axis"), f"{key}: registered on an axis with no name"
        assert ax.get("cohorts"), f"{key}: axis {ax.get('axis')!r} declares no cohorts -- unroutable"
        assert set(ax["cohorts"]) <= _COHORTS, f"{key}: unknown cohort token in {ax['cohorts']}"


@pytest.mark.skipif(not DATA_CATALOG.exists(), reason="sibling data-catalog repo not on disk")
def test_authored_strata_rest_on_a_measured_denominator():
    """★ THE PLAN'S GOVERNING DECISION, made checkable: *no stratum ships on a guessed denominator.*

    Every stratum authored in stage 3d must reach `measured` or `underpowered` -- i.e. carry an
    `Observed emit` count with at least one member -- on at least one cohort its axis declares. That is
    `authoring_rule.registrable_when` applied at the moment of authoring.

    Note what this does NOT require: it does not require n>=30. The floor LABELS, it does not ADMIT --
    HNSC NOTCH1_mut (20) and TMB_high (27) are registered BECAUSE underpowered is not absent, and a flat
    n>=30 authoring gate would have disqualified 36 of 84 measured cells. What it forbids is authoring on
    an ESTIMATE, which is the state 83 of 99 declared counts were in before this arc measured them.
    """
    doc = _load()
    reg = _registered_index(doc)
    cat_strata = _catalog_strata_index()
    report, unmeasured = {}, []
    for key in sorted(_AUTHORED_STAGE_3D):
        s = cat_strata.get(key)
        assert s is not None, f"{key}: authored but absent from the catalog -- phantom id"
        states = {c: _evidence_state(s, c) for c in reg[key].get("cohorts") or []}
        report[key] = states
        if not ({"measured", "underpowered"} & set(states.values())):
            unmeasured.append((key, states))
    assert not unmeasured, (
        "strata authored without a MEASURED denominator on any declared cohort:\n"
        + "\n".join(f"  {k}: {st}" for k, st in unmeasured)
        + "\n`not_measured` means a count with no `Observed emit` note behind it -- an estimate. Run the "
        "assigner and write the observed n back before registering, or park the stratum in "
        f"pending_authoring.\nfull report: {report}"
    )


@pytest.mark.skipif(not DATA_CATALOG.exists(), reason="sibling data-catalog repo not on disk")
def test_no_registered_stratum_is_absent_on_every_cohort_its_axis_declares():
    """`authoring_rule.registrable_when` as a standing invariant over the WHOLE registry, not just the
    strata this branch touched.

    A stratum measured at zero members over a full denominator on every cohort its axis declares is one
    the subtype tier can never populate: the fan-out builds a panorama, the reader finds nobody, and the
    run degrades with no way to tell "nobody is in this stratum" from "this stratum was never wired".

    The two known violators are pinned by EQUALITY, which is what keeps a reasoned exception from
    becoming permanent permission: a new violation reds ("author it correctly"), and repairing an old one
    ALSO reds ("delete the pin"). Compare test_declared_cohorts_that_measure_absent_are_exactly_the_pinned_set
    in tests/schemas/, which pins the same facts at (indication, stratum, cohort) grain.
    """
    doc = _load()
    reg = _registered_index(doc)
    cat_strata = _catalog_strata_index()
    examined, violations = 0, set()
    for key, ax in sorted(reg.items()):
        s = cat_strata.get(key)
        if s is None:
            continue  # registry->catalog direction is test_registry_strata_exist_in_catalog's job
        examined += 1
        states = {_evidence_state(s, c) for c in ax.get("cohorts") or []}
        if states and states <= {"absent", "not_measured", "no_key"} and "absent" in states:
            violations.add(key)
    # ★ LIVENESS BEFORE THE CEILING: if the census dies (catalogs unreadable, ids renamed) every lookup
    # misses, `violations` is empty, and the assertion below passes for the wrong reason.
    assert examined >= 60, f"census died -- only {examined} registered strata resolved to a catalog block"
    assert violations == _ABSENT_ON_EVERY_DECLARED_COHORT, (
        "the set of registered strata that measure ABSENT on every declared cohort changed.\n"
        f"  new violations (fix the axis's cohorts, or do not register the stratum): "
        f"{sorted(violations - _ABSENT_ON_EVERY_DECLARED_COHORT)}\n"
        f"  no longer violating (delete the pin): {sorted(_ABSENT_ON_EVERY_DECLARED_COHORT - violations)}"
    )


# The number of registered strata with NO measured cohort at all -- every declared cohort is an estimate
# or declares nothing. A DOWNWARD ratchet, not a pin: 16 today, and the data-catalog half of stage 3d
# lowers it. Growing it means a stratum was registered on a guess, the practice this arc exists to end.
#   BRCA x8 (no depmap-subgroup-assignments-brca-* shard exists at all), COADREAD LOT x3 and NSCLC LOT x3
#   (line-of-therapy strata declare no expected_n key on any cohort), NSCLC + PAAD NTRK_fusion (the
#   fusion rule grammar is `fusion_gene in [...]` where the assigner requires `fusion_gene == '<GENE>'`,
#   so the run is UNMEASURABLE_NO_ROWS rather than zero).
# ★ Count this with _catalog_docs(), never with a `2026-Q3` glob: COADREAD -- the reference indication
#   whose Observed-emit provenance every other catalog copies -- is the ONE on 2026-Q2, so a
#   quarter-hardcoded reader drops it entirely and under-reports this ceiling by exactly 3.
_UNMEASURED_REGISTERED_CEILING = 16


@pytest.mark.skipif(not DATA_CATALOG.exists(), reason="sibling data-catalog repo not on disk")
def test_registered_strata_with_no_measurement_at_all_do_not_grow():
    """The ratchet that generalises the authoring rule to strata this branch did not author.

    Unlike the `absent` invariant above, this is not a correctness claim about any single stratum -- a
    stratum can legitimately await measurement. It is a claim about DIRECTION: the count may fall, never
    rise. Lower the ceiling when the data-catalog corrections land; a stale-high ceiling is a gate that
    has stopped gating.
    """
    doc = _load()
    reg = _registered_index(doc)
    cat_strata = _catalog_strata_index()
    examined, unmeasured = 0, []
    for key, ax in sorted(reg.items()):
        s = cat_strata.get(key)
        if s is None:
            continue
        examined += 1
        states = {_evidence_state(s, c) for c in ax.get("cohorts") or []}
        if states and states <= {"not_measured", "no_key"}:
            unmeasured.append(key)
    assert examined >= 60, f"census died -- only {examined} registered strata resolved to a catalog block"
    assert len(unmeasured) <= _UNMEASURED_REGISTERED_CEILING, (
        f"{len(unmeasured)} registered strata have no measured denominator on any declared cohort, above "
        f"the ceiling of {_UNMEASURED_REGISTERED_CEILING}: {sorted(unmeasured)}"
    )
    if len(unmeasured) < _UNMEASURED_REGISTERED_CEILING:
        pytest.fail(
            f"GOOD NEWS, ratchet needs lowering: {len(unmeasured)} unmeasured registered strata, ceiling "
            f"is {_UNMEASURED_REGISTERED_CEILING}. Set _UNMEASURED_REGISTERED_CEILING to "
            f"{len(unmeasured)} so the improvement cannot be silently given back."
        )


# =================================================================================================
# reader_routing -- registering a stratum is link 2 of 3, and this block says so
# =================================================================================================

SKILLS = REPO.parent / "rnd-computational-biology-oncology-claude-oncology-skills"


def test_reader_routing_block_is_structurally_live():
    """Anti-vacuity for the `reader_routing` block, with no sibling repo needed.

    The block's whole purpose is to stop a future reader mistaking a zero-diff replay for a safety
    result when it is really a capability result. That only works if it names LIVE registrations: an
    `unrouted_indications` entry for an indication this registry does not carry would be a warning about
    nothing, and would go stale invisibly.
    """
    doc = _load()
    rr = doc["reader_routing"]
    unrouted = rr.get("unrouted_indications") or []
    assert unrouted, "reader_routing with an empty unrouted list is a claim about nothing -- delete it"
    registered = {ind["canonical_code"]: ind for ind in doc["indications"]}
    for code in unrouted:
        assert code in registered, (
            f"reader_routing names {code} as unrouted, but no indication with that canonical_code is "
            "registered -- the block is warning about a stratum set that does not exist"
        )
        assert registered[code].get("axes"), f"{code}: named unrouted but carries no axes"
    n = rr.get("registries_returning_none")
    assert isinstance(n, int) and n > 0, f"registries_returning_none must be a positive count, got {n!r}"
    assert str(rr.get("link_3_file", "")).endswith("_live_readers.py"), (
        "link_3_file must name the file that does the routing, so the claim can be re-measured"
    )


@pytest.mark.skipif(
    not SKILLS.exists(),
    reason="sibling claude-oncology-skills repo not on disk -- link-3 routing claim UNVERIFIED here, "
    "not verified-absent; see reader_routing in subtype_crosswalk.yaml",
)
def test_reader_routing_unrouted_indications_are_still_unrouted():
    """The liveness half: re-measure the claim instead of trusting the comment that recorded it.

    `reader_routing` asserts that N per-indication registries in `_live_readers.py` return no shard for
    HNSC and ESCA. Both halves are checkable from the file itself -- the indication codes must be absent
    from it, and the registry count must still match. If someone wires HNSC (the real capability fix,
    currently held by a peer claim on `_skills_common/`), this test reds and says so, rather than leaving
    a stale "MISSING" note that reads as current.

    A pointer that never resolves looks like a working one, so the file's existence is asserted first.
    """
    doc = _load()
    rr = doc["reader_routing"]
    live = SKILLS / "skills" / "_skills_common" / "_live_readers.py"
    assert live.exists(), f"reader_routing.link_3_file does not resolve on disk: {live}"
    text = live.read_text()

    routed_now = [c for c in rr["unrouted_indications"] if c in text]
    assert not routed_now, (
        f"reader_routing is STALE: {routed_now} now appear in {live.name}. Re-measure "
        "`_shard_for_indication` for them and update or delete the block -- a resolved gap described as "
        "MISSING is worse than no note, because the next reader trusts it."
    )

    registries = re.findall(r"^_[A-Z0-9_]*ASSIGNMENTS[A-Z0-9_]*\s*=\s*\{", text, re.MULTILINE)
    assert len(registries) == rr["registries_returning_none"], (
        f"{live.name} now declares {len(registries)} per-indication assignment registries but "
        f"reader_routing claims {rr['registries_returning_none']} return no shard. Re-measure all of "
        "them and update the count -- a new registry could be the one that routes these indications."
    )
