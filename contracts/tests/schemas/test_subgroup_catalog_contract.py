"""subgroup_catalog.schema.json — the contract that had no validator (foundation audit 3c).

★★ WHY THIS FILE EXISTS. `$defs.atomic_stratum` has carried `unevaluatedProperties: false` --
the strictest closure keyword in JSON Schema -- since it was written, and NOTHING has ever
validated a catalog against it. The only reference to the schema across all five repos was a
PROSE COMMENT in analysis-methods `scripts/emit_subgroup_assignments.py:328`. A schema with
maximal closure and no runner is indistinguishable from an absent one, and the corpus proved
it: `main` x `main` was invalid in **110 places** on 2026-09-13 (101 coalesced
`unevaluatedProperties` errors covering 123 undeclared-key occurrences, plus 9 `enum`).

★★ AND WHY THE DECLARATIONS ALONE WOULD HAVE PROVEN NOTHING. Taking 110 -> 0 by declaring the
five missing keys is, by itself, *relaxing a gate to match the build*: it adds zero checking
power, and it would have converted a decorative CLOSED schema into a decorative PERMISSIVE
one. So the same change added the constraints this file exercises -- bidirectional
`dependentRequired` over every cohort family, `minLength` on the provenance notes, and
`minimum` on `min_caller_count` -- and every one of them is asserted here to be capable of
going RED. Anything that cannot fail is not tested.

WHERE THIS RUNS, precisely, because that is the whole reason for the file's location:
  * `tests/schemas/` is the ONLY directory in this repo collected DIRECTORY-WIDE, by BOTH
    `.github/workflows/contracts-validate.yml:129` and `scripts/preland.sh:25`. Its siblings
    `tests/validators/` and `tests/vocabularies/` are wired FILE BY FILE, and the workflow
    warns about it in its own comments at line 166: "tests/validators/ is curated file-by-file,
    so an unwired file never runs." 42 of this repo's 66 test files (373 tests) currently run
    in no workflow at all -- including the reverse subtype guard landed by stage 2a. Putting
    this file anywhere else would have reproduced the exact defect that #767 was about.
  * Consequently Parts 1 and 2 below get REAL CI coverage: they read only in-repo files.
  * Part 3 needs the data-catalog sibling, which NO green job in ANY repo provides -- see the
    header of Part 3. It SKIPS in CI, and that is stated rather than disguised.
"""

import json
import os
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO / "schemas" / "subgroup_catalog.schema.json").read_text())
CROSSWALK = yaml.safe_load((REPO / "vocabularies" / "subtype_crosswalk.yaml").read_text())
RULES = yaml.safe_load((REPO / "interpretation-rules" / "intracellular-intrinsic.rules.yaml").read_text())

# Sibling gate, mirroring tests/schemas/test_products_registry_sync.py:50 (itself mirroring
# validators/validate_cards.py's `_DATA_CATALOG_REPO`). A checkout-only runner has no sibling.
# data-catalog STAYS a separate repo (SK#2063 only folded target-contracts/analysis-methods into
# this monorepo), so the default is genuinely sibling-relative — REPO.parent is this checkout's
# root, REPO.parent.parent its sibling-clone dir (whatever that is on a given box) — never a
# hardcoded /home/sagemaker-user literal (SK#2137).
DATA_CATALOG = Path(
    os.environ.get("DATA_CATALOG_ROOT", str(REPO.parent.parent / "rnd-computational-biology-oncology-data-catalog"))
)
CATALOG_DIR = DATA_CATALOG / "subgroup-catalogs"

# Validate a bare stratum without hand-building a whole catalog around it.
STRATUM = Draft202012Validator({"$ref": "#/$defs/atomic_stratum", "$defs": SCHEMA["$defs"]})
CATALOG = Draft202012Validator(SCHEMA)

_STRATUM_PROPS = SCHEMA["$defs"]["atomic_stratum"]["properties"]

# ★ DERIVED, not listed. This was a hardcoded 7 until 2026-09-14, and the hardcoding is what
# let the half-declared-family defect through: six families were added to the schema over two
# commits and the pairing tests below silently did not cover any of them, because covering a
# family required a human to also edit a literal here. Deriving from the schema's own
# `properties` means a family cannot be declared without being exercised. One
# `--data-source tcga` run writes a key under six different names across the nine catalogs,
# which is why this was never a `tcga`/`depmap` pair -- see the "six spellings" note in
# vocabularies/subtype_crosswalk.yaml.
COHORT_FAMILIES = sorted(
    k[len("expected_n_") :] for k in _STRATUM_PROPS if k.startswith("expected_n_") and not k.endswith("_note")
)

# The families whose absence was the defect, plus a couple of originals. An ANCHOR set, not an
# equality pin: a new legitimate family must not have to red a literal to be added.
_ANCHOR_FAMILIES = {"tcga", "depmap", "tcga_coadread", "tcga_gc", "genie", "genie_bpc", "george_2015", "ccle"}

_NOTE = "Observed emit 2026-09-13 against FIXTURE__directly_tagged__tcga (n~100 of 100 rows; 42 members)."


def _stratum(**over) -> dict:
    """Minimal VALID stratum. Every reject-case below is this plus one mutation, so a failure
    localises to the mutation instead of to fixture drift."""
    return {"id": "TP53_mut", "label": "TP53-mutant", "rule": "gene_symbol == 'TP53'", **over}


