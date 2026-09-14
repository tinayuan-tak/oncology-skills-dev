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
`dependentRequired` over all seven cohort families, `minLength` on the provenance notes, and
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
DATA_CATALOG = Path(
    os.environ.get("DATA_CATALOG_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog")
)
CATALOG_DIR = DATA_CATALOG / "subgroup-catalogs"

# Validate a bare stratum without hand-building a whole catalog around it.
STRATUM = Draft202012Validator({"$ref": "#/$defs/atomic_stratum", "$defs": SCHEMA["$defs"]})
CATALOG = Draft202012Validator(SCHEMA)

# The seven cohort families the corpus actually spells. One `--data-source tcga` run writes a
# key under six different names across the nine catalogs, which is why this is a LIST rather
# than a `tcga`/`depmap` pair -- see the "six spellings" note in
# vocabularies/subtype_crosswalk.yaml.
COHORT_FAMILIES = [
    "tcga",
    "depmap",
    "tcga_coadread",
    "tcga_pdac",
    "tcga_nsclc",
    "tcga_sclc",
    "tcga_gc",
]

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
    """The `dependentRequired` ratchet, measured against reality rather than fixtures: 180
    counts and 180 notes, pairing exactly, in all seven families."""
    counts, notes = 0, 0
    for doc in _live_catalogs().values():
        for s in doc.get("atomic_strata") or []:
            for k in s:
                if k.endswith("_denominator_note"):
                    notes += 1
                elif k.startswith("expected_n_"):
                    counts += 1
    assert counts == notes == 180, f"expected 180 paired declarations, got {counts} counts / {notes} notes"


@pytestmark_live
def test_declared_cohorts_that_measure_absent_are_exactly_the_pinned_set():
    """★ The invariant the measured ledger made checkable: a cohort in an axis's `cohorts:` is
    a CLAIM that the stratum has members there (the crosswalk header: it records "WHICH axes
    can even carry a given stratum"). `tp_facets_subtype.py` turns that list into `cohorts_of`,
    and `tp_fanout.py` uses it to restrict each card's stratum scope -- so a false claim sends
    the fan-out to build a panorama on a cohort with zero members.

    Seven claims are contradicted today. They are NOT fixed here: removing a cohort changes
    which panoramas a profile builds, so it is verdict-bearing and belongs behind stage 3d's
    composed replay diff. They are PINNED BY NAME, the #598 pattern -- an eighth is an error,
    and fixing one requires deleting its entry, so this cannot rot into a permanent allowlist.
    """
    recon = CROSSWALK["cohort_claim_reconciliation"]
    pinned = {
        (c["indication"], c["stratum"], c["cohort"])
        for cls in ("measured_absent", "source_excluded")
        for c in recon[cls]["claims"]
    }
    assert len(pinned) == 7, f"pin set changed shape: {len(pinned)}"

    tcga_keys = [f"expected_n_{c}" for c in COHORT_FAMILIES if c != "depmap"]
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
                    if cohort == "depmap":
                        keys = ["expected_n_depmap"]
                    elif cohort == "tcga":
                        keys = [k for k in tcga_keys if k in s]
                    else:
                        continue  # genie/genie_bpc/george_2015: no catalog declares an n
                    if not keys or keys[0] not in s:
                        continue
                    k = keys[0]
                    note = s.get(f"{k}_denominator_note") or ""
                    # ★ Only an `Observed emit` 0 is an ABSENCE claim. The same 0 also serves as
                    # an N/A sentinel, and `evaluable == 0` is not `n == 0` -- conflating them is
                    # the defect analysis-methods #626 fixed one level down.
                    if s[k] == 0 and (note.startswith("Observed emit") or note.startswith("Corrected")):
                        observed.add((code, sid, cohort))

    assert observed == pinned, (
        "crosswalk cohort claims contradicted by the measured catalogs changed.\n"
        f"  newly contradicted (add to cohort_claim_reconciliation, or fix the claim): {sorted(observed - pinned)}\n"
        f"  no longer contradicted (delete the pin): {sorted(pinned - observed)}"
    )
