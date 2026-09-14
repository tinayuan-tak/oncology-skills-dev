"""`DEFERRED_ANCHORS` / `UNDECLARED_ANCHORS` — expected-absence declarations that nothing asserted.

TWO mechanisms defer an anchor, and they fail differently. `DEFERRED_ANCHORS` gates a label that HAS an
exemplar set (`fusion_driver`); `UNDECLARED_ANCHORS` records a label deliberately given NO exemplar set
(`synthetic_lethal`), which the first mechanism structurally cannot cover. The second half of this file
(2026-09-13) applies the same four checks to it — see the section comment there.

`fusion_driver` is deferred by an EVIDENCED separation failure, not by absence: activating it puts a corner
in the RTK/amp mass rather than on rearrangement, because strong FUS is 2 of 176 columns at 1.2% positive.
Re-measured 2026-09-14 at n=504 and the deferral was RENEWED — leg 3 fails with 42 non-member flips, 40 of
which carry no FUS evidence at all, and precision against the FUS column is 7%.

★ WHY THE EVIDENCE IS NOW STRUCTURED, and why these tests read fields instead of prose. Until 2026-09-14 the
deferral was a bare `frozenset` whose reason lived only in a comment, citing four named witnesses (MET
flipped fusion-dominant, ERBB2 35%, EGFR 20%, CLDN18 31%). By n=504 EVERY ONE had stopped reproducing — MET
sits at 21% and does not flip, ERBB2 at 0%, CLDN18 at 8% — while the CONCLUSION had become better supported
than the anecdote ever implied. Worse, CLDN18/STAD genuinely reads strong FUS (CLDN18-ARHGAP26 is a real
gastric fusion), so "not even a kinase" was mis-specified when it was written. A reader who checked only the
cited witnesses would have concluded the anchor was fixed and activated a corner that is now MORE clearly
wrong. Prose evidence cannot be re-checked, so it decays silently; `measured_on` + `separation_test` +
`scripts/anchor_separation_test.py` make the claim re-runnable, which is the only durable form of a deferral.

★ Why this file exists. Two of `fusion_driver`'s five exemplars — `RET/THCA` and `NTRK1/THCA` — RE-ENTERED
the corpus with the 2026-09-13 expansion. Before that, the anchor would have been skipped anyway for
having no members present, so `DEFERRED_ANCHORS` was belt-and-braces. It is now the ONLY thing keeping a
known-bleeding anchor out of the shipped artifact, and no test read it: deleting the frozenset, or dropping
the `if label in DEFERRED_ANCHORS` branch, would have produced a fully GREEN re-freeze that silently
re-introduced the 2026-09-02 regression.

Structured as the four checks this repo uses for any expected-absence declaration (see TC #752's
`expected_inert_arms`): **dangling** (it names a real anchor), **misdeclared** (the anchor did not in fact
activate), **stale** (the declaration is still load-bearing — an ERROR, not a warning, because a deferral
that no longer does anything documents the opposite of the behaviour), and the **reason** being present
rather than implied — as a RE-RUNNABLE structure, not prose, for the reason above.

A THIRD mechanism is covered in the last section: an exemplar set that only PARTIALLY resolves against the
corpus, which builds an anchor from a silent subset. See the section comment there.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ATLAS = Path(__file__).resolve().parents[1] / "atlas" / "atlas.json"
BUILD = Path(__file__).resolve().parents[1] / "scripts" / "build_atlas.py"


@pytest.fixture(scope="module")
def build_mod():
    spec = importlib.util.spec_from_file_location("build_atlas", BUILD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_atlas"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc():
    return json.loads(ATLAS.read_text())


def test_the_deferral_exists_at_all(build_mod):
    """Positive control: every check below iterates DEFERRED_ANCHORS, so all of them pass vacuously against
    an empty frozenset."""
    assert build_mod.DEFERRED_ANCHORS, "DEFERRED_ANCHORS is empty — the deferral mechanism is gone"


def test_fusion_driver_specifically_is_still_deferred(build_mod):
    """The named pin, and NOT redundant with the positive control above. Every other test here iterates
    whatever DEFERRED_ANCHORS happens to contain, so dropping `fusion_driver` while adding some other label
    keeps the set non-empty and the whole file green — while the one anchor with a MEASURED regression
    behind it activates. The evidence is specific to this anchor, so the guard is too."""
    assert "fusion_driver" in build_mod.DEFERRED_ANCHORS, (
        "fusion_driver is no longer deferred, so the next re-freeze ACTIVATES it (2 of its 5 exemplars are in "
        "the corpus). Re-measured 2026-09-14 at n=504 and the separation test still FAILS: 42 non-member "
        "targets flip their dominant phenotype to fusion_driver, 40 of them with no FUS evidence, and "
        "precision against the FUS column is 7%. The root cause is the FEATURE SPACE, not the exemplar set — "
        "measured on three membership variants, the three legs move in OPPOSITE directions as membership "
        "improves, so they cannot be satisfied together. Do not re-litigate from the exemplar list; re-run "
        "scripts/anchor_separation_test.py and make all three legs PASS in the same PR (skills #1243)."
    )


def test_no_deferred_anchor_dangles(build_mod):
    """DANGLING: a deferred label that names nothing in ANCHOR_SETS protects nothing, and reads as if it
    did."""
    unknown = set(build_mod.DEFERRED_ANCHORS) - set(build_mod.ANCHOR_SETS)
    assert not unknown, f"DEFERRED_ANCHORS names anchors that do not exist: {sorted(unknown)}"


def test_no_deferred_anchor_reached_the_shipped_artifact(build_mod, doc):
    """MISDECLARED: the declaration and the artifact must agree. A deferred anchor appears in
    `anchor_phenotypes_skipped` and must NOT appear in `anchor_phenotypes`."""
    deferred = set(build_mod.DEFERRED_ANCHORS)
    active = set(doc["meta"].get("anchor_phenotypes") or [])
    skipped = set(doc["meta"].get("anchor_phenotypes_skipped") or [])
    leaked = deferred & active
    assert not leaked, (
        f"DEFERRED anchor(s) {sorted(leaked)} ACTIVATED in the shipped atlas. fusion_driver bleeds RTK-ness "
        "into its neighbours: 42 non-member targets take it as their DOMINANT phenotype (measured at n=504), "
        "so those rows now report a fusion phenotype the data does not support. Do not relax this guard — "
        "re-freeze without the anchor, or land a passing separation test first (skills #1243)."
    )
    assert deferred <= skipped, (
        f"deferred anchors missing from meta.anchor_phenotypes_skipped: {sorted(deferred - skipped)} — the "
        "artifact does not record its own deferral, so a consumer cannot tell a deferred anchor from one "
        "that never existed"
    )


def test_the_deferral_is_still_load_bearing(build_mod, doc):
    """★ STALE — an ERROR, not a warning, and the check that makes this whole file worth having.

    A `DEFERRED_ANCHORS` entry only does work when its exemplars are PRESENT in the corpus; with none
    present, the build skips the anchor for absence and the deferral is decoration. This asserts the
    condition that makes the guard live, so the guard cannot quietly become a no-op — and so the day the
    corpus regains the exemplars is a day this test already covered rather than a silent change of state.

    Measured on the 2026-09-13 freeze: 2 of the 5 fusion_driver exemplars (RET/THCA, NTRK1/THCA) are in
    the corpus, having re-entered with the diverse expansion.
    """
    pairs = set(zip(doc["targets"], doc["indications"]))
    for label in sorted(build_mod.DEFERRED_ANCHORS):
        members = build_mod.ANCHOR_SETS.get(label, [])
        present = [tuple(m) for m in members if tuple(m) in pairs]
        assert present, (
            f"DEFERRED anchor '{label}' has no exemplars in the corpus, so the deferral currently changes "
            "NOTHING — the build would skip it for absence anyway. Either the corpus lost them (then this "
            "guard is decoration and the deferral's evidenced reason is misleading) or the exemplar set "
            "was edited. Re-read the deferral rather than deleting this test."
        )


def test_the_deferral_carries_a_prose_reason(build_mod):
    """A bare frozenset is an unexplained absence. The WHY has to survive next to the mechanism, because
    the whole failure mode here is a future session reading `{"fusion_driver"}` and seeing no cost to
    removing it. This covers the ANCHOR_SETS-side comment — the place a reader edits the exemplar list."""
    src = BUILD.read_text()
    for label in build_mod.DEFERRED_ANCHORS:
        i = src.index(f'"{label}":')
        window = src[max(0, i - 2500) : i + 2500]
        assert "DEFERRED" in window and "separat" in window.lower(), (
            f"no prose reason near the '{label}' anchor definition explaining the deferral"
        )


def test_the_deferral_carries_RE_RUNNABLE_evidence(build_mod):
    """★ The check the prose test above CANNOT make, and the reason this declaration stopped being a set.

    A prose window is satisfied by any 2500 characters containing two substrings — including the stale ones.
    It went green for two weeks while every witness the reason named had quietly stopped reproducing. What
    makes a deferral survivable is not that it explains itself but that it can be RE-MEASURED, so the fields
    that make it re-runnable are what get asserted: which corpus the numbers came from, what produced them,
    and a per-leg verdict. Reads the declared structure, not source text — a substring match is not a
    population."""
    for label, spec in sorted(build_mod.DEFERRED_ANCHORS.items()):
        assert isinstance(spec, dict), (
            f"'{label}' maps to {type(spec).__name__}, not a declaration. DEFERRED_ANCHORS regressed to a "
            f"bare collection, which is how the 2026-09-02 evidence rotted unnoticed."
        )
        reason = spec.get("reason") or ""
        assert len(reason) > 200, f"'{label}' carries no substantive reason ({len(reason)} chars)"
        assert "separat" in reason.lower(), (
            f"'{label}''s reason does not reference the separation test that justifies the deferral — an "
            f"un-evidenced deferral is indistinguishable from an oversight, and cannot be overturned"
        )
        corpus = spec.get("measured_on") or ""
        assert corpus and any(c.isdigit() for c in corpus), (
            f"'{label}' does not say WHICH corpus its evidence was measured on ({corpus!r}). Unattributed "
            f"numbers cannot be reproduced, and a deferral whose evidence cannot be reproduced is a deferral "
            f"the next reader will overturn on a hunch."
        )
        legs = spec.get("separation_test") or {}
        assert legs.get("verdict"), f"'{label}' records no separation-test verdict"
        named = [k for k in legs if k.startswith("leg")]
        assert len(named) >= 3, (
            f"'{label}' records {len(named)} legs, not the three the criterion has (centroid isolation, "
            f"exemplar recovery, no bleed). A single overall verdict hides WHICH leg fails, and the legs move "
            f"in different directions — that is the whole finding."
        )


def test_the_measurement_TOOL_the_deferral_cites_actually_exists(build_mod):
    """★ A POINTER THAT NEVER RESOLVES LOOKS LIKE A WORKING ONE.

    `synthetic_lethal`'s reason cites "the separation-test log", which was never committed — so the one
    artifact that could have re-run its verdict does not exist, and that is precisely how ITS evidence became
    unverifiable. `measured_by` must therefore name a path that is really in the tree, or this declaration
    repeats the mistake in a machine-readable costume."""
    skill_root = BUILD.resolve().parents[1]
    for label, spec in sorted(build_mod.DEFERRED_ANCHORS.items()):
        tool = (spec.get("measured_by") or "").strip()
        assert tool, f"'{label}' does not name the tool that produced its numbers"
        path = skill_root / tool  # `measured_by` is declared relative to the skill root
        assert path.exists(), (
            f"'{label}' cites `{tool}`, which does not exist. Either commit the tool or stop citing it — a "
            f"reference to a missing artifact reads as reproducible evidence while being unverifiable."
        )


# --- the OTHER deferral mechanism: deferred by having NO exemplar set at all ---------------------------
# `synthetic_lethal` was deferred on the same kind of evidence as `fusion_driver` (2026-09-13 separation
# test: the SL centroid sat inside the p90 NN scale of BOTH dependency_essential and tsg_loss, CHEK1 FLIPPED
# to SL at 54%), but by a strictly WEAKER mechanism — it simply carries no ANCHOR_SETS entry, so the build
# skips it by never iterating it. DEFERRED_ANCHORS cannot protect it: that frozenset only gates labels that
# HAVE an entry, and `test_no_deferred_anchor_dangles` above would in fact go RED if someone tried to add
# `synthetic_lethal` to it as-is. So the absence is invisible, and pasting the curated exemplar list back in
# ACTIVATES a known-bleeding corner with a green suite. `UNDECLARED_ANCHORS` turns the absence into a
# declaration; these are the same four checks applied to it.


def test_the_undeclared_deferral_exists_at_all(build_mod):
    """Positive control for the checks below, which iterate UNDECLARED_ANCHORS."""
    assert build_mod.UNDECLARED_ANCHORS, "UNDECLARED_ANCHORS is empty — the deferral is undeclared again"


def test_synthetic_lethal_specifically_is_still_undeclared(build_mod):
    """Pinned BY NAME: iterating the declaration is GREEN under a SUBSTITUTION (swap this label for any
    other and every other test here still passes), so the load-bearing member needs its own assertion with
    the evidence in the failure message."""
    assert "synthetic_lethal" in build_mod.UNDECLARED_ANCHORS, (
        "synthetic_lethal is no longer declared as deferred. It does NOT separate: 2026-09-13 test put its "
        "centroid inside the p90 NN scale (~6.30) of dependency_essential (5.94) and tsg_loss (5.37), only "
        "3/6 exemplars recovered (WRN->tsg_loss 37%, PARP1->amp_driver 36%), and DDR dependencies bled in "
        "(CHEK1 FLIPPED to synthetic_lethal 54%, WEE1 38%). Root cause is the feature space (SL claim signal "
        "129/213 rows vs dependency::COND 2-3/213), not the exemplar count — re-run the separation test and "
        "make it PASS before removing this."
    )


def test_no_undeclared_anchor_carries_an_exemplar_set(build_mod):
    """The mechanism itself: these labels are deferred BY having no ANCHOR_SETS entry, so an entry appearing
    is the activation this file exists to catch. Mirrors the producer-boundary check in build()."""
    activated = sorted(set(build_mod.UNDECLARED_ANCHORS) & set(build_mod.ANCHOR_SETS))
    assert not activated, (
        f"{activated} are declared deferred in UNDECLARED_ANCHORS but now have an ANCHOR_SETS entry, which "
        f"ACTIVATES them: " + " | ".join(f"{k}: {build_mod.UNDECLARED_ANCHORS[k]['reason']}" for k in activated)
    )


def test_the_undeclared_deferral_is_still_load_bearing(build_mod, doc):
    """STALE-as-ERROR. If the declared exemplars were NOT in the corpus, the label would be skipped anyway
    for having no members present and this whole declaration would document a hypothetical. They ARE in the
    corpus (WRN/COADREAD, PARP1/BRCA, ATR/OV, POLQ/BRCA, MAT2A/PAAD, RAD51/OV all shipped 2026-09-13), so
    restoring an entry activates the anchor on the NEXT build with no further data work — which is exactly
    the accident being guarded. Read from the declaration, not a hardcoded list."""
    pairs = set(zip(doc["targets"], doc["indications"]))
    for label, spec in sorted(build_mod.UNDECLARED_ANCHORS.items()):
        exemplars = [tuple(m) for m in spec["exemplars"]]
        assert exemplars, f"'{label}' declares no exemplars — nothing pins that the deferral still matters"
        present = [m for m in exemplars if m in pairs]
        assert present, (
            f"none of '{label}''s {len(exemplars)} declared exemplars {exemplars} are in the shipped corpus, "
            f"so this deferral is no longer load-bearing (the anchor would be skipped for absence anyway). "
            f"Either the corpus lost them — re-run the separation test against the CURRENT corpus before "
            f"trusting the evidence — or the exemplar list drifted from the panel."
        )


def test_no_undeclared_anchor_reached_the_shipped_artifact(build_mod, doc):
    """Deferral-by-absence leaves NO trace in the artifact — that is its defining weakness, and the
    assertion has to encode it: the label must appear in neither the active anchors nor the skipped list.
    (`anchor_phenotypes_skipped` is populated from the ANCHOR_SETS loop, so a label with no entry cannot get
    in there. If a future re-freeze DOES stamp these labels into meta, this test is where that shows up.)"""
    undeclared = set(build_mod.UNDECLARED_ANCHORS)
    active = set(doc["meta"].get("anchor_phenotypes") or [])
    skipped = set(doc["meta"].get("anchor_phenotypes_skipped") or [])
    assert active, "artifact declares no active anchors — the check below would be vacuous"
    assert not (undeclared & active), (
        f"{sorted(undeclared & active)} are declared deferred but ARE anchors in the shipped atlas — the "
        f"artifact was built from a tree where the exemplar set existed. Re-freeze or re-defer."
    )
    assert not (undeclared & skipped), (
        f"{sorted(undeclared & skipped)} appear in anchor_phenotypes_skipped, which means they had an "
        f"ANCHOR_SETS entry at build time (that list only ever names labels the loop iterated)."
    )


def test_the_undeclared_deferral_carries_its_evidence(build_mod):
    """The reason must be a real evidence statement, not a TODO. Keyed on the declared structure rather
    than a prose window: a substring match on source text is not a population."""
    for label, spec in sorted(build_mod.UNDECLARED_ANCHORS.items()):
        reason = spec.get("reason") or ""
        assert len(reason) > 200, f"'{label}' carries no substantive reason ({len(reason)} chars)"
        assert "separat" in reason.lower(), (
            f"'{label}''s reason does not reference the separation test that justifies the deferral — an "
            f"un-evidenced deferral is indistinguishable from an oversight, and cannot be overturned"
        )


def test_the_build_itself_refuses_an_activated_deferral(build_mod, monkeypatch):
    """★ The guard exercised, not just described. A guard bound to the TEST SUITE cannot protect the caller
    that skips it — `build_atlas.py` is run by hand for a re-freeze — so the refusal lives at the producer
    boundary and this asserts it actually fires, with the evidence in the message."""
    monkeypatch.setitem(build_mod.ANCHOR_SETS, "synthetic_lethal", [("WRN", "COADREAD")])
    with pytest.raises(SystemExit) as e:
        build_mod.build([], Path("/nonexistent/panel.tsv"), "2026-01-01")
    msg = str(e.value)
    assert "synthetic_lethal" in msg and "CHEK1" in msg, msg


def test_the_build_refuses_a_dangling_deferred_anchor(build_mod, monkeypatch):
    """The other half of the producer check: a DEFERRED_ANCHORS label with no ANCHOR_SETS entry is a
    DECORATIVE guard (the skip loop iterates ANCHOR_SETS), which reads as protection while providing none.

    The patched value is a DICT, matching the production shape. It used to be a frozenset, which passed for
    the wrong reason: `_assert_deferral_declarations_consistent` only does set algebra on the KEYS, so a
    frozenset satisfies it identically — the test would have stayed green after the declaration grew fields
    it never touched, i.e. it exercised a shape the build no longer uses."""
    monkeypatch.setattr(
        build_mod,
        "DEFERRED_ANCHORS",
        {"fusion_driver": build_mod.DEFERRED_ANCHORS["fusion_driver"], "not_an_anchor": {"reason": "x" * 250}},
    )
    with pytest.raises(SystemExit) as e:
        build_mod.build([], Path("/nonexistent/panel.tsv"), "2026-01-01")
    assert "not_an_anchor" in str(e.value)


@pytest.mark.parametrize(
    "shape,expect",
    [
        (frozenset({"fusion_driver"}), "frozenset"),
        ({"fusion_driver": "a prose reason with no measurement in it"}, "fusion_driver"),
    ],
    ids=["whole_container_reverted", "one_entry_left_as_prose"],
)
def test_the_build_refuses_an_UNSTRUCTURED_deferral(build_mod, monkeypatch, shape, expect):
    """★ The regression this guards is a REVERT, and it is invisible to every other check here.

    Both parametrised shapes keep `fusion_driver` deferred, so the skip loop (`label in DEFERRED_ANCHORS`)
    and the dangling check (set algebra over the keys) are BOTH satisfied — a frozenset of labels is a
    perfectly good membership test. What is lost is the evidence: `measured_on`, `measured_by` and the
    separation-test legs, i.e. the only reason a future reader could re-run rather than trust. The 2026-09-02
    prose reason rotted precisely because it was unstructured, so the shape is load-bearing, not stylistic.

    The two cases fail on DIFFERENT lines and that is the point of parametrising: an `isinstance(v, dict)`
    sweep over `.values()` cannot report the first case, because `.values()` is exactly what a frozenset does
    not have — it would raise AttributeError from inside the guard and blame the guard.

    ★ `SystemExit` (not FileNotFoundError) on a deliberately NONEXISTENT panel is the load-bearing half of the
    assertion, and it was measured: deleting the check makes both cases fail with FileNotFoundError on that
    path. So the refusal is reached BEFORE any corpus or panel I/O — it is a check on the DECLARATION, needing
    no corpus, which is what lets it run first and name the shape while the deferral is still the subject."""
    monkeypatch.setattr(build_mod, "DEFERRED_ANCHORS", shape)
    with pytest.raises(SystemExit) as e:
        build_mod.build([], Path("/nonexistent/panel.tsv"), "2026-01-01")
    msg = str(e.value)
    assert "BUILD REFUSED" in msg and expect in msg, msg
    assert "evidence" in msg, f"the refusal must say what the shape is FOR, not merely that it is wrong: {msg}"


def test_the_build_does_not_refuse_the_shipped_declarations(build_mod):
    """Both poles: the refusals above must not be firing on the tree as it stands, or every build is red."""
    build_mod._assert_deferral_declarations_consistent()


# --- the THIRD mechanism: an exemplar set that only PARTIALLY resolves -----------------------------------
# Both mechanisms above ask "did a deferred label activate?". Neither asks whether an ACTIVE anchor was built
# from the set it declares. `fusion_driver` names five exemplars and only TWO can ever resolve: the corpus
# files ALK and ROS1 only under `NSCLC` (the spec says LUAD) and has no `CHOL` rows at all, so its centroid
# would be a 2-row THCA-only average of a set curated to span four indications. That shipped, unnoticed,
# through every freeze — identical against the n=297 atlas and the n=504 build, so it is spec rot, not
# panel-expansion fallout. Three things had to fail at once for it to stay invisible:
#   * the ARTIFACT is self-consistent — `n_members` and `members` both describe the surviving subset, and
#     test_target_archetype.py asserts exactly that pair, i.e. artifact-vs-artifact and never artifact-vs-SPEC;
#   * the existing WARN only fires on `not present`, and 2 != 0; and
#   * for a DEFERRED anchor `present` is never computed at all — the skip `continue`s first — so a deferred
#     anchor's exemplars were not ELIGIBLE to be checked by anything inside the loop, which is why the miss
#     survived the very re-freeze that introduced the deferral.
# `_assert_anchor_exemplars_resolve` closes it from OUTSIDE the loop, over every label. Same four checks.


@pytest.fixture(scope="module")
def corpus_keys(doc):
    return set(zip(doc["targets"], doc["indications"]))


def test_the_unresolvable_declaration_matches_the_shipped_corpus_EXACTLY(build_mod, doc, corpus_keys):
    """★ DANGLING + STALE together, against real data rather than a mutation.

    Asserts set EQUALITY, not containment: over-declaring is as wrong as under-declaring, because the
    declaration is cited as evidence (the deferral's reason argues from "a 2-row THCA-only subset"). A
    containment check would let the list grow into a wishlist while still reading as a measurement.

    Pins the expected counts BY NAME as well, because iterating the declaration is green under a
    substitution — and the counts are the finding: exactly 3 for fusion_driver, and ZERO for every other
    anchor, which is what establishes this as one anchor's spec rot rather than a corpus-wide gap."""
    expected = {"fusion_driver": 3}
    for label, members in sorted(build_mod.ANCHOR_SETS.items()):
        missing = {tuple(m) for m in members if tuple(m) not in corpus_keys}
        declared = {tuple(x) for x in (build_mod.DEFERRED_ANCHORS.get(label) or {}).get("unresolvable_exemplars", ())}
        assert declared == missing, (
            f"'{label}': `unresolvable_exemplars` declares {sorted(declared)} but the exemplars actually "
            f"missing from the shipped corpus are {sorted(missing)}. Extra entries are decorative; missing "
            f"entries mean the anchor is built from an undeclared subset. If the corpus GAINED a row, delete "
            f"the entry and RE-RUN scripts/anchor_separation_test.py — the anchor's membership, and therefore "
            f"its centroid, is not what the recorded evidence measured."
        )
        assert len(missing) == expected.get(label, 0), (
            f"'{label}' now has {len(missing)} unresolvable exemplars, expected {expected.get(label, 0)}. "
            f"A NEW one means an exemplar spec and the corpus vocabulary have diverged: check the corpus "
            f"indication token before substituting a different indication, because that can change the "
            f"biology (gastric FGFR2 is amplification-driven, not fusion-driven)."
        )


def test_the_guard_does_not_fire_on_the_shipped_corpus(build_mod, corpus_keys):
    """Pole one: green on the tree as it stands, or every re-freeze is red."""
    build_mod._assert_anchor_exemplars_resolve(corpus_keys)


def test_the_guard_refuses_an_UNDECLARED_partial_anchor(build_mod, corpus_keys, monkeypatch):
    """Pole two, and the exact pre-2026-09-14 state: the deferral present, the misses undeclared. This is
    what the tree looked like while it was shipping a 2-row anchor spec, so if this does not RAISE, the guard
    would not have caught the bug it was written for."""
    monkeypatch.setattr(build_mod, "DEFERRED_ANCHORS", {"fusion_driver": {"reason": "prose only, no fields"}})
    with pytest.raises(SystemExit) as e:
        build_mod._assert_anchor_exemplars_resolve(corpus_keys)
    msg = str(e.value)
    assert "PARTIALLY" in msg and "ALK/LUAD" in msg, msg


def test_the_guard_refuses_a_STALE_unresolvable_declaration(build_mod, corpus_keys):
    """STALE as an ERROR: a declared-unresolvable exemplar the corpus has since GAINED silently changes the
    anchor's membership, so the recorded legs describe a centroid that no longer exists. Simulated by growing
    the corpus rather than by editing the declaration — that is the direction the real change arrives from."""
    grown = set(corpus_keys) | {("ALK", "LUAD")}
    with pytest.raises(SystemExit) as e:
        build_mod._assert_anchor_exemplars_resolve(grown)
    msg = str(e.value)
    assert "NOW RESOLVE" in msg and "ALK/LUAD" in msg, msg
    assert "RE-RUN the separation test" in msg, "a stale declaration must direct the reader to re-measure"


def test_the_guard_refuses_a_declaration_for_a_NON_exemplar(build_mod, corpus_keys, monkeypatch):
    """DANGLING: a declaration naming a pair that is not an exemplar of that anchor guards nothing. The
    probe pair must be absent from the corpus too, or the STALE leg fires instead and this passes for the
    wrong reason — which is what happened the first time this was probed (BRAF/SKCM is a real corpus row)."""
    fake = ("ZZZ9", "NOSUCH")
    assert fake not in corpus_keys, "probe invalid: the pair is in the corpus, so STALE would fire instead"
    spec = dict(build_mod.DEFERRED_ANCHORS["fusion_driver"])
    spec["unresolvable_exemplars"] = list(spec["unresolvable_exemplars"]) + [fake]
    monkeypatch.setattr(build_mod, "DEFERRED_ANCHORS", {"fusion_driver": spec})
    with pytest.raises(SystemExit) as e:
        build_mod._assert_anchor_exemplars_resolve(corpus_keys)
    msg = str(e.value)
    assert "ZZZ9/NOSUCH" in msg and "not in this anchor's ANCHOR_SETS entry" in msg, msg


def test_a_FULLY_absent_anchor_is_still_allowed(build_mod, corpus_keys):
    """The designed exception, asserted so it cannot be tightened by accident. An anchor with NO members
    present is aspirational — the exemplar spec carries the panel forward and the anchor activates when its
    runs land — and it is already LOUD, because the label is simply missing from `anchors`. Only PARTIAL
    resolution ships something wrong while looking complete."""
    label = "control_housekeeping"
    without = {k for k in corpus_keys if k not in {tuple(m) for m in build_mod.ANCHOR_SETS[label]}}
    assert len(without) < len(corpus_keys), "probe invalid: the anchor's members were not actually removed"
    build_mod._assert_anchor_exemplars_resolve(without)


def test_the_guard_is_WIRED_INTO_build_not_merely_defined(build_mod):
    """★ A guard the producer never calls is a guard bound to this suite — and the caller that matters runs
    `build_atlas.py` by hand for a re-freeze, skipping the suite entirely. The other producer checks are
    exercised through `build()` directly, but this one cannot be: it runs after the corpus is loaded, so an
    empty-input build dies earlier for unrelated reasons and would report the wrong thing.

    So the wiring is asserted structurally — an AST call-site search inside `build`, NOT a substring match on
    the source, which a mention in a comment or docstring would satisfy."""
    import ast

    tree = ast.parse(BUILD.read_text())
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build"), None)
    assert fn is not None, "build() not found in build_atlas.py"
    called = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for guard in ("_assert_deferral_declarations_consistent", "_assert_anchor_exemplars_resolve"):
        assert hasattr(build_mod, guard), f"{guard} no longer exists"
        assert guard in called, (
            f"build() does not call {guard}() — the check is DEFINED but not wired in, so it only ever runs "
            f"from this test file and a hand-run re-freeze is unprotected."
        )