def _kinds(doc: dict, validator: Draft202012Validator = STRATUM) -> set[str]:
    return {e.validator for e in validator.iter_errors(doc)}


# ==========================================================================================
# Part 1 — schema behaviour on fixtures.  RUNS IN CI (no sibling repo needed).
# ==========================================================================================


def test_minimal_stratum_is_valid():
    """The control. If this ever fails, every reject-case below is uninterpretable."""
    assert not _kinds(_stratum())


def test_closure_still_rejects_an_undeclared_key():
    """★ The load-bearing anti-regression. Declaring five keys must NOT have opened the object
    up -- otherwise 110 -> 0 was achieved by deleting the gate."""
    assert "unevaluatedProperties" in _kinds(_stratum(some_new_field="x"))


def test_the_cohort_family_derivation_is_alive():
    """★ LIVENESS BEFORE THE CEILING, and it guards the three parametrized tests below rather
    than itself. `parametrize` over an empty list generates ZERO cases and pytest reports
    SUCCESS -- so if the derivation above ever collapsed (a rename of the `expected_n_` prefix,
    a restructure that moves these under `$defs`), the pairing suite would quietly drop from 39
    assertions to 0 and the run would still be green. Assert the population is non-empty and
    still holds the families whose ABSENCE was the 2026-09-14 defect."""
    assert COHORT_FAMILIES, "cohort-family derivation is empty — the pairing tests below are vacuous"
    missing = _ANCHOR_FAMILIES - set(COHORT_FAMILIES)
    assert not missing, f"cohort-family derivation lost members: {sorted(missing)}"


def test_every_declarable_source_can_record_its_own_denominator():
    """★★ THE GUARD THAT WOULD HAVE CAUGHT THIS. A NAME FAMILY IS TWO HALVES: the token that
    DECLARES a cohort (`applicable_data_sources` enum) and the key that CARRIES its count
    (`expected_n_<token>`). Declaring only the first half produces a schema where a stratum can
    name a cohort and is then FORBIDDEN from recording that cohort's denominator -- and it
    CANNOT go red on its own, because the corpus can never contain a key the schema rejects, so
    the missing half looks forgotten instead of forbidden. That is why the asymmetry survived
    from f9a7c22 (`ccle`, `gdsc`, `tempus`) and was then reproduced by #768 (`genie`,
    `genie_bpc`, `george_2015`): nothing anywhere compared the two halves.

    Direction matters, as in `test_applicable_data_sources_enum_covers_every_crosswalk_cohort_token`.
    Asserted: enum ⊆ families -- everything declarable must be recordable. The reverse is
    legitimately FALSE and must not be asserted: `tcga_coadread` and its four siblings are
    per-indication SPELLINGS of the `tcga` token, not distinct sources, so they have count keys
    with no enum member by design."""
    enum = set(_STRATUM_PROPS["applicable_data_sources"]["items"]["enum"])
    assert enum, "empty source enum — this check would be vacuous"
    unrecordable = enum - set(COHORT_FAMILIES)
    assert not unrecordable, (
        f"sources are declarable but their denominators are unrecordable: {sorted(unrecordable)}. "
        "Add `expected_n_<token>` + `expected_n_<token>_denominator_note` to `properties` and both "
        "directions to `dependentRequired`."
    )


@pytest.mark.parametrize("cohort", COHORT_FAMILIES)
def test_expected_n_requires_its_denominator_note(cohort):
    """Forward pairing: a count may not ship without provenance. A bare integer is ambiguous
    between a measurement, a real zero, and the 0-as-N/A sentinel the catalogs also use."""
    assert "dependentRequired" in _kinds(_stratum(**{f"expected_n_{cohort}": 42}))


@pytest.mark.parametrize("cohort", COHORT_FAMILIES)
def test_denominator_note_requires_its_expected_n(cohort):
    """Reverse pairing -- the half that is easy to omit. Provenance for a cohort the stratum
    does not declare is a note with nothing behind it; that is how the 8 STRAY_EXPECTATION
    cells (#598) got in."""
    assert "dependentRequired" in _kinds(_stratum(**{f"expected_n_{cohort}_denominator_note": _NOTE}))


@pytest.mark.parametrize("cohort", COHORT_FAMILIES)
def test_paired_expected_n_and_note_is_valid(cohort):
    """Non-vacuity for the two tests above: the PAIR must be accepted, in every family. If
    this failed, the pairing tests would be passing because the keys are simply forbidden."""
    assert not _kinds(_stratum(**{f"expected_n_{cohort}": 42, f"expected_n_{cohort}_denominator_note": _NOTE}))


def test_placeholder_note_is_rejected():
    assert "minLength" in _kinds(_stratum(expected_n_tcga=42, expected_n_tcga_denominator_note="TODO"))


def test_min_caller_count_is_declared_and_a_typo_is_not():
    """★ The point of DECLARING `data_source.min_caller_count`: the real hazard was never the
    schema error, it was that a reader defaulting the key would read `1` from a catalog that
    MISSPELLED it and never know. Declaring the correct name is what makes the typo visible."""
    ds = {"manifest_id": "tcga-fusion-consensus-per-sample-v1", "min_caller_count": 1}
    assert not _kinds(_stratum(data_source=ds))
    bad = {"manifest_id": "tcga-fusion-consensus-per-sample-v1", "min_caller_counts": 1}
    assert "unevaluatedProperties" in _kinds(_stratum(data_source=bad))


def test_min_caller_count_zero_is_not_a_threshold():
    ds = {"manifest_id": "m", "min_caller_count": 0}
    assert "minimum" in _kinds(_stratum(data_source=ds))


def test_genie_sources_are_accepted_and_unknown_ones_are_not():
    """genie/genie_bpc shipped in COADREAD and NSCLC while absent from the enum -- 9 of the 110
    errors. They are now declared; the enum must still CLOSE."""
    assert not _kinds(_stratum(applicable_data_sources=["tcga", "depmap", "genie", "genie_bpc"]))
    assert not _kinds(_stratum(applicable_data_sources=["george_2015"]))
    assert "enum" in _kinds(_stratum(applicable_data_sources=["foundation_one"]))


def test_applicable_data_sources_enum_covers_every_crosswalk_cohort_token():
    """★ Two vocabularies route this one axis: this enum, and the crosswalk's per-axis
    `cohorts:`. The enum being the NARROWER of the two is what made the corpus invalid. Assert
    containment in the direction that can produce an invalid catalog -- a cohort the crosswalk
    claims must be EXPRESSIBLE here, or the claim can never be recorded in a catalog at all.
    (That is why `george_2015` was added: the SCLC NAPY claim was structurally unrecordable.)"""
    enum = set(SCHEMA["$defs"]["atomic_stratum"]["properties"]["applicable_data_sources"]["items"]["enum"])
    claimed = {
        c for ind in CROSSWALK["indications"] for ax in (ind.get("axes") or []) for c in (ax.get("cohorts") or [])
    }
    assert claimed, "no cohort tokens found in the crosswalk — this check would be vacuous"
    assert claimed <= enum, f"crosswalk claims cohorts the schema cannot express: {claimed - enum}"


def test_a_whole_catalog_fixture_round_trips():
    """Closure applies at the ROOT too, so exercise it there once -- a stratum-only test would
    miss a mis-shaped top level."""
    doc = {
        "id": "fixture-subgroups-2026-q3",
        "manifest_kind": "subgroup_catalog",
        "indication": "FIXTURE",
        "version": "2026-Q3",
        "schema_version": 1,
        "atomic_strata": [_stratum()],
    }
    assert not _kinds(doc, CATALOG)
    assert "unevaluatedProperties" in _kinds({**doc, "bogus_root_key": 1}, CATALOG)


# ==========================================================================================
# Part 2 — the declared floor vs the literals that enforce it.  RUNS IN CI (in-repo only).
# ==========================================================================================
#
# Stage 3c's deliverable was to DECLARE the admissibility floor, which no repo did: sixteen
# literals in two families enforced one, kept consistent only by prose comments naming each
# other. `panorama.py:36` asserts "SINGLE SOURCE OF TRUTH — readers import this, never
# re-hardcode" while four skills modules re-hardcode it, necessarily -- the skills repo has no
# import path to analysis-methods. These tests make the vocabulary authoritative for the
# literals THIS repo owns; the cross-repo half cannot be enforced from here and is documented
# in the vocabulary instead of being silently omitted.


def _family(name: str) -> dict:
    fams = {f["family"]: f for f in CROSSWALK["admissibility_floors"]}
    assert name in fams, f"admissibility_floors is missing family {name!r}: {sorted(fams)}"
    return fams[name]


def test_two_floor_families_are_declared_with_distinct_populations():
    """★ The audit went in believing "5 is cell lines, 30 is patients" and MEASURING falsified
    it: `SUBGROUP_N_FLOOR` is applied to both units at 30 (gdc_somatic_hotspot/read.py:543 on
    patients, depmap_chronos/read.py:208 on cell lines). The families differ by POPULATION --
    stratum vs lineage -- which is why they are not reconcilable to one number, and why this
    test asserts they are DISTINCT rather than equal."""
    fams = {f["family"]: f for f in CROSSWALK["admissibility_floors"]}
    assert set(fams) == {"subgroup_stratum_n", "lineage_n"}
    assert fams["subgroup_stratum_n"]["value"] == 30
    assert fams["lineage_n"]["value"] == 5
    pops = {f["population"] for f in fams.values()}
    assert len(pops) == 2, "the two families must describe DIFFERENT populations"


def _rules_with_min_n() -> dict[str, int]:
    out = {}
    for r in RULES.get("rules") or []:
        meta = r.get("subgroup_metadata_declared") or {}
        if "min_n_required" in meta:
            out[r["rule_id"]] = meta["min_n_required"]
    return out


def test_in_repo_rule_literals_match_the_declared_floor():
    """Every `min_n_required` in this repo's interpretation rules must equal the declared
    `subgroup_stratum_n`, EXCEPT the single documented exception. Editing a rule's 30 without
    updating the vocabulary now reds CI."""
    found = _rules_with_min_n()
    assert len(found) >= 8, f"only {len(found)} rules carry min_n_required — scan looks broken"

    fam = _family("subgroup_stratum_n")
    declared = fam["value"]
    exc = fam["documented_exception"]

    off = {rid: n for rid, n in found.items() if n != declared}
    assert set(off) == {exc["rule_id"]}, (
        f"rules diverging from the declared floor {declared} must be exactly the documented "
        f"exception {exc['rule_id']!r}, got {off}"
    )
    assert off[exc["rule_id"]] == exc["min_n_required"]


def test_the_documented_exception_is_disjoint_from_the_floor_cleared_rule():
    """★ The exception is not a competing floor and not drift -- it is an EFFECT-ADMISSIBILITY
    gate. Its safety rests on being unreachable when the floor-cleared rule fires, so assert
    the disjointness rather than trusting the prose: one keys on `underpowered`, the other on
    `measured`, so they can never double-fire."""
    exc_id = _family("subgroup_stratum_n")["documented_exception"]["rule_id"]
    by_id = {r["rule_id"]: r for r in RULES["rules"]}
    exc = by_id[exc_id]
    assert (exc["when"]["in_record"]["evidence_state"]) == "underpowered"
    assert exc["when"]["in_record"]["subgroup_effect_admissible"] is True

    peers = [
        r
        for rid, r in by_id.items()
        if rid != exc_id
        and (r.get("when", {}).get("in_record", {}) or {}).get("evidence_state") == "measured"
        and (r.get("subgroup_metadata_declared") or {}).get("min_n_required")
    ]
    assert peers, "found no floor-cleared peer rule — the disjointness claim would be vacuous"


def test_in_repo_card_literals_match_the_declared_lineage_floor():
    """The `lineage_n` family's two in-repo definition sites are cards. Read the value out of
    each card rather than trusting `definition_sites` prose."""
    declared = _family("lineage_n")["value"]
    cards = sorted((REPO / "cards").glob("*.card.yaml"))
    assert cards, "no cards found — scan looks broken"
    found = {}
    for p in cards:
        doc = yaml.safe_load(p.read_text()) or {}
        for block in ("thresholds", "parameters", "params"):
            v = (doc.get(block) or {}).get("min_cell_lines_in_lineage")
            if v is not None:
                found[p.name] = v
    assert len(found) == 2, f"expected 2 cards to declare min_cell_lines_in_lineage, got {found}"
    assert set(found.values()) == {declared}, f"card literals {found} != declared {declared}"


def test_authoring_rule_is_the_evidence_state_trichotomy():
    """★ The floor LABELS, it does not ADMIT -- the single most important property, because a
    flat n>=30 authoring gate would retroactively disqualify 36 of the 84 measured cells,
    including essentially the whole NSCLC actionable-driver panel. Pin the three state names to
    `panorama.evidence_state()`'s return values so the two cannot drift apart silently."""
    ar = CROSSWALK["authoring_rule"]
    assert set(ar["states"]) == {"absent", "underpowered", "measured"}
    assert ar["floor_sets"] == "claim_strength_not_existence"
    assert "absent" in ar["registrable_when"]


# ==========================================================================================
# Part 3 — the live corpus.  SKIPS IN CI, and the blocker is named rather than hidden.
# ==========================================================================================
#
# ★★ THERE IS NO GREEN JOB IN ANY REPO WHERE BOTH THIS SCHEMA AND THE CATALOGS ARE PRESENT.
# That is why the schema was decorative -- not because a line was forgotten, but because no
# runnable context exists:
#   * `contracts-validate.yml` runs on every PR but checks out THIS repo only;
#   * `framework-health-cross-repo.yml` does check out all five, but is parked to
#     `workflow_dispatch` with 8/8 failed runs -- its `skills-reposet` PAT covers 3 of 5 repos
#     and the FIRST sibling checkout 404s;
#   * data-catalog's `test.yml` has no target-contracts checkout.
# A "graceful skip" here is therefore VACUOUS BY CONSTRUCTION in CI, and pretending otherwise
# would be the skip-is-not-a-pass defect. It is kept because it is the gate that runs locally
# and in `scripts/preland.sh` on a full checkout, where it is the 110 -> 0 measurement itself.
# Deliberately NOT addressed by adding a cross-repo workflow: a peer's identical attempt
# (data-catalog #597) failed for want of `CROSS_REPO_TOKEN`, and a permanently-red required
# check is the same defect class in reverse.

pytestmark_live = pytest.mark.skipif(
    not CATALOG_DIR.exists(),
    reason=f"data-catalog sibling absent ({CATALOG_DIR}) — cannot validate the live corpus. "
    "Expected in CI: no workflow in any repo checks out both repos (see Part 3 header).",
)


def _live_catalogs() -> dict[str, dict]:
    return {p.parent.name: yaml.safe_load(p.read_text()) for p in sorted(CATALOG_DIR.glob("*/*.yaml"))}


@pytestmark_live
def test_every_live_catalog_validates():
    """THE GATE. 110 errors on 2026-09-13, 0 after. Reported per catalog with the offending
    keys, because a bare count told nobody which declaration was missing."""
    docs = _live_catalogs()
    assert len(docs) >= 9, f"expected >=9 catalogs, found {len(docs)}"
    problems = {}
    for name, doc in docs.items():
        errs = list(CATALOG.iter_errors(doc))
        if errs:
            problems[name] = [
                f"{e.validator} at /{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}" for e in errs
            ]
    assert not problems, "live catalogs violate the schema:\n" + json.dumps(problems, indent=2)


@pytestmark_live
def test_every_expected_n_in_the_live_corpus_is_paired():
    """The `dependentRequired` ratchet, measured against reality rather than fixtures: every
    count pairs with a note, in all thirteen families.

    ★ WAS `counts == notes == 180` until 2026-09-14. The load-bearing invariant is `counts ==
    notes` -- every declared count carries provenance. The `== 180` was a CORPUS-SIZE PIN riding
    along inside it, and the two fail for opposite reasons: an unpaired count is a defect, while a
    corpus that changed size is ordinary work in ANOTHER REPO. data-catalog #600 takes the corpus
    to 176 (19 narrowed as unmeasurable-on-a-declared-source, 15 added as newly measured) with
    pairing still exact at 176/176, so the equality pin reds on a PR that strengthens the corpus.
    Worse, it reds in a place no CI job can see (Part 3 header: no workflow checks out both
    repos), so it surfaces only when a human runs `scripts/preland.sh` -- and the cheapest way to
    make a red like that go away is to bump the literal, which is
    `dont_relax_a_gate_to_match_the_build` with extra steps.

    The FLOOR keeps it non-vacuous in the direction that matters. `counts == notes` alone passes
    trivially on an empty or truncated corpus, and coverage RATIOS improve identically whether a
    hard stratum is measured or DELETED -- the #598/#600 lesson that ratio-shaped guards make
    "100% measured" reachable by deletion. A floor only reds when provenanced declarations
    DISAPPEAR, which no legitimate edit does silently; growth is free. Set to the post-#600 count
    deliberately, since the floor must admit the state the very next PR in this arc creates."""
    counts, notes = 0, 0
    for doc in _live_catalogs().values():
        for s in doc.get("atomic_strata") or []:
            for k in s:
                if k.endswith("_denominator_note"):
                    notes += 1
                elif k.startswith("expected_n_"):
                    counts += 1
    assert counts == notes, f"unpaired declarations: {counts} counts / {notes} notes"
    # ★★ 176 -> 174, AND THE PARAGRAPH ABOVE NEEDED A CAVEAT TO SAY SO. It asserted that a DROP
    # means "counts lost their notes or strata were deleted", i.e. that no legitimate edit removes a
    # provenanced declaration. data-catalog #601 is a counterexample and a third cause: RETRACTING a
    # declaration that was never a measurement. Two NSCLC `expected_n_depmap` cells named `exon`, a
    # column DepMap does not carry, so every candidate abstained and the recorded 0 stood over a
    # denominator emptied of candidates. Deleting each cell and narrowing `depmap` out of
    # `applicable_data_sources` is the honest repair, and it costs exactly 2 provenanced
    # declarations.
    #
    # WHICH MEANS THE FLOOR IS NOT A COVERAGE METRIC AND MUST NOT BE READ AS ONE. It is a
    # tripwire against SILENT loss, and the discipline that keeps it honest is that lowering it
    # requires naming the PR and the cells -- as here. A drop that arrives with no such note is
    # still the failure this guard was built for. What the floor cannot distinguish on its own is a
    # retraction from a deletion; that distinction is carried by
    # `cohort_claim_reconciliation.measured_absent.cleared` and by data-catalog's own
    # `NARROWED_2026_09_14` roster, which pins both cells BY NAME so re-adding a `depmap` cell reds
    # there rather than quietly restoring the count here.
    assert counts >= 174, (
        f"provenanced declarations fell to {counts} (floor 174, lowered from 176 by data-catalog "
        "#601 which RETRACTED 2 cells that were never measurements). A DROP means counts lost "
        "their notes, strata were deleted, or a cell was retracted; lower this floor only "
        "alongside the corpus edit that forces it, and name the cells."
    )


@pytestmark_live
def test_declared_cohorts_that_measure_absent_are_exactly_the_pinned_set():
    """★ The invariant the measured ledger made checkable: a cohort in an axis's `cohorts:` is
    a CLAIM that the stratum has members there (the crosswalk header: it records "WHICH axes
    can even carry a given stratum"). `tp_facets_subtype.py` turns that list into `cohorts_of`,
    and `tp_fanout.py` uses it to restrict each card's stratum scope -- so a false claim sends
    the fan-out to build a panorama on a cohort with zero members.

    Five claims are contradicted today. They are NOT fixed here: removing a cohort changes
    which panoramas a profile builds, so it is verdict-bearing and belongs behind stage 3d's
    composed replay diff. They are PINNED BY NAME, the #598 pattern -- a sixth is an error,
    and fixing one requires deleting its entry, so this cannot rot into a permanent allowlist.

    ★★ CORRECTED 2026-09-14 (stage 3d), in TWO ways, and both were defects in THIS test:

    (1) THE PIN WAS 7 AND THE TRUTH IS 5. Two of the seven were NSCLC histology_Adeno / histology_SCC
        on depmap, drawn from `source_excluded`, whose disposition was `needs NO measurement`. Measuring
        the published shard gives 118 and 32 members of 150 evaluable -- both above the floor. Those two
        moved to `source_excluded.measured` in the crosswalk as a FALSIFICATION, so this test now reads
        its pin from `measured_absent.claims` alone.
    (2) THE CONDITION READ A SENTINEL AS EVIDENCE. It admitted `note.startswith("Corrected")`, and the
        note it thereby admitted says, in full, "Reset to the N/A sentinel 0". So a value the catalog
        explicitly labels NOT-A-MEASUREMENT was counted as a measured absence -- the same overloaded-`0`
        defect the crosswalk records at axis level, reproduced in the guard meant to enforce it. Only
        `Observed emit` makes a 0 an absence claim now. That tightening is what takes 7 -> 5, and the
        two it drops are exactly the two the shard falsified: the arithmetic agrees from both ends.
    """
    recon = CROSSWALK["cohort_claim_reconciliation"]
    pinned = {(c["indication"], c["stratum"], c["cohort"]) for c in recon["measured_absent"]["claims"]}
    # ★ 5 -> 3 (data-catalog #601). Two NSCLC pins were retracted rather than resolved: their 0s
    # were recorded against a rule naming `exon`, which the DepMap MAF does not carry, so every
    # candidate abstained and the pin was filing a NON-measurement under `measured_absent`. They
    # move to `.cleared` and are asserted genuinely absent by the test below -- because THIS test
    # `continue`s on a missing key, so a retraction is invisible here and would otherwise read as
    # a clean resolution.
    assert len(pinned) == 3, f"pin set changed shape: {len(pinned)}"

    # ★ SPELLINGS OF `tcga`, derived by that meaning. This read `[c for c in COHORT_FAMILIES if
    # c != "depmap"]` until 2026-09-14, which was an adequate proxy only while COHORT_FAMILIES
    # was a hardcoded 7 of which 6 were tcga spellings. Deriving the family list from the schema
    # took it to 13, and `!= "depmap"` silently became "everything" -- so an `expected_n_genie_bpc`
    # would have been counted as a measurement on the `tcga` cohort. Latent, not active (no
    # catalog carries those keys yet, precisely because the schema forbade them until this
    # commit), and fixed here rather than left for the PR that would have activated it.
    tcga_keys = [f"expected_n_{c}" for c in COHORT_FAMILIES if c == "tcga" or c.startswith("tcga_")]
    catalogs = {n: {s["id"]: s for s in (d.get("atomic_strata") or [])} for n, d in _live_catalogs().items()}

    observed = set()
    for ind in CROSSWALK["indications"]:
        code = ind["canonical_code"]
        for ax in ind.get("axes") or []:
            for sid in ax.get("strata") or []:
                s = catalogs.get(code, {}).get(sid)
                if s is None:
                    continue
                for cohort in ax.get("cohorts") or []:
                    if cohort == "tcga":
                        keys = [k for k in tcga_keys if k in s]
                    else:
                        # ★ WAS `continue`, with the comment "genie/genie_bpc/george_2015: no
                        # catalog declares an n". That was true BY CONSTRUCTION -- the schema
                        # rejected those keys -- and this commit is what makes them writable, so
                        # the same `continue` turns into a blind spot over exactly 7 axis-cohort
                        # claims (COADREAD driver_mutation+line_of_therapy, NSCLC
                        # driver_mutation+fusion+line_of_therapy, PAAD driver_mutation, SCLC napy).
                        # Handling every cohort by its own name closes it in advance instead of
                        # leaving a stale comment to be believed later.
                        keys = [f"expected_n_{cohort}"]
                    if not keys or keys[0] not in s:
                        continue
                    k = keys[0]
                    note = s.get(f"{k}_denominator_note") or ""
                    # ★ ONLY an `Observed emit` 0 is an ABSENCE claim. The same 0 also serves as an N/A
                    # sentinel, and `evaluable == 0` is not `n == 0` -- conflating them is the defect
                    # analysis-methods #626 fixed one level down. `Corrected ...` is DELIBERATELY not
                    # accepted: #598 wrote those notes to say "Reset to the N/A sentinel 0", so admitting
                    # them counts a declared non-measurement as a measurement.
                    if s[k] == 0 and note.startswith("Observed emit"):
                        observed.add((code, sid, cohort))

    assert observed == pinned, (
        "crosswalk cohort claims contradicted by the measured catalogs changed.\n"
        f"  newly contradicted (add to cohort_claim_reconciliation, or fix the claim): {sorted(observed - pinned)}\n"
        f"  no longer contradicted (move the pin to `.cleared` with a state and a reason, or fix "
        f"the claim -- do NOT simply delete it, see the test below): {sorted(pinned - observed)}"
    )


@pytestmark_live
def test_field_absent_pins_are_narrowed_out_not_silently_dropped():
    """★ THE COMPANION TO THE TEST ABOVE, AND THE REASON A RETRACTED PIN IS MOVED RATHER THAN DELETED.

    The test above `continue`s on a missing `expected_n_<cohort>` key, which is right for its own
    question -- an absent cell makes no absence CLAIM. But it means retracting a cell removes the
    stratum from that test's population entirely, so the guard reports "no longer contradicted" for
    a cell nobody is looking at any more. Passing by shrinking the population is the failure mode
    this whole arc is about; here it would have been the guard doing it to itself.

    So every `measured_absent.cleared` entry must prove the retraction actually happened, in BOTH
    halves -- the cell gone AND the cohort gone from `applicable_data_sources`. One without the
    other is the state that produced the original defect: a cohort declared applicable while the
    rule cannot be answered on it is exactly what licenses the next false zero.

    This mirrors data-catalog's `test_narrowed_cell_stays_narrowed`, deliberately. Two repos assert
    the same two halves from opposite sides, because the corpus lives in one and the claim in the
    other, and neither repo's CI can see both.
    """
    recon = CROSSWALK["cohort_claim_reconciliation"]
    cleared = [
        c for c in (recon["measured_absent"].get("cleared") or []) if c.get("state") == "unmeasurable_field_absent"
    ]
    # LIVENESS FIRST. An empty list makes every assertion below unreachable, and this test would
    # then pass most loudly at the moment the declarations it polices were removed.
    assert len(cleared) == 2, (
        f"expected the 2 field-absent retractions from data-catalog #601, found {len(cleared)}. "
        f"Adding one? It needs a `why` naming the absent column and whether the rule is broadenable "
        f"count-preservingly. Removing one? Then the cell is measurable again -- re-measure it."
    )
    catalogs = {n: {s["id"]: s for s in (d.get("atomic_strata") or [])} for n, d in _live_catalogs().items()}
    for c in cleared:
        ind, sid, cohort = c["indication"], c["stratum"], c["cohort"]
        for field in ("was", "why", "cleared_by"):
            assert c.get(field), f"{ind}/{sid}.{cohort} cleared with no `{field}` -- an undocumented retraction"
        s = catalogs.get(ind, {}).get(sid)
        assert s is not None, (
            f"{ind}/{sid} is pinned as a field-absent retraction but no longer exists in the "
            f"catalog. A DELETED stratum is not a retracted cell -- if the stratum went away, this "
            f"pin should too, and the {c['cleared_by']} rationale needs restating."
        )
        assert f"expected_n_{cohort}" not in s, (
            f"{ind}/{sid} re-declares `expected_n_{cohort}` = {s.get(f'expected_n_{cohort}')} after "
            f"being retracted by {c['cleared_by']}. {c['why']} If the source gained the column, "
            f"delete this pin and re-measure; do not restore the old value."
        )
        sources = s.get("applicable_data_sources") or []
        assert cohort not in sources, (
            f"{ind}/{sid} still lists `{cohort}` in applicable_data_sources ({sources}) while "
            f"declaring the cell retracted. That is the licensing half of the original defect: the "
            f"claim says answerable, the rule is not."
        )


@pytestmark_live
def test_sentinel_zeros_are_not_absence_claims_and_the_falsified_pair_is_pinned():
    """The other half of the tightening above: the sentinel `0`s the old condition mistook for absences.

    A `Corrected ... Reset to the N/A sentinel 0` note DECLARES that no run ever evaluated this cohort.
    It is not evidence of zero members -- and for these two strata it is not even true that no run can:
    `depmap-subgroup-assignments-nsclc-v1` measures histology_Adeno at 118 and histology_SCC at 32 of 150
    evaluable, and the manifest's own description already said so. The registry's `cohorts:
    [tcga, depmap]` claim was RIGHT; the catalog is stale in three places at once
    (`applicable_data_sources`, the sentinel count, and `iter1b_status: data_blocked`).

    Pinned by EQUALITY against the crosswalk's `source_excluded.measured` record so that:
      * a THIRD sentinel-0 on a declared cohort is an error -- it needs measuring, not filing; and
      * when the data-catalog correction lands, this test REDS and says to move the pin, instead of a
        falsification quietly outliving the claim it falsified.

    ★★ THE CORRECTION LANDED (data-catalog #600, squash `1addffd`) AND THE TRIPWIRE FIRED AS DESIGNED,
    so `measured` is now empty and the two entries live in `source_excluded.cleared`. Three things
    that a bare deletion of the pin would have thrown away, and which are the reason this test grew
    rather than shrank:

      * `measured: []` is kept as a DECLARED EMPTY LIST. The equality still holds the "a third
        sentinel is an error" half; deleting the key would have retired that half silently.
      * An empty-vs-empty equality is VACUOUS, so it is now preceded by a liveness floor on the
        number of cohort-cells actually examined. Absence only means something once you know the
        scan read a corpus.
      * The cleared entries became a REGRESSION guard in the opposite direction, pinning the measured
        members as values -- because the regression this file is actually vulnerable to is 118 being
        edited back to an estimate, which is non-zero and therefore invisible to the sentinel scan.

    ★ Why a sentinel and a measurement must never share an encoding: #598 reset a declared 60/40 to `0`
    BECAUSE `applicable_data_sources` excluded depmap -- so the backfill took its authority to declare
    N/A from the very declaration that was wrong, and the estimates it discarded (60/40) were closer to
    the measured truth (118/32) than the "Correction" that replaced them.
    """
    recon = CROSSWALK["cohort_claim_reconciliation"]
    excluded = recon["source_excluded"]
    falsified = {(e["indication"], e["stratum"], e["cohort"]) for e in excluded["measured"]}
    for e in [*excluded["measured"], *excluded["cleared"]]:
        assert e["state"] == "measured", (
            f"{e['stratum']}: filed as falsified-by-measurement but state is {e['state']!r}"
        )
        assert e["members"] >= 30, f"{e['stratum']}: {e['members']} members does not clear the floor it is cited for"
        assert e["members"] <= e["evaluable"], f"{e['stratum']}: {e['members']} members of {e['evaluable']} evaluable"

    assert excluded["cleared"], (
        "`source_excluded.cleared` is empty. It is the only surviving record of what this pin "
        "falsified and of the measurements that cleared it -- emptying it retires the regression "
        "guard below without retiring the claim."
    )

    # ★ SPELLINGS OF `tcga`, derived by that meaning rather than by `!= "depmap"`. The proxy was
    # adequate only while COHORT_FAMILIES was a hardcoded 7 of which 6 were tcga spellings; #770
    # derives that list from the schema and takes it to 13, at which point `!= "depmap"` silently
    # means "everything" and an `expected_n_genie_bpc` would be read as a measurement on the
    # `tcga` cohort. Written in this form here so the two PRs cannot interact: at 7 families both
    # spellings yield the identical 6 keys, so this is inert on THIS branch and correct after #770.
    tcga_keys = [f"expected_n_{c}" for c in COHORT_FAMILIES if c == "tcga" or c.startswith("tcga_")]
    catalogs = {n: {s["id"]: s for s in (d.get("atomic_strata") or [])} for n, d in _live_catalogs().items()}

    sentinels = set()
    examined = 0
    for ind in CROSSWALK["indications"]:
        code = ind["canonical_code"]
        for ax in ind.get("axes") or []:
            for sid in ax.get("strata") or []:
                s = catalogs.get(code, {}).get(sid)
                if s is None:
                    continue
                for cohort in ax.get("cohorts") or []:
                    if cohort == "tcga":
                        keys = [k for k in tcga_keys if k in s]
                    else:
                        # ★ WAS a bare `continue`. That skipped genie/genie_bpc/george_2015, which
                        # was correct BY CONSTRUCTION (the schema rejected those keys) and becomes a
                        # blind spot the moment #770 makes them writable -- over the same 7
                        # axis-cohort claims named there. Handling each cohort by its own key name
                        # closes it in advance; the `depmap` special case folds into this.
                        keys = [f"expected_n_{cohort}"]
                    if not keys or keys[0] not in s:
                        continue
                    examined += 1
                    k = keys[0]
                    note = s.get(f"{k}_denominator_note") or ""
                    if s[k] == 0 and not note.startswith("Observed emit"):
                        sentinels.add((code, sid, cohort))

    # ★★ LIVENESS BEFORE THE CEILING. As of data-catalog #600 the honest answer is that there are NO
    # sentinels left, so `sentinels` is legitimately empty -- and an empty set compares equal to an
    # empty `falsified` no matter WHY it is empty. A glob that misses the corpus would do it (the
    # catalogs are quarter-stamped and COADREAD alone sits on 2026-Q2, so a reader hardcoding 2026-Q3
    # silently drops the reference indication), as would a crosswalk axis whose `strata` stopped
    # resolving, or the corpus being deleted outright. Each of those is a BROKEN READ presenting as a
    # clean bill of health. So assert the scan reached a real population FIRST; the emptiness above
    # only carries information once this holds.
    assert examined >= 100, (
        f"the sentinel scan examined only {examined} declared cohort-cells, expected >= 100 "
        f"(measured 121 across 84 strata and 8 indications on 2026-09-14). An empty sentinel set is "
        f"evidence of a clean corpus only if a corpus was actually read."
    )

    assert sentinels == falsified, (
        "the set of DECLARED cohorts carrying a sentinel 0 (a `0` with no measurement behind it) "
        "changed.\n"
        f"  new sentinels (measure them; do not read a 0 as an absence): {sorted(sentinels - falsified)}\n"
        f"  no longer sentinels (the catalog was fixed -- move the pin to source_excluded.cleared): "
        f"{sorted(falsified - sentinels)}"
    )

    # ★★ THE CLEARED PINS GUARD THE OTHER DIRECTION, and the equality above genuinely cannot. A
    # returning `0` would re-enter `sentinels` and red there -- but the more likely regression is a
    # measured 118 edited back to an ESTIMATE: non-zero, so never a sentinel, invisible to every
    # assertion above, and indistinguishable from the 60/40 guess #598 discarded. These cells have
    # been overwritten once already, by the very PR that was correcting provenance. So pin the
    # recorded members as VALUES and require the provenance token to survive alongside them.
    for e in excluded["cleared"]:
        s = catalogs.get(e["indication"], {}).get(e["stratum"])
        assert s is not None, (
            f"{e['indication']}/{e['stratum']}: a cleared pin names a stratum that is no longer in the "
            f"live corpus. The measurement that cleared it can no longer be checked -- do not delete "
            f"the pin to make this pass."
        )
        key = f"expected_n_{e['cohort']}"
        note = s.get(f"{key}_denominator_note") or ""
        assert s.get(key) == e["members"], (
            f"{e['stratum']}: {key} reads {s.get(key)!r} but the cleared pin records a MEASURED "
            f"{e['members']} of {e['evaluable']} evaluable. A 0 means the N/A sentinel was restored "
            f"over a measurement; any other value means the measurement was replaced without "
            f"updating the record that cites it."
        )
        assert note.startswith("Observed emit"), (
            f"{e['stratum']}: {key} = {e['members']} but its note does not begin with 'Observed emit' "
            f"({note[:70]!r}). A count and its provenance token must move together -- that they can "
            f"drift apart is the whole defect this block records."
        )
